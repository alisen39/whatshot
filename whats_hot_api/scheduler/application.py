"""Scheduler orchestration and the only path that can persist captures."""

from __future__ import annotations

import asyncio
import hashlib
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from whats_hot_api.fetch import CachePolicy, FetchError, FetchRequest, FetchService
from whats_hot_api.history.models import CaptureBatch, RunStart, TriggerKind
from whats_hot_api.scheduler.config import AppConfig, SchedulerJob
from whats_hot_api.scheduler.writer_actor import SchedulerWriterActor
from whats_hot_api.utils.logger import logger


class SchedulerError(Exception):
    code = "SCHEDULER_ERROR"


class JobNotFoundError(SchedulerError):
    code = "JOB_NOT_FOUND"


class JobAlreadyRunningError(SchedulerError):
    code = "JOB_ALREADY_RUNNING"


class SchedulerRunNotFoundError(SchedulerError):
    code = "RUN_NOT_FOUND"


class CachedCaptureRejectedError(SchedulerError):
    code = "CACHED_CAPTURE_REJECTED"


class StorageDisabledError(SchedulerError):
    code = "STORAGE_DISABLED"


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    run_key: str
    job_id: str
    status: str
    capture_id: str | None
    started_at: datetime
    finished_at: datetime
    error_code: str | None = None
    error_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "runKey": self.run_key,
            "jobId": self.job_id,
            "status": self.status,
            "captureId": self.capture_id,
            "startedAt": self.started_at.isoformat(),
            "finishedAt": self.finished_at.isoformat(),
            "errorCode": self.error_code,
            "errorMessage": self.error_message,
        }


class SchedulerApplication:
    def __init__(
        self,
        *,
        config: AppConfig,
        fetch_service: FetchService,
        retry_delays: tuple[float, ...] = (5.0, 30.0),
        random_source: random.Random | None = None,
    ) -> None:
        self.config = config
        self.fetch_service = fetch_service
        self._jobs = {job.id: job for job in config.jobs}
        self._retry_delays = retry_delays
        self._random = random_source or random.Random()
        self._writer = (
            SchedulerWriterActor(
                config.storage.path,
                queue_size=config.scheduler.writer_queue_size,
                checkpoint_on_shutdown=config.storage.checkpoint_on_shutdown,
            )
            if config.storage.enabled
            else None
        )
        self._semaphore = asyncio.Semaphore(config.scheduler.max_fetch_concurrency)
        self._job_locks = {job.id: asyncio.Lock() for job in config.jobs}
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._operation_tasks: set[asyncio.Task[None]] = set()
        self._operations: dict[str, dict[str, Any]] = {}
        self._pending_jobs: set[str] = set()
        self._last_results: dict[str, RunResult] = {}
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._stop_event = asyncio.Event()
        self._semaphore = asyncio.Semaphore(self.config.scheduler.max_fetch_concurrency)
        self._job_locks = {job.id: asyncio.Lock() for job in self.config.jobs}
        self._operation_tasks.clear()
        self._pending_jobs.clear()
        if self._writer is None:
            self._started = True
            return
        await self._writer.start()
        self._started = True
        if self.config.scheduler.enabled:
            for job in self.config.jobs:
                if job.enabled:
                    self._tasks.append(
                        asyncio.create_task(
                            self._job_loop(job),
                            name=f"whatshot-scheduler-{job.id}",
                        )
                    )
            self._tasks.append(
                asyncio.create_task(
                    self._maintenance_loop(),
                    name="whatshot-scheduler-maintenance",
                )
            )

    async def stop(self) -> None:
        if not self._started:
            return
        self._stop_event.set()
        active_tasks = [*self._tasks, *self._operation_tasks]
        if active_tasks:
            try:
                async with asyncio.timeout(
                    self.config.scheduler.shutdown_grace_seconds
                ):
                    await asyncio.gather(*active_tasks, return_exceptions=True)
            except TimeoutError:
                for task in active_tasks:
                    task.cancel()
                await asyncio.gather(*active_tasks, return_exceptions=True)
        self._tasks.clear()
        self._operation_tasks.clear()
        self._pending_jobs.clear()
        if self._writer is not None:
            await self._writer.stop()
        self._started = False

    async def trigger(self, job_id: str) -> RunResult:
        return await self.run_once(job_id, trigger_kind="manual")

    def submit_trigger(self, job_id: str) -> dict[str, Any]:
        self._require_storage()
        if not self._started:
            raise SchedulerError("Scheduler is not running.")
        if job_id not in self._jobs:
            raise JobNotFoundError(f"Unknown scheduler job '{job_id}'.")
        if job_id in self._pending_jobs or self._job_locks[job_id].locked():
            raise JobAlreadyRunningError(
                f"Scheduler job '{job_id}' is already running."
            )
        self._prune_operations()
        operation_id = str(uuid4())
        submitted_at = datetime.now(UTC)
        operation = {
            "operationId": operation_id,
            "jobId": job_id,
            "status": "accepted",
            "submittedAt": submitted_at.isoformat(),
        }
        self._operations[operation_id] = operation
        self._pending_jobs.add(job_id)
        task = asyncio.create_task(
            self._run_trigger_operation(operation_id, job_id),
            name=f"whatshot-trigger-{operation_id}",
        )
        self._operation_tasks.add(task)
        task.add_done_callback(self._operation_tasks.discard)
        return dict(operation)

    def get_trigger_operation(self, operation_id: str) -> dict[str, Any]:
        operation = self._operations.get(operation_id)
        if operation is None:
            raise SchedulerRunNotFoundError(f"Unknown scheduler run '{operation_id}'.")
        return dict(operation)

    async def run_once(
        self,
        job_id: str,
        *,
        trigger_kind: TriggerKind = "manual",
        scheduled_for: datetime | None = None,
    ) -> RunResult:
        self._require_storage()
        if not self._started:
            raise SchedulerError("Scheduler is not running.")
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(f"Unknown scheduler job '{job_id}'.")
        lock = self._job_locks[job_id]
        if lock.locked():
            raise JobAlreadyRunningError(
                f"Scheduler job '{job_id}' is already running."
            )
        async with lock, self._semaphore:
            return await self._run_attempts(
                job,
                trigger_kind=trigger_kind,
                scheduled_for=scheduled_for,
            )

    def status(self) -> dict[str, Any]:
        return {
            "running": self._started and self._writer is not None,
            "storageEnabled": self.config.storage.enabled,
            "writerQueueDepth": (
                self._writer.queue_depth if self._writer is not None else None
            ),
            "jobs": [
                {
                    "id": job.id,
                    "site": job.site,
                    "boardKey": job.board_key,
                    "enabled": job.enabled,
                    "intervalSeconds": job.interval_seconds,
                    "running": self._job_locks[job.id].locked(),
                    "lastRun": (
                        self._last_results[job.id].as_dict()
                        if job.id in self._last_results
                        else None
                    ),
                }
                for job in self.config.jobs
            ],
        }

    async def _run_trigger_operation(
        self,
        operation_id: str,
        job_id: str,
    ) -> None:
        operation = self._operations[operation_id]
        operation["status"] = "running"
        operation["startedAt"] = datetime.now(UTC).isoformat()
        try:
            result = await self.trigger(job_id)
            operation.update(result.as_dict())
        except asyncio.CancelledError:
            operation.update(
                {
                    "status": "failed",
                    "errorCode": "SCHEDULER_STOPPED",
                    "errorMessage": "Scheduler stopped before the run completed.",
                    "finishedAt": datetime.now(UTC).isoformat(),
                }
            )
            raise
        except SchedulerError as exc:
            operation.update(
                {
                    "status": "failed",
                    "errorCode": exc.code,
                    "errorMessage": str(exc),
                    "finishedAt": datetime.now(UTC).isoformat(),
                }
            )
        except Exception as exc:  # noqa: BLE001 - keep operation status observable
            logger.error(
                f"Scheduler trigger {operation_id} failed with {type(exc).__name__}"
            )
            operation.update(
                {
                    "status": "failed",
                    "errorCode": "SCHEDULER_ERROR",
                    "errorMessage": "Scheduler run failed unexpectedly.",
                    "finishedAt": datetime.now(UTC).isoformat(),
                }
            )
        finally:
            self._pending_jobs.discard(job_id)

    def _prune_operations(self) -> None:
        if len(self._operations) < 1000:
            return
        completed = [
            operation_id
            for operation_id, operation in self._operations.items()
            if operation["status"] in {"success", "failed"}
        ]
        for operation_id in completed[:500]:
            self._operations.pop(operation_id, None)

    async def _run_attempts(
        self,
        job: SchedulerJob,
        *,
        trigger_kind: TriggerKind,
        scheduled_for: datetime | None,
    ) -> RunResult:
        assert self._writer is not None
        scheduled = scheduled_for or datetime.now(UTC)
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=UTC)
        request_id = str(uuid4()) if trigger_kind == "manual" else ""
        run_key = self._run_key(job.id, scheduled, trigger_kind, request_id)
        run_id = str(uuid5(NAMESPACE_URL, f"whatshot:run:{run_key}"))
        started_at = datetime.now(UTC)
        last_error: Exception | None = None

        for attempt in range(1, len(self._retry_delays) + 2):
            run = RunStart(
                run_id=run_id,
                run_key=run_key,
                job_id=job.id,
                trigger_kind=trigger_kind,
                scheduled_for=scheduled,
                started_at=started_at,
                attempt=attempt,
            )
            await self._writer.call("record_run_started", run)
            try:
                async with asyncio.timeout(
                    self.config.scheduler.request_timeout_seconds
                ):
                    fetched = await self.fetch_service.fetch(
                        FetchRequest(
                            site=job.site,
                            path_type=job.path_type,
                            params=job.params,
                            limit=job.limit,
                            cache_policy=CachePolicy.REFRESH,
                        )
                    )
                if fetched.from_cache:
                    raise CachedCaptureRejectedError(
                        "Scheduler refresh returned cached data."
                    )
                capture_id = str(uuid5(NAMESPACE_URL, f"whatshot:capture:{run_key}"))
                await self._writer.call(
                    "persist_capture",
                    CaptureBatch(
                        capture_id=capture_id,
                        run=run,
                        board_key=job.board_key,
                        fetch_result=fetched,
                    ),
                )
                result = RunResult(
                    run_id=run_id,
                    run_key=run_key,
                    job_id=job.id,
                    status="success",
                    capture_id=capture_id,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                )
                self._last_results[job.id] = result
                return result
            except Exception as exc:  # noqa: BLE001 - persist every job failure
                last_error = exc
                error_code = getattr(exc, "code", type(exc).__name__)
                await self._writer.call(
                    "record_run_failure",
                    run,
                    error_code=str(error_code),
                    error_message=str(exc),
                )
                retryable = (
                    isinstance(exc, FetchError) and exc.retryable
                ) or isinstance(exc, TimeoutError)
                if not retryable or attempt > len(self._retry_delays):
                    break
                await asyncio.sleep(self._retry_delays[attempt - 1])

        assert last_error is not None
        result = RunResult(
            run_id=run_id,
            run_key=run_key,
            job_id=job.id,
            status="failed",
            capture_id=None,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            error_code=str(getattr(last_error, "code", type(last_error).__name__)),
            error_message=str(last_error),
        )
        self._last_results[job.id] = result
        return result

    async def _job_loop(self, job: SchedulerJob) -> None:
        loop = asyncio.get_running_loop()
        next_deadline = loop.time()
        if not job.run_on_start:
            next_deadline += job.interval_seconds
        while not self._stop_event.is_set():
            jitter = (
                self._random.uniform(0, self.config.scheduler.jitter_seconds)
                if self.config.scheduler.jitter_seconds
                else 0
            )
            delay = max(0.0, next_deadline + jitter - loop.time())
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                break
            except TimeoutError:
                pass
            try:
                await self.run_once(
                    job.id,
                    trigger_kind="interval",
                    scheduled_for=datetime.now(UTC),
                )
            except JobAlreadyRunningError:
                logger.warning(f"⏭️ Scheduler job already running: {job.id}")
            except Exception:  # noqa: BLE001 - keep other jobs running
                logger.exception(f"❌ Scheduler job failed unexpectedly: {job.id}")
            next_deadline += job.interval_seconds
            while next_deadline <= loop.time():
                next_deadline += job.interval_seconds

    async def _maintenance_loop(self) -> None:
        assert self._writer is not None
        while not self._stop_event.is_set():
            try:
                await self._writer.call(
                    "apply_retention",
                    self.config.storage.retention_days,
                )
            except Exception:  # noqa: BLE001 - retry maintenance on the next cycle
                logger.exception("❌ Scheduler retention task failed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=24 * 60 * 60,
                )
            except TimeoutError:
                continue

    def _require_storage(self) -> None:
        if self._writer is None:
            raise StorageDisabledError("History storage is disabled.")

    @staticmethod
    def _run_key(
        job_id: str,
        scheduled_for: datetime,
        trigger_kind: TriggerKind,
        request_id: str,
    ) -> str:
        identity = (
            f"{job_id}|manual|{request_id}"
            if trigger_kind == "manual"
            else f"{job_id}|{scheduled_for.astimezone(UTC).isoformat()}"
        )
        return hashlib.sha256(identity.encode()).hexdigest()

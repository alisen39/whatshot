"""Async queue around the Scheduler-exclusive synchronous DuckDB writer."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from whats_hot_api.scheduler.storage import SchedulerDuckDBWriter


@dataclass(slots=True)
class _WriterCommand:
    method: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    future: asyncio.Future[Any]


class SchedulerWriterActor:
    def __init__(
        self,
        path: str | Path,
        *,
        queue_size: int = 32,
        checkpoint_on_shutdown: bool = True,
    ) -> None:
        self._path = path
        self._queue_size = queue_size
        self._checkpoint_on_shutdown = checkpoint_on_shutdown
        self._queue: asyncio.Queue[_WriterCommand | None] = asyncio.Queue(
            maxsize=queue_size
        )
        self._executor: ThreadPoolExecutor | None = None
        self._writer: SchedulerDuckDBWriter | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._queue = asyncio.Queue(maxsize=self._queue_size)
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="whatshot-duckdb-writer",
        )
        loop = asyncio.get_running_loop()
        try:
            self._writer = await loop.run_in_executor(
                self._executor,
                SchedulerDuckDBWriter,
                self._path,
            )
        except Exception:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
            raise
        self._task = asyncio.create_task(
            self._run(),
            name="whatshot-duckdb-writer",
        )

    async def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if self._task is None or self._writer is None:
            raise RuntimeError("Scheduler writer actor is not running.")
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        await self._queue.put(
            _WriterCommand(
                method=method,
                args=args,
                kwargs=kwargs,
                future=future,
            )
        )
        return await future

    async def stop(self) -> None:
        if self._task is None:
            return
        await self._queue.put(None)
        await self._task
        self._task = None
        self._writer = None
        assert self._executor is not None
        self._executor.shutdown(wait=True, cancel_futures=False)
        self._executor = None

    async def _run(self) -> None:
        assert self._writer is not None
        assert self._executor is not None
        loop = asyncio.get_running_loop()
        while True:
            command = await self._queue.get()
            if command is None:
                self._queue.task_done()
                break
            try:
                method = getattr(self._writer, command.method)
                result = await loop.run_in_executor(
                    self._executor,
                    partial(method, *command.args, **command.kwargs),
                )
            except Exception as exc:  # noqa: BLE001 - return writer errors to caller
                if not command.future.done():
                    command.future.set_exception(exc)
            else:
                if not command.future.done():
                    command.future.set_result(result)
            finally:
                self._queue.task_done()
        await loop.run_in_executor(
            self._executor,
            partial(
                self._writer.close,
                checkpoint=self._checkpoint_on_shutdown,
            ),
        )

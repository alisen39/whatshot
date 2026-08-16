"""FastAPI Control API for the standalone WhatsHot daemon."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from whats_hot_api.daemon.backend_v1 import (
    BOARD_KEY_VERSION,
    CONTRACT_VERSION,
    BackendContractError,
    create_backend_v1_router,
    error_envelope,
)
from whats_hot_api.daemon.runtime import DaemonRuntime
from whats_hot_api.fetch import (
    CachePolicy,
    FetchError,
    FetchRequest,
    FetchService,
    canonical_board_key,
)
from whats_hot_api.history.errors import HistoryDisabledError, HistoryError
from whats_hot_api.scheduler.application import SchedulerError
from whats_hot_api.scheduler.config import AppConfig


class CurrentFetchBody(BaseModel):
    params: dict[str, str] = Field(default_factory=dict)
    limit: int = Field(default=50, ge=1, le=200)


def create_daemon_app(
    config: AppConfig,
    *,
    fetch_service: FetchService,
) -> FastAPI:
    runtime = DaemonRuntime(config=config, fetch_service=fetch_service)
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(
        title="WhatsHot Daemon",
        version="1",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.daemon_runtime = runtime
    app.include_router(
        create_backend_v1_router(
            config,
            fetch_service=runtime.fetch_service,
            history_service=runtime.history,
        )
    )

    @app.middleware("http")
    async def contract_version_headers(request: Any, call_next: Any):
        response = await call_next(request)
        if request.url.path.startswith("/api/v1"):
            response.headers["X-WhatsHot-Contract-Version"] = CONTRACT_VERSION
            response.headers["X-WhatsHot-Board-Key-Version"] = str(BOARD_KEY_VERSION)
        return response

    @app.get("/internal/v1/sources")
    async def list_sources() -> dict[str, Any]:
        return {
            "sources": [
                source.as_dict() for source in runtime.fetch_service.list_sources()
            ]
        }

    @app.get("/internal/v1/sources/{site}")
    async def get_source(site: str) -> dict[str, Any]:
        return {"source": runtime.fetch_service.describe_source(site).as_dict()}

    @app.post("/internal/v1/current/{site}/{path_type}")
    async def fetch_current(
        site: str,
        path_type: str,
        body: CurrentFetchBody,
    ) -> dict[str, Any]:
        result = await runtime.fetch_service.fetch(
            FetchRequest(
                site=site,
                path_type=path_type,
                params=body.params,
                limit=body.limit,
                cache_policy=CachePolicy.PREFER,
            )
        )
        descriptor = runtime.fetch_service.describe_source(site)
        return {
            "site": site,
            "boardKey": canonical_board_key(
                path_type=path_type,
                params=body.params,
                declared_dimensions=(descriptor.params or {}).keys(),
            ),
            "kind": result.data.kind,
            "title": result.data.title,
            "type": result.data.type,
            "updateTime": result.data.updateTime,
            "observedAt": result.observed_at,
            "fromCache": result.from_cache,
            "items": [
                {"rank": rank, **item.model_dump(exclude_none=True)}
                for rank, item in enumerate(result.data.data, start=1)
            ],
        }

    @app.get("/internal/v1/health")
    async def health() -> dict[str, Any]:
        status = runtime.scheduler.status()
        failed = sum(
            1
            for job in status["jobs"]
            if job["lastRun"] and job["lastRun"]["status"] == "failed"
        )
        return {
            "status": "degraded" if failed else "healthy",
            "scheduler": status,
            "history": await runtime.history.call("get_storage_stats"),
        }

    @app.get("/internal/v1/history")
    async def query_history(
        site: str | None = None,
        board: str | None = None,
        kind: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = Query(50, ge=1, le=200),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return await runtime.history.call(
            "query_history",
            site=site,
            board_key=board,
            kind=kind,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )

    @app.get("/internal/v1/history/search")
    async def search_history(
        keyword: str,
        site: str | None = None,
        board: str | None = None,
        kind: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = Query(50, ge=1, le=200),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return await runtime.history.call(
            "search_history",
            keyword,
            site=site,
            board_key=board,
            kind=kind,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )

    @app.get("/internal/v1/history/trends")
    async def trend_history(
        site: str,
        board: str,
        item_id: str,
        bucket: str = "1h",
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        return await runtime.history.call(
            "get_trend_series",
            site=site,
            board_key=board,
            item_id=item_id,
            bucket=bucket,
            since=since,
            until=until,
        )

    @app.get("/internal/v1/history/captures/{capture_id}")
    async def get_capture(capture_id: str) -> dict[str, Any]:
        capture = await runtime.history.call("get_capture", capture_id)
        if capture is None:
            return JSONResponse(
                {
                    "error": {
                        "code": "CAPTURE_NOT_FOUND",
                        "message": f"Unknown capture '{capture_id}'.",
                    }
                },
                status_code=404,
            )
        return capture

    @app.get("/internal/v1/storage/stats")
    async def storage_stats() -> dict[str, Any]:
        return await runtime.history.call("get_storage_stats")

    @app.get("/internal/v1/scheduler/status")
    async def scheduler_status() -> dict[str, Any]:
        return runtime.scheduler.status()

    @app.get("/internal/v1/scheduler/jobs")
    async def scheduler_jobs() -> dict[str, Any]:
        return {"jobs": runtime.scheduler.status()["jobs"]}

    @app.post(
        "/internal/v1/scheduler/jobs/{job_id}/trigger",
        status_code=202,
    )
    async def trigger_scheduler_job(job_id: str) -> dict[str, Any]:
        return runtime.scheduler.submit_trigger(job_id)

    @app.get("/internal/v1/scheduler/runs/{operation_id}")
    async def scheduler_run(operation_id: str) -> dict[str, Any]:
        return runtime.scheduler.get_trigger_operation(operation_id)

    @app.exception_handler(HistoryError)
    async def history_error_handler(
        _request: Any,
        exc: HistoryError,
    ) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                }
            },
            status_code=409 if isinstance(exc, HistoryDisabledError) else 400,
        )

    @app.exception_handler(FetchError)
    async def fetch_error_handler(
        _request: Any,
        exc: FetchError,
    ) -> JSONResponse:
        return JSONResponse(
            {"error": exc.as_dict()},
            status_code=exc.status_code,
        )

    @app.exception_handler(BackendContractError)
    async def backend_contract_error_handler(
        request: Any,
        exc: BackendContractError,
    ) -> JSONResponse:
        return JSONResponse(
            error_envelope(request, exc),
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Any,
        exc: RequestValidationError,
    ) -> JSONResponse:
        if not request.url.path.startswith("/api/v1"):
            return await request_validation_exception_handler(request, exc)
        error = BackendContractError(
            "INVALID_ARGUMENT",
            "Request validation failed.",
            status_code=400,
            details={"errors": jsonable_encoder(exc.errors())},
        )
        return JSONResponse(error_envelope(request, error), status_code=400)

    @app.exception_handler(SchedulerError)
    async def scheduler_error_handler(
        _request: Any,
        exc: SchedulerError,
    ) -> JSONResponse:
        status = 404 if exc.code in {"JOB_NOT_FOUND", "RUN_NOT_FOUND"} else 409
        return JSONResponse(
            {
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                }
            },
            status_code=status,
        )

    return app

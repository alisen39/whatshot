from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from whats_hot_api.daemon.app import create_daemon_app
from whats_hot_api.daemon.owner_lock import (
    DaemonAlreadyRunningError,
    OwnerLock,
)
from whats_hot_api.daemon.query_actor import HistoryQueryActor
from whats_hot_api.fetch import FetchRequest, FetchResult, SourceDescriptor
from whats_hot_api.history.errors import (
    HistoryCursorExpiredError,
    HistoryQueryError,
)
from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.scheduler.config import (
    AppConfig,
    DaemonSettings,
    BackendApiSettings,
    SchedulerJob,
    SchedulerSettings,
    StorageSettings,
)

CONTRACT_SCHEMAS = (
    Path(__file__).parents[2]
    / "whats-hot-mcp"
    / "contracts"
    / "jsonschema"
    / "v1"
)


class _FakeFetchService:
    def list_sources(self) -> tuple[SourceDescriptor, ...]:
        return (self.describe_source("demo"),)

    def describe_source(self, site: str) -> SourceDescriptor:
        return SourceDescriptor(
            name=site,
            title="Demo",
            description="Demo source",
            link="https://example.com",
            category="hotlist",
            category_label="热榜",
            params=None,
            types=("hot",),
            default_type="hot",
            validate_type=True,
            data_path=f"/{site}/{{type}}",
        )

    async def fetch(self, request: FetchRequest) -> FetchResult:
        now = datetime.now(UTC)
        return FetchResult(
            request=request,
            observed_at=now,
            data=RouterData(
                name=request.site,
                title="Demo",
                type="热榜",
                total=1,
                fromCache=False,
                updateTime=now.isoformat(),
                data=[
                    ListItem(
                        id="one",
                        title="守护进程测试",
                        hot=10,
                        url="https://example.com/one",
                    )
                ],
            ),
        )


class _BlockingFetchService(_FakeFetchService):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def fetch(self, request: FetchRequest) -> FetchResult:
        self.started.set()
        await self.release.wait()
        return await super().fetch(request)


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        daemon=DaemonSettings(state_path=tmp_path / "state"),
        storage=StorageSettings(path=tmp_path / "whatshot.duckdb"),
        scheduler=SchedulerSettings(enabled=False, jitter_seconds=0),
        jobs=(
            SchedulerJob(
                id="demo-hot",
                site="demo",
                path_type="hot",
                board_key="hot",
                params={},
                interval_seconds=60,
            ),
        ),
    )


def _disabled_storage_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        daemon=DaemonSettings(state_path=tmp_path / "state"),
        storage=StorageSettings(
            enabled=False,
            path=tmp_path / "data" / "whatshot.duckdb",
        ),
        scheduler=SchedulerSettings(enabled=True, jitter_seconds=0),
    )


async def _wait_for_operation(
    client: AsyncClient,
    operation: dict,
) -> dict:
    operation_id = operation["operationId"]
    for _ in range(100):
        current = (
            await client.get(f"/internal/v1/scheduler/runs/{operation_id}")
        ).json()
        if current["status"] in {"success", "failed"}:
            return current
        await asyncio.sleep(0.01)
    raise AssertionError(f"Scheduler operation did not finish: {operation_id}")


async def test_control_api_triggers_scheduler_and_queries_history(
    tmp_path: Path,
) -> None:
    app = create_daemon_app(
        _config(tmp_path),
        fetch_service=_FakeFetchService(),  # type: ignore[arg-type]
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        current = await client.post(
            "/internal/v1/current/demo/hot",
            json={"limit": 1, "params": {}},
        )
        assert current.status_code == 200
        empty_stats = await client.get("/internal/v1/storage/stats")
        assert empty_stats.json()["captures"] == 0

        trigger = await client.post("/internal/v1/scheduler/jobs/demo-hot/trigger")
        assert trigger.status_code == 202
        completed = await _wait_for_operation(client, trigger.json())
        assert completed["status"] == "success"

        history = await client.get(
            "/internal/v1/history",
            params={"site": "demo", "board": "hot"},
        )
        assert history.status_code == 200
        assert history.json()["items"][0]["title"] == "守护进程测试"

        capabilities = await client.get("/api/v1/capabilities")
        assert capabilities.json()["data"]["profiles"] == [
            "core-read",
            "history-read",
        ]
        assert {
            name: capabilities.json()["data"]["features"][name]
            for name in ("history", "historySearch", "trendSeries", "coverage")
        } == {
            "history": True,
            "historySearch": True,
            "trendSeries": True,
            "coverage": True,
        }
        sources = await client.get("/api/v1/sources")
        assert {
            "history",
            "historySearch",
            "trendSeries",
        } <= set(sources.json()["data"]["sources"][0]["capabilities"])

        contract_responses = {
            "history-response": await client.get(
                "/api/v1/history",
                params={"site": "demo", "boardKey": "hot"},
            ),
            "history-search-response": await client.get(
                "/api/v1/history/search",
                params={"keyword": "守护", "kind": "hotlist"},
            ),
            "trend-response": await client.get(
                "/api/v1/history/trends",
                params={
                    "site": "demo",
                    "boardKey": "hot",
                    "itemId": "one",
                },
            ),
            "coverage-response": await client.get(
                "/api/v1/coverage",
                params={"site": "demo", "kind": "hotlist"},
            ),
        }
        assert all(
            response.status_code == 200
            for response in contract_responses.values()
        )
        assert contract_responses["history-response"].json()["data"]["items"][0][
            "evidenceId"
        ].startswith("duckdb:")
        assert contract_responses["history-search-response"].json()["data"][
            "coverage"
        ]["limitations"] == ["retention-window"]
        assert contract_responses["coverage-response"].json()["data"][
            "configuredSites"
        ] == ["demo"]

        if CONTRACT_SCHEMAS.is_dir():
            jsonschema = pytest.importorskip("jsonschema")
            for name, response in contract_responses.items():
                schema_name = (
                    "history-response"
                    if name == "history-search-response"
                    else name
                )
                schema = json.loads(
                    (CONTRACT_SCHEMAS / f"{schema_name}.schema.json").read_text()
                )
                jsonschema.Draft202012Validator(schema).validate(response.json())

        invalid_cursor = await client.get(
            "/api/v1/history",
            params={"cursor": "W10"},
        )
        assert invalid_cursor.status_code == 400
        assert invalid_cursor.json()["error"]["code"] == "INVALID_CURSOR"

        original_history_call = app.state.daemon_runtime.history.call

        async def expired_history_call(*_args, **_kwargs):
            raise HistoryCursorExpiredError("expired")

        app.state.daemon_runtime.history.call = expired_history_call
        expired_cursor = await client.get("/api/v1/history")
        app.state.daemon_runtime.history.call = original_history_call
        assert expired_cursor.status_code == 409
        assert expired_cursor.json()["error"]["code"] == "CURSOR_EXPIRED"
        if CONTRACT_SCHEMAS.is_dir():
            schema = json.loads(
                (CONTRACT_SCHEMAS / "error-response.schema.json").read_text()
            )
            jsonschema.Draft202012Validator(schema).validate(invalid_cursor.json())
            jsonschema.Draft202012Validator(schema).validate(expired_cursor.json())

        malformed_cursor = await client.get(
            "/internal/v1/history",
            params={"cursor": "W10"},
        )
        assert malformed_cursor.status_code == 400
        assert malformed_cursor.json()["error"]["code"] == "INVALID_HISTORY_CURSOR"

        health = await client.get("/internal/v1/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"


def test_owner_lock_rejects_second_daemon(tmp_path: Path) -> None:
    path = tmp_path / "daemon.lock"
    first = OwnerLock(path)
    second = OwnerLock(path)
    first.acquire()
    try:
        with pytest.raises(DaemonAlreadyRunningError):
            second.acquire()
    finally:
        first.release()


async def test_trigger_returns_before_slow_scheduler_run_finishes(
    tmp_path: Path,
) -> None:
    fetch_service = _BlockingFetchService()
    app = create_daemon_app(
        _config(tmp_path),
        fetch_service=fetch_service,  # type: ignore[arg-type]
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        async with asyncio.timeout(0.1):
            response = await client.post("/internal/v1/scheduler/jobs/demo-hot/trigger")
        assert response.status_code == 202
        await fetch_service.started.wait()
        operation_id = response.json()["operationId"]
        running = await client.get(f"/internal/v1/scheduler/runs/{operation_id}")
        assert running.json()["status"] == "running"
        duplicate = await client.post("/internal/v1/scheduler/jobs/demo-hot/trigger")
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "JOB_ALREADY_RUNNING"
        missing = await client.get("/internal/v1/scheduler/runs/missing")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "RUN_NOT_FOUND"

        fetch_service.release.set()
        completed = await _wait_for_operation(client, response.json())
        assert completed["status"] == "success"


async def test_daemon_lifespan_can_restart_cleanly(tmp_path: Path) -> None:
    app = create_daemon_app(
        _config(tmp_path),
        fetch_service=_FakeFetchService(),  # type: ignore[arg-type]
    )

    for _ in range(2):
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client,
        ):
            health = await client.get("/internal/v1/health")
            assert health.status_code == 200


async def test_disabled_storage_keeps_backend_current_available(
    tmp_path: Path,
) -> None:
    config = _disabled_storage_config(tmp_path)
    app = create_daemon_app(
        config,
        fetch_service=_FakeFetchService(),  # type: ignore[arg-type]
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://127.0.0.1:6690",
        ) as http_client,
    ):
        current = await http_client.post(
            "/internal/v1/current/demo/hot",
            json={"limit": 1, "params": {}},
        )
        assert current.status_code == 200
        assert current.json()["items"][0]["title"] == "守护进程测试"

        stats = await http_client.get("/internal/v1/storage/stats")
        assert stats.status_code == 200
        assert stats.json() == {"enabled": False}

        history = await http_client.get("/internal/v1/history")
        assert history.status_code == 409
        assert history.json()["error"]["code"] == "HISTORY_DISABLED"

        trigger = await http_client.post("/internal/v1/scheduler/jobs/demo-hot/trigger")
        assert trigger.status_code == 409
        assert trigger.json()["error"]["code"] == "STORAGE_DISABLED"

        health = await http_client.get("/internal/v1/health")
        assert health.status_code == 200
        assert health.json()["history"] == {"enabled": False}
        assert health.json()["scheduler"]["storageEnabled"] is False
        assert health.json()["scheduler"]["running"] is False

        assert config.storage.path.exists() is False
        assert config.storage.path.parent.exists() is False


async def test_disabled_storage_does_not_touch_existing_database(
    tmp_path: Path,
) -> None:
    config = _disabled_storage_config(tmp_path)
    config.storage.path.parent.mkdir(parents=True)
    config.storage.path.write_bytes(b"existing-history")
    original = config.storage.path.read_bytes()
    app = create_daemon_app(
        config,
        fetch_service=_FakeFetchService(),  # type: ignore[arg-type]
    )

    async with app.router.lifespan_context(app):
        assert config.storage.path.read_bytes() == original
        assert config.storage.path.with_suffix(".duckdb.wal").exists() is False

    assert config.storage.path.read_bytes() == original


async def test_history_query_actor_interrupts_timeout(tmp_path: Path) -> None:
    class SlowReader:
        interrupted = False

        def slow(self) -> None:
            time.sleep(0.05)

        def interrupt(self) -> None:
            self.interrupted = True

        def close(self) -> None:
            pass

    actor = HistoryQueryActor(
        tmp_path / "unused.duckdb",
        timeout_seconds=0.01,
    )
    reader = SlowReader()
    actor._reader = reader  # type: ignore[assignment]
    actor._executor = ThreadPoolExecutor(max_workers=1)
    with pytest.raises(HistoryQueryError, match="exceeded"):
        await actor.call("slow")
    assert reader.interrupted is True
    await actor.stop()


def test_daemon_without_storage_does_not_require_history_dependencies(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from whats_hot_api.daemon import main

    config = AppConfig(
        daemon=DaemonSettings(state_path=tmp_path / "state"),
        storage=StorageSettings(
            enabled=False,
            path=tmp_path / "data" / "whatshot.duckdb",
        ),
        scheduler=SchedulerSettings(enabled=False),
        backend_api=BackendApiSettings(),
    )
    launched: list[object] = []
    monkeypatch.setattr(main, "discover_and_register_routes", lambda: None)
    monkeypatch.setattr(main, "load_config", lambda *args, **kwargs: config)
    monkeypatch.setattr(main, "find_spec", lambda name: None)
    monkeypatch.setattr(main.uvicorn, "run", lambda app, **kwargs: launched.append(app))

    main.run_daemon()

    assert len(launched) == 1
    assert config.storage.path.parent.exists() is False

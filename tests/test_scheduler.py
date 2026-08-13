from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from whats_hot_api.fetch import FetchRequest, FetchResult, FetchService
from whats_hot_api.history import HistoryReader
from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.registry import discover_and_register_routes, fetch_service
from whats_hot_api.scheduler.application import (
    SchedulerApplication,
    StorageDisabledError,
)
from whats_hot_api.scheduler.config import (
    AppConfig,
    SchedulerJob,
    SchedulerSettings,
    StorageSettings,
    canonical_board_key,
    default_config_path,
    load_config,
    parse_duration,
)


class _FakeFetchService:
    def __init__(self, *, from_cache: bool = False) -> None:
        self.requests: list[FetchRequest] = []
        self.from_cache = from_cache

    async def fetch(self, request: FetchRequest) -> FetchResult:
        self.requests.append(request)
        now = datetime.now(UTC)
        return FetchResult(
            request=request,
            observed_at=now,
            data=RouterData(
                name=request.site,
                title="Demo",
                type="热榜",
                total=1,
                fromCache=self.from_cache,
                updateTime=now.isoformat(),
                data=[
                    ListItem(
                        id="one",
                        title="测试",
                        hot=1,
                        url="https://example.com/one",
                    )
                ],
            ),
        )


def _config(database: Path) -> AppConfig:
    return AppConfig(
        storage=StorageSettings(path=database),
        scheduler=SchedulerSettings(
            enabled=False,
            jitter_seconds=0,
            request_timeout_seconds=5,
        ),
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


def test_parse_duration_and_board_key() -> None:
    assert parse_duration("10m") == 600
    assert (
        canonical_board_key(
            path_type="1",
            params={"range": "WEEK"},
            declared_dimensions={"type", "range"},
        )
        == "type=1&range=WEEK"
    )
    assert (
        canonical_board_key(
            path_type="hot",
            params={},
            declared_dimensions=set(),
        )
        == "hot"
    )


def test_load_config_defaults_to_zero_jobs(tmp_path: Path) -> None:
    service = FetchService()
    config = load_config(tmp_path / "missing.toml", fetch_service=service)

    assert config.jobs == ()
    assert config.scheduler.enabled is True
    assert config.storage.enabled is True
    assert config.storage.cursor_ttl_seconds == 86400


def test_project_config_is_preferred_and_paths_are_config_relative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[daemon]
state_path = "data/state"

[storage]
path = "data/whatshot.duckdb"
cursor_ttl_seconds = 3600
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert default_config_path() == config_path

    config = load_config(None, fetch_service=FetchService())

    assert config.daemon.state_path == tmp_path / "data" / "state"
    assert config.storage.path == tmp_path / "data" / "whatshot.duckdb"
    assert config.storage.cursor_ttl_seconds == 3600


def test_load_config_fills_secondary_dimension_defaults(tmp_path: Path) -> None:
    discover_and_register_routes()
    config_path = tmp_path / "whatshot.toml"
    config_path.write_text(
        """
[scheduler]
[[scheduler.jobs]]
id = "acfun-animation"
site = "acfun"
type = "1"
interval = "10m"
""",
        encoding="utf-8",
    )

    config = load_config(config_path, fetch_service=fetch_service)

    assert config.jobs[0].params == {"range": "DAY"}
    assert config.jobs[0].board_key == "type=1&range=DAY"


async def test_scheduler_is_the_only_capture_write_path(tmp_path: Path) -> None:
    database = tmp_path / "whatshot.duckdb"
    fetch = _FakeFetchService()
    scheduler = SchedulerApplication(
        config=_config(database),
        fetch_service=fetch,  # type: ignore[arg-type]
        retry_delays=(),
    )
    await scheduler.start()
    result = await scheduler.run_once("demo-hot")

    assert result.status == "success"
    assert result.capture_id
    assert fetch.requests[0].cache_policy.value == "refresh"

    reader = HistoryReader(database)
    stats = reader.get_storage_stats()
    assert stats["captures"] == 1
    assert stats["hotlistRows"] == 1
    reader.close()
    await scheduler.stop()


async def test_scheduler_rejects_cached_capture(tmp_path: Path) -> None:
    database = tmp_path / "whatshot.duckdb"
    scheduler = SchedulerApplication(
        config=_config(database),
        fetch_service=_FakeFetchService(from_cache=True),  # type: ignore[arg-type]
        retry_delays=(),
    )
    await scheduler.start()
    result = await scheduler.run_once("demo-hot")

    assert result.status == "failed"
    assert result.error_code == "CACHED_CAPTURE_REJECTED"
    reader = HistoryReader(database)
    assert reader.get_storage_stats()["captures"] == 0
    reader.close()
    await scheduler.stop()


async def test_scheduler_can_restart_after_clean_stop(tmp_path: Path) -> None:
    database = tmp_path / "whatshot.duckdb"
    fetch = _FakeFetchService()
    scheduler = SchedulerApplication(
        config=_config(database),
        fetch_service=fetch,  # type: ignore[arg-type]
        retry_delays=(),
    )

    await scheduler.start()
    first = await scheduler.run_once("demo-hot")
    await scheduler.stop()
    await scheduler.start()
    second = await scheduler.run_once("demo-hot")
    await scheduler.stop()

    assert first.status == "success"
    assert second.status == "success"
    reader = HistoryReader(database)
    assert reader.get_storage_stats()["captures"] == 2
    reader.close()


def test_invalid_short_interval_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 10 seconds"):
        parse_duration("5s")


def test_config_rejects_quoted_boolean_values(tmp_path: Path) -> None:
    discover_and_register_routes()
    config_path = tmp_path / "quoted-booleans.toml"
    config_path.write_text(
        """
[storage]
enabled = "true"
checkpoint_on_shutdown = "false"

[scheduler]
enabled = "false"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be a boolean"):
        load_config(config_path, fetch_service=fetch_service)


def test_config_rejects_enabled_job_when_storage_is_disabled(
    tmp_path: Path,
) -> None:
    discover_and_register_routes()
    config_path = tmp_path / "storage-disabled.toml"
    config_path.write_text(
        """
[storage]
enabled = false

[scheduler]
[[scheduler.jobs]]
id = "weibo-hot"
site = "weibo"
type = "hot"
interval = "10m"
enabled = true
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires every scheduler job"):
        load_config(config_path, fetch_service=fetch_service)


def test_config_allows_disabled_job_when_storage_is_disabled(
    tmp_path: Path,
) -> None:
    discover_and_register_routes()
    config_path = tmp_path / "storage-disabled.toml"
    config_path.write_text(
        """
[storage]
enabled = false

[scheduler]
[[scheduler.jobs]]
id = "weibo-hot"
site = "weibo"
type = "hot"
interval = "10m"
enabled = false
""",
        encoding="utf-8",
    )

    config = load_config(config_path, fetch_service=fetch_service)

    assert config.storage.enabled is False
    assert config.jobs[0].enabled is False


def test_programmatic_config_rejects_enabled_job_when_storage_is_disabled(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="requires every scheduler job"):
        AppConfig(
            storage=StorageSettings(
                enabled=False,
                path=tmp_path / "whatshot.duckdb",
            ),
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


def test_config_rejects_boolean_where_integer_is_required(tmp_path: Path) -> None:
    discover_and_register_routes()
    config_path = tmp_path / "boolean-port.toml"
    config_path.write_text(
        """
[daemon]
port = true
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be an integer"):
        load_config(config_path, fetch_service=fetch_service)


def test_duration_rejects_boolean() -> None:
    with pytest.raises(ValueError, match="Invalid interval"):
        parse_duration(True)


async def test_zero_job_scheduler_never_fetches_upstream(tmp_path: Path) -> None:
    database = tmp_path / "whatshot.duckdb"
    fetch = _FakeFetchService()
    scheduler = SchedulerApplication(
        config=AppConfig(
            storage=StorageSettings(path=database),
            scheduler=SchedulerSettings(
                enabled=True,
                jitter_seconds=0,
            ),
            jobs=(),
        ),
        fetch_service=fetch,  # type: ignore[arg-type]
        retry_delays=(),
    )

    await scheduler.start()
    await scheduler.stop()

    assert fetch.requests == []


async def test_storage_disabled_scheduler_never_opens_database_or_fetches(
    tmp_path: Path,
) -> None:
    database = tmp_path / "disabled" / "whatshot.duckdb"
    fetch = _FakeFetchService()
    scheduler = SchedulerApplication(
        config=AppConfig(
            storage=StorageSettings(enabled=False, path=database),
            scheduler=SchedulerSettings(enabled=True, jitter_seconds=0),
        ),
        fetch_service=fetch,  # type: ignore[arg-type]
        retry_delays=(),
    )

    await scheduler.start()
    status = scheduler.status()
    with pytest.raises(StorageDisabledError):
        await scheduler.run_once("demo-hot")
    await scheduler.stop()

    assert status["running"] is False
    assert status["storageEnabled"] is False
    assert status["writerQueueDepth"] is None
    assert fetch.requests == []
    assert database.exists() is False
    assert database.parent.exists() is False

"""TOML configuration for the Scheduler-owned daemon."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whats_hot_api.fetch import FetchService, canonical_board_key


class SchedulerConfigError(ValueError):
    pass


def default_config_path() -> Path:
    project_config = Path.cwd() / "config.toml"
    if project_config.is_file():
        return project_config
    root = Path(
        os.getenv(
            "XDG_CONFIG_HOME",
            Path.home() / ".config",
        )
    )
    return root / "whatshot" / "config.toml"


def default_data_path() -> Path:
    root = Path(
        os.getenv(
            "XDG_DATA_HOME",
            Path.home() / ".local" / "share",
        )
    )
    return root / "whatshot" / "whatshot.duckdb"


def default_state_path() -> Path:
    root = Path(
        os.getenv(
            "XDG_STATE_HOME",
            Path.home() / ".local" / "state",
        )
    )
    return root / "whatshot"


@dataclass(frozen=True, slots=True)
class DaemonSettings:
    bind: str = "127.0.0.1"
    port: int = 6690
    state_path: Path = field(default_factory=default_state_path)


@dataclass(frozen=True, slots=True)
class StorageSettings:
    enabled: bool = True
    path: Path = field(default_factory=default_data_path)
    retention_days: int = 180
    query_timeout_seconds: int = 5
    checkpoint_on_shutdown: bool = True


@dataclass(frozen=True, slots=True)
class SchedulerSettings:
    enabled: bool = True
    max_fetch_concurrency: int = 4
    writer_queue_size: int = 32
    jitter_seconds: int = 15
    request_timeout_seconds: int = 30
    shutdown_grace_seconds: int = 30


@dataclass(frozen=True, slots=True)
class McpSettings:
    enabled: bool = True
    streamable_http_path: str = "/mcp"
    max_result_items: int = 200
    default_history_days: int = 7
    max_history_days: int = 365


@dataclass(frozen=True, slots=True)
class SchedulerJob:
    id: str
    site: str
    path_type: str
    board_key: str
    params: dict[str, str]
    interval_seconds: int
    limit: int = 50
    enabled: bool = True
    run_on_start: bool = True


@dataclass(frozen=True, slots=True)
class AppConfig:
    daemon: DaemonSettings = field(default_factory=DaemonSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)
    scheduler: SchedulerSettings = field(default_factory=SchedulerSettings)
    mcp: McpSettings = field(default_factory=McpSettings)
    jobs: tuple[SchedulerJob, ...] = ()

    def __post_init__(self) -> None:
        if not self.storage.enabled and any(job.enabled for job in self.jobs):
            raise SchedulerConfigError(
                "storage.enabled=false requires every scheduler job to be disabled."
            )


def parse_duration(value: str | int) -> int:
    if isinstance(value, bool):
        raise SchedulerConfigError(f"Invalid interval: {value!r}")
    if isinstance(value, int):
        seconds = value
    else:
        text = str(value).strip().lower()
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        if text.isdigit():
            seconds = int(text)
        elif len(text) >= 2 and text[-1] in units and text[:-1].isdigit():
            seconds = int(text[:-1]) * units[text[-1]]
        else:
            raise SchedulerConfigError(f"Invalid interval: {value!r}")
    if seconds < 10:
        raise SchedulerConfigError("Scheduler interval must be at least 10 seconds.")
    return seconds


def load_config(
    path: str | Path | None,
    *,
    fetch_service: FetchService,
) -> AppConfig:
    config_path = (
        Path(path).expanduser() if path else default_config_path()
    ).resolve()
    config_dir = config_path.parent
    if config_path.exists():
        with config_path.open("rb") as file:
            raw = tomllib.load(file)
    else:
        raw = {}
    if not isinstance(raw, dict):
        raise SchedulerConfigError("Configuration root must be a TOML table.")

    daemon_raw = _table(raw, "daemon")
    storage_raw = _table(raw, "storage")
    scheduler_raw = _table(raw, "scheduler")
    mcp_raw = _table(raw, "mcp")

    daemon = DaemonSettings(
        bind=str(daemon_raw.get("bind", "127.0.0.1")),
        port=_bounded_int(daemon_raw.get("port", 6690), "daemon.port", 1, 65535),
        state_path=_configured_path(
            daemon_raw.get("state_path"),
            default=default_state_path(),
            config_dir=config_dir,
        ),
    )
    storage = StorageSettings(
        enabled=_require_bool(
            storage_raw.get("enabled", True),
            "storage.enabled",
        ),
        path=_configured_path(
            storage_raw.get("path"),
            default=default_data_path(),
            config_dir=config_dir,
        ),
        retention_days=_bounded_int(
            storage_raw.get("retention_days", 180),
            "storage.retention_days",
            1,
            3650,
        ),
        query_timeout_seconds=_bounded_int(
            storage_raw.get("query_timeout_seconds", 5),
            "storage.query_timeout_seconds",
            1,
            300,
        ),
        checkpoint_on_shutdown=_require_bool(
            storage_raw.get("checkpoint_on_shutdown", True),
            "storage.checkpoint_on_shutdown",
        ),
    )
    scheduler = SchedulerSettings(
        enabled=_require_bool(
            scheduler_raw.get("enabled", True),
            "scheduler.enabled",
        ),
        max_fetch_concurrency=_bounded_int(
            scheduler_raw.get("max_fetch_concurrency", 4),
            "scheduler.max_fetch_concurrency",
            1,
            32,
        ),
        writer_queue_size=_bounded_int(
            scheduler_raw.get("writer_queue_size", 32),
            "scheduler.writer_queue_size",
            1,
            1024,
        ),
        jitter_seconds=_bounded_int(
            scheduler_raw.get("jitter_seconds", 15),
            "scheduler.jitter_seconds",
            0,
            3600,
        ),
        request_timeout_seconds=_bounded_int(
            scheduler_raw.get("request_timeout_seconds", 30),
            "scheduler.request_timeout_seconds",
            1,
            3600,
        ),
        shutdown_grace_seconds=_bounded_int(
            scheduler_raw.get("shutdown_grace_seconds", 30),
            "scheduler.shutdown_grace_seconds",
            1,
            3600,
        ),
    )
    mcp = McpSettings(
        enabled=_require_bool(
            mcp_raw.get("enabled", True),
            "mcp.enabled",
        ),
        streamable_http_path=str(mcp_raw.get("streamable_http_path", "/mcp")),
        max_result_items=_bounded_int(
            mcp_raw.get("max_result_items", 200),
            "mcp.max_result_items",
            1,
            200,
        ),
        default_history_days=_bounded_int(
            mcp_raw.get("default_history_days", 7),
            "mcp.default_history_days",
            1,
            365,
        ),
        max_history_days=_bounded_int(
            mcp_raw.get("max_history_days", 365),
            "mcp.max_history_days",
            1,
            365,
        ),
    )
    if not mcp.streamable_http_path.startswith("/"):
        raise SchedulerConfigError("mcp.streamable_http_path must start with '/'.")
    if mcp.default_history_days > mcp.max_history_days:
        raise SchedulerConfigError(
            "mcp.default_history_days must not exceed max_history_days."
        )

    jobs_raw = scheduler_raw.get("jobs", [])
    if not isinstance(jobs_raw, list):
        raise SchedulerConfigError("scheduler.jobs must be an array of tables.")
    jobs = tuple(_parse_job(row, fetch_service) for row in jobs_raw)
    job_ids = [job.id for job in jobs]
    if len(job_ids) != len(set(job_ids)):
        raise SchedulerConfigError("scheduler job ids must be unique.")
    return AppConfig(
        daemon=daemon,
        storage=storage,
        scheduler=scheduler,
        mcp=mcp,
        jobs=jobs,
    )


def _parse_job(raw: Any, fetch_service: FetchService) -> SchedulerJob:
    if not isinstance(raw, Mapping):
        raise SchedulerConfigError("Each scheduler job must be a TOML table.")
    job_id = str(raw.get("id", "")).strip()
    site = str(raw.get("site", "")).strip()
    path_type = str(raw.get("type", "")).strip()
    if not job_id or not site or not path_type:
        raise SchedulerConfigError("Each job requires id, site, and type.")
    try:
        descriptor = fetch_service.describe_source(site)
    except Exception as exc:
        raise SchedulerConfigError(
            f"Job '{job_id}' references unknown site '{site}'."
        ) from exc
    if descriptor.validate_type and path_type not in descriptor.types:
        raise SchedulerConfigError(
            f"Job '{job_id}' has unknown type '{path_type}' for '{site}'."
        )
    params_raw = raw.get("params", {})
    if not isinstance(params_raw, Mapping):
        raise SchedulerConfigError(f"Job '{job_id}' params must be a table.")
    params = {str(key): str(value) for key, value in params_raw.items()}
    declared = descriptor.params or {}
    unknown_params = set(params) - (set(declared) - {"type"})
    if unknown_params:
        raise SchedulerConfigError(
            f"Job '{job_id}' has unknown params: {sorted(unknown_params)}"
        )
    for key, param_meta in declared.items():
        if key == "type" or key in params or not isinstance(param_meta, Mapping):
            continue
        choices = param_meta.get("type")
        if isinstance(choices, Mapping) and choices:
            params[key] = str(next(iter(choices)))
        elif isinstance(choices, (list, tuple)) and choices:
            params[key] = str(choices[0])
    for key, value in params.items():
        param_meta = declared.get(key)
        if isinstance(param_meta, Mapping):
            choices = param_meta.get("type")
            if isinstance(choices, Mapping) and value not in {
                str(item) for item in choices
            }:
                raise SchedulerConfigError(
                    f"Job '{job_id}' has invalid {key}={value!r}."
                )
            if isinstance(choices, (list, tuple)) and value not in {
                str(item) for item in choices
            }:
                raise SchedulerConfigError(
                    f"Job '{job_id}' has invalid {key}={value!r}."
                )
    has_type_dimension = "type" in declared
    return SchedulerJob(
        id=job_id,
        site=site,
        path_type=path_type,
        board_key=canonical_board_key(
            path_type=path_type,
            params=params,
            has_type_dimension=has_type_dimension,
        ),
        params=params,
        interval_seconds=parse_duration(raw.get("interval", "10m")),
        limit=_bounded_int(raw.get("limit", 50), f"job {job_id}.limit", 1, 200),
        enabled=_require_bool(raw.get("enabled", True), f"job {job_id}.enabled"),
        run_on_start=_require_bool(
            raw.get("run_on_start", True),
            f"job {job_id}.run_on_start",
        ),
    )


def _table(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key, {})
    if not isinstance(value, Mapping):
        raise SchedulerConfigError(f"{key} must be a TOML table.")
    return value


def _configured_path(
    value: Any,
    *,
    default: Path,
    config_dir: Path,
) -> Path:
    if value is None:
        return default.expanduser().resolve()
    configured = Path(value).expanduser()
    if not configured.is_absolute():
        configured = config_dir / configured
    return configured.resolve()


def _bounded_int(
    value: Any,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchedulerConfigError(f"{name} must be an integer.")
    parsed = value
    if not minimum <= parsed <= maximum:
        raise SchedulerConfigError(f"{name} must be between {minimum} and {maximum}.")
    return parsed


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise SchedulerConfigError(f"{name} must be a boolean.")
    return value

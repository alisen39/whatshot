"""Daemon command runner."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

import uvicorn

from whats_hot_api.daemon.app import create_daemon_app
from whats_hot_api.registry import discover_and_register_routes, fetch_service
from whats_hot_api.scheduler.config import SchedulerConfigError, load_config


def run_daemon(config_path: str | Path | None = None) -> None:
    discover_and_register_routes()
    config = load_config(config_path, fetch_service=fetch_service)
    if config.storage.enabled and (
        find_spec("duckdb") is None or find_spec("pytz") is None
    ):
        raise SchedulerConfigError(
            "History support is not installed; install whats-hot-api[history]."
        )
    if config.mcp.enabled and find_spec("mcp") is None:
        raise SchedulerConfigError(
            "MCP support is not installed; install whats-hot-api[daemon]."
        )
    uvicorn.run(
        create_daemon_app(config, fetch_service=fetch_service),
        host=config.daemon.bind,
        port=config.daemon.port,
        reload=False,
        workers=1,
    )

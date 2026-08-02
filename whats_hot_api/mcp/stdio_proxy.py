"""stdio MCP proxy that delegates every operation to the daemon."""

from __future__ import annotations

from pathlib import Path

from whats_hot_api.daemon.client import DaemonClient
from whats_hot_api.mcp.backend import DaemonMcpBackend
from whats_hot_api.registry import discover_and_register_routes, fetch_service
from whats_hot_api.scheduler.config import load_config


def main(config_path: str | Path | None = None) -> None:
    try:
        from whats_hot_api.mcp.server import build_mcp_server
    except ModuleNotFoundError as exc:
        if exc.name not in {"mcp", "mcp_types"}:
            raise
        raise SystemExit(
            "MCP support is not installed; install whats-hot-api[mcp]."
        ) from None

    discover_and_register_routes()
    config = load_config(config_path, fetch_service=fetch_service)
    host = (
        "127.0.0.1" if config.daemon.bind in {"0.0.0.0", "::"} else config.daemon.bind
    )
    backend = DaemonMcpBackend(DaemonClient(f"http://{host}:{config.daemon.port}"))
    build_mcp_server(
        backend,
        max_result_items=config.mcp.max_result_items,
        default_history_days=config.mcp.default_history_days,
        max_history_days=config.mcp.max_history_days,
    ).run(transport="stdio")


if __name__ == "__main__":
    main()

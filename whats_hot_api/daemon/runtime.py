"""Daemon lifecycle and service ownership."""

from __future__ import annotations

from whats_hot_api.daemon.owner_lock import OwnerLock
from whats_hot_api.daemon.query_actor import (
    DisabledHistoryService,
    HistoryQueryActor,
)
from whats_hot_api.fetch import FetchService
from whats_hot_api.scheduler.application import SchedulerApplication
from whats_hot_api.scheduler.config import AppConfig


class DaemonRuntime:
    def __init__(
        self,
        *,
        config: AppConfig,
        fetch_service: FetchService,
    ) -> None:
        self.config = config
        self.fetch_service = fetch_service
        self.scheduler = SchedulerApplication(
            config=config,
            fetch_service=fetch_service,
        )
        self.history = (
            HistoryQueryActor(
                config.storage.path,
                timeout_seconds=config.storage.query_timeout_seconds,
                default_history_days=config.mcp.default_history_days,
                max_history_days=config.mcp.max_history_days,
                cursor_ttl_seconds=config.storage.cursor_ttl_seconds,
                cursor_secret_path=(
                    config.daemon.state_path / "history_cursor.key"
                ),
            )
            if config.storage.enabled
            else DisabledHistoryService()
        )
        self._lock = OwnerLock(config.daemon.state_path / "daemon.lock")

    async def start(self) -> None:
        self._lock.acquire()
        try:
            await self.scheduler.start()
            await self.history.start()
        except Exception:
            await self.scheduler.stop()
            self._lock.release()
            raise

    async def stop(self) -> None:
        await self.history.stop()
        await self.scheduler.stop()
        self._lock.release()

"""Dedicated read thread for HistoryReader and its DuckDB connection."""

from __future__ import annotations

import asyncio
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import Any

from whats_hot_api.history import HistoryReader
from whats_hot_api.history.errors import HistoryDisabledError, HistoryQueryError


class DisabledHistoryService:
    """History facade used when persistence is explicitly disabled."""

    async def start(self) -> None:
        return None

    async def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if method == "get_storage_stats":
            return {"enabled": False}
        raise HistoryDisabledError("History storage is disabled.")

    async def stop(self) -> None:
        return None


class HistoryQueryActor:
    def __init__(
        self,
        path: str | Path,
        *,
        timeout_seconds: float = 5,
        default_history_days: int = 7,
        max_history_days: int = 365,
        cursor_ttl_seconds: int = 86400,
        cursor_secret_path: str | Path | None = None,
    ) -> None:
        self._path = path
        self._timeout_seconds = timeout_seconds
        self._default_history_days = default_history_days
        self._max_history_days = max_history_days
        self._cursor_ttl_seconds = cursor_ttl_seconds
        self._cursor_secret_path = (
            Path(cursor_secret_path) if cursor_secret_path is not None else None
        )
        self._executor: ThreadPoolExecutor | None = None
        self._reader: HistoryReader | None = None

    async def start(self) -> None:
        if self._reader is not None:
            return
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="whatshot-duckdb-query",
        )
        loop = asyncio.get_running_loop()
        try:
            cursor_secret = (
                _load_cursor_secret(self._cursor_secret_path)
                if self._cursor_secret_path is not None
                else None
            )
            self._reader = await loop.run_in_executor(
                self._executor,
                partial(
                    HistoryReader,
                    self._path,
                    default_history_days=self._default_history_days,
                    max_history_days=self._max_history_days,
                    cursor_secret=cursor_secret,
                    cursor_ttl=timedelta(seconds=self._cursor_ttl_seconds),
                ),
            )
        except Exception:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
            raise

    async def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if self._reader is None:
            raise RuntimeError("History query actor is not running.")
        assert self._executor is not None
        callback = getattr(self._reader, method)
        future = asyncio.get_running_loop().run_in_executor(
            self._executor,
            partial(callback, *args, **kwargs),
        )
        try:
            async with asyncio.timeout(self._timeout_seconds):
                return await asyncio.shield(future)
        except TimeoutError as exc:
            self._reader.interrupt()
            # Drain the worker result so the single-thread actor is reusable after
            # DuckDB handles the interrupt. Query errors are replaced by the stable
            # timeout error below.
            await asyncio.gather(future, return_exceptions=True)
            raise HistoryQueryError(
                f"History query exceeded {self._timeout_seconds:g} seconds."
            ) from exc

    async def stop(self) -> None:
        if self._reader is None:
            return
        reader = self._reader
        self._reader = None
        assert self._executor is not None
        await asyncio.get_running_loop().run_in_executor(
            self._executor,
            reader.close,
        )
        self._executor.shutdown(wait=True, cancel_futures=False)
        self._executor = None


def _load_cursor_secret(path: Path) -> bytes:
    """Load or atomically create the daemon-local cursor signing key."""

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as file:
            file.write(secrets.token_bytes(32))
    except FileExistsError:
        pass
    os.chmod(path, 0o600)
    secret = path.read_bytes()
    if len(secret) != 32:
        raise ValueError("History cursor signing key must contain exactly 32 bytes.")
    return secret

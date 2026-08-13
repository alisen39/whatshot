"""Scheduler-exclusive DuckDB writer.

No CLI, HTTP, history, or MCP module may import this module.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import orjson

from whats_hot_api.history.models import CaptureBatch, RunStart
from whats_hot_api.history.migrations import MigrationRunner
from whats_hot_api.history.text import evidence_search_text
from whats_hot_api.models import GoldItem, ListItem, NewsFlashItem


def _duckdb():
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "DuckDB support is not installed; install whats-hot-api[history]."
        ) from exc
    return duckdb


def _json(value: Any) -> str:
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS).decode()


def _published_at(timestamp: int | None) -> datetime | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp / 1000, UTC)


def _response_time(value: str, fallback: datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class SchedulerDuckDBWriter:
    """Synchronous writer invoked only by the Scheduler writer actor."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        database_existed = self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = _duckdb().connect(str(self.path))
        try:
            self._configure()
            MigrationRunner(
                self._connection,
                self.path,
                database_existed=database_existed,
            ).run()
        except Exception:
            self._connection.close()
            raise

    def close(self, *, checkpoint: bool = True) -> None:
        if checkpoint:
            self._connection.execute("CHECKPOINT")
        self._connection.close()

    def record_run_started(self, run: RunStart) -> None:
        existing = self._connection.execute(
            "SELECT status FROM scheduler_runs WHERE run_key = ?",
            [run.run_key],
        ).fetchone()
        if existing:
            if existing[0] != "success":
                self._connection.execute(
                    """
                    UPDATE scheduler_runs
                    SET status = 'running',
                        attempt = ?,
                        error_code = NULL,
                        error_message = NULL
                    WHERE run_key = ?
                    """,
                    [run.attempt, run.run_key],
                )
            return
        self._connection.execute(
            """
            INSERT INTO scheduler_runs (
                run_id, run_key, job_id, trigger_kind, scheduled_for,
                started_at, status, attempt
            ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?)
            """,
            [
                run.run_id,
                run.run_key,
                run.job_id,
                run.trigger_kind,
                run.scheduled_for,
                run.started_at,
                run.attempt,
            ],
        )

    def record_run_failure(
        self,
        run: RunStart,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        self.record_run_started(run)
        self._connection.execute(
            """
            UPDATE scheduler_runs
            SET status = 'failed',
                finished_at = ?,
                error_code = ?,
                error_message = ?
            WHERE run_key = ?
            """,
            [
                datetime.now(UTC),
                error_code,
                error_message[:1000],
                run.run_key,
            ],
        )

    def persist_capture(self, batch: CaptureBatch) -> str:
        existing = self._connection.execute(
            "SELECT capture_id FROM captures WHERE run_key = ?",
            [batch.run.run_key],
        ).fetchone()
        if existing:
            self._connection.execute(
                """
                UPDATE scheduler_runs
                SET status = 'success',
                    finished_at = COALESCE(finished_at, ?),
                    capture_id = ?,
                    error_code = NULL,
                    error_message = NULL
                WHERE run_key = ?
                """,
                [
                    datetime.now(UTC),
                    str(existing[0]),
                    batch.run.run_key,
                ],
            )
            return str(existing[0])

        result = batch.fetch_result
        route_data = result.data
        request = result.request
        observed_at = result.observed_at
        content_hash = hashlib.sha256(
            route_data.model_dump_json(exclude_none=True).encode()
        ).hexdigest()
        self._connection.execute("BEGIN TRANSACTION")
        try:
            self.record_run_started(batch.run)
            self._connection.execute(
                """
                INSERT INTO captures (
                    capture_id, run_key, job_id, site, board_key, path_type,
                    params_json, kind, title, type_label, scheduled_for,
                    observed_at, response_update_at, item_count, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    batch.capture_id,
                    batch.run.run_key,
                    batch.run.job_id,
                    request.site,
                    batch.board_key,
                    request.path_type,
                    _json(request.params),
                    route_data.kind,
                    route_data.title,
                    route_data.type,
                    batch.run.scheduled_for,
                    observed_at,
                    _response_time(route_data.updateTime, observed_at),
                    len(route_data.data),
                    content_hash,
                ],
            )
            if route_data.kind == "hotlist":
                self._insert_hotlist(batch)
            elif route_data.kind == "newsflash":
                self._upsert_newsflash(batch)
            elif route_data.kind == "gold":
                self._insert_gold(batch)
            else:
                raise ValueError(f"Unsupported content kind: {route_data.kind}")
            self._connection.execute(
                """
                UPDATE scheduler_runs
                SET status = 'success',
                    finished_at = ?,
                    capture_id = ?,
                    error_code = NULL,
                    error_message = NULL
                WHERE run_key = ?
                """,
                [
                    datetime.now(UTC),
                    batch.capture_id,
                    batch.run.run_key,
                ],
            )
            self._connection.execute("COMMIT")
            return batch.capture_id
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def apply_retention(self, retention_days: int) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        self._connection.execute("BEGIN TRANSACTION")
        try:
            for table in (
                "hotlist_observations",
                "newsflash_occurrences",
                "gold_observations",
            ):
                self._connection.execute(
                    f"DELETE FROM {table} WHERE observed_at < ?",
                    [cutoff],
                )
            self._connection.execute(
                "DELETE FROM captures WHERE observed_at < ?",
                [cutoff],
            )
            self._connection.execute(
                "DELETE FROM scheduler_runs WHERE started_at < ?",
                [cutoff],
            )
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def _insert_hotlist(self, batch: CaptureBatch) -> None:
        route_data = batch.fetch_result.data
        request = batch.fetch_result.request
        for position, raw_item in enumerate(route_data.data, start=1):
            if not isinstance(raw_item, ListItem):
                raise TypeError("hotlist capture contains a non-ListItem")
            self._connection.execute(
                """
                INSERT INTO hotlist_observations (
                    capture_id, site, board_key, observed_at, position,
                    source_item_id, title, url, mobile_url, hot, author,
                    description, cover_url, published_at, search_text_normalized
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    batch.capture_id,
                    request.site,
                    batch.board_key,
                    batch.fetch_result.observed_at,
                    position,
                    raw_item.id,
                    raw_item.title,
                    raw_item.url,
                    raw_item.mobileUrl,
                    raw_item.hot,
                    raw_item.author,
                    raw_item.desc,
                    raw_item.cover,
                    _published_at(raw_item.timestamp),
                    evidence_search_text(raw_item.title, raw_item.desc),
                ],
            )

    def _upsert_newsflash(self, batch: CaptureBatch) -> None:
        route_data = batch.fetch_result.data
        request = batch.fetch_result.request
        observed_at = batch.fetch_result.observed_at
        for position, raw_item in enumerate(route_data.data, start=1):
            if not isinstance(raw_item, NewsFlashItem):
                raise TypeError("newsflash capture contains a non-NewsFlashItem")
            self._connection.execute(
                """
                INSERT INTO newsflash_occurrences (
                    capture_id, site, board_key, observed_at, position,
                    source_item_id, title, content, summary, content_status,
                    url, mobile_url, source, is_important, tags_json,
                    images_json, symbols_json, metrics_json, published_at,
                    search_text_normalized
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    batch.capture_id,
                    request.site,
                    batch.board_key,
                    observed_at,
                    position,
                    raw_item.id,
                    raw_item.title,
                    raw_item.content,
                    raw_item.summary,
                    raw_item.contentStatus,
                    raw_item.url,
                    raw_item.mobileUrl,
                    raw_item.source,
                    raw_item.isImportant,
                    _json(raw_item.tags),
                    _json(raw_item.images),
                    _json(raw_item.symbols),
                    _json(raw_item.metrics),
                    _published_at(raw_item.timestamp),
                    evidence_search_text(
                        raw_item.title,
                        raw_item.summary or raw_item.content,
                    ),
                ],
            )

    def _insert_gold(self, batch: CaptureBatch) -> None:
        route_data = batch.fetch_result.data
        request = batch.fetch_result.request
        for raw_item in route_data.data:
            if not isinstance(raw_item, GoldItem):
                raise TypeError("gold capture contains a non-GoldItem")
            self._connection.execute(
                """
                INSERT INTO gold_observations (
                    capture_id, site, board_key, observed_at, source_item_id,
                    title, sell_price, recycle_price, description, price_date,
                    url, search_text_normalized
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    batch.capture_id,
                    request.site,
                    batch.board_key,
                    batch.fetch_result.observed_at,
                    raw_item.id,
                    raw_item.title,
                    raw_item.sellPrice,
                    raw_item.recyclePrice,
                    raw_item.desc,
                    _published_at(raw_item.timestamp),
                    raw_item.url,
                    evidence_search_text(raw_item.title, raw_item.desc),
                ],
            )

    def _configure(self) -> None:
        statements = (
            "SET enable_external_access = false",
            "SET allow_community_extensions = false",
            "SET autoinstall_known_extensions = false",
            "SET autoload_known_extensions = false",
            "SET TimeZone = 'UTC'",
        )
        for statement in statements:
            self._connection.execute(statement)

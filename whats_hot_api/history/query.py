"""Typed, read-only DuckDB history queries."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from whats_hot_api.history.errors import (
    HistoryCursorError,
    HistoryQueryError,
    HistoryRangeError,
    HistoryUnavailableError,
)

_MAX_LIMIT = 200
_MAX_RANGE = timedelta(days=365)
_BUCKETS = {
    "10m": "INTERVAL '10 minutes'",
    "1h": "INTERVAL '1 hour'",
    "6h": "INTERVAL '6 hours'",
    "1d": "INTERVAL '1 day'",
}


def _duckdb():
    try:
        import duckdb
    except ImportError as exc:
        raise HistoryUnavailableError(
            "DuckDB support is not installed; install whats-hot-api[history]."
        ) from exc
    return duckdb


def _utc(value: datetime | None, *, default: datetime) -> datetime:
    if value is None:
        return default
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _encode_cursor(row: dict[str, Any]) -> str:
    raw = json.dumps(
        [
            row["observedAt"].isoformat(),
            row["captureId"],
            row["__cursorRank"],
            row["itemId"],
        ],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str, int, str]:
    try:
        if not cursor or len(cursor) > 4096:
            raise ValueError("cursor length is invalid")
        padding = "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(
            cursor + padding,
            altchars=b"-_",
            validate=True,
        )
        value = json.loads(decoded.decode())
        if not isinstance(value, list) or len(value) != 4:
            raise ValueError("cursor payload must contain four fields")
        timestamp, capture_id, cursor_rank, item_id = value
        if not isinstance(timestamp, str):
            raise TypeError("cursor timestamp must be a string")
        observed_at = datetime.fromisoformat(timestamp)
        if observed_at.tzinfo is None:
            raise ValueError("cursor timestamp must include a timezone")
        if not isinstance(capture_id, str) or not 1 <= len(capture_id) <= 256:
            raise ValueError("cursor capture id is invalid")
        if isinstance(cursor_rank, bool) or not isinstance(cursor_rank, int):
            raise TypeError("cursor rank must be an integer")
        if not isinstance(item_id, str) or len(item_id) > 2048:
            raise ValueError("cursor item id is invalid")
        return observed_at.astimezone(UTC), capture_id, cursor_rank, item_id
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
    ) as exc:
        raise HistoryCursorError("Invalid history cursor.") from exc


class HistoryReader:
    """Public history API that never exposes SQL or a writable connection."""

    def __init__(self, path: str | Path) -> None:
        database_path = Path(path).expanduser()
        if not database_path.exists():
            raise HistoryUnavailableError(
                f"History database does not exist: {database_path}"
            )
        try:
            self.__connection = _duckdb().connect(str(database_path))
            self.__connection.execute("SET TimeZone = 'UTC'")
        except Exception as exc:
            raise HistoryUnavailableError(
                "Unable to open the history database."
            ) from exc

    def close(self) -> None:
        self.__connection.close()

    def interrupt(self) -> None:
        """Interrupt the active query; DuckDB supports calling this cross-thread."""
        self.__connection.interrupt()

    def query_history(
        self,
        *,
        site: str | None = None,
        board_key: str | None = None,
        kind: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        start, end, page_limit = self._validated_window(since, until, limit)
        clauses = ["observed_at >= ?", "observed_at <= ?"]
        params: list[Any] = [start, end]
        if site:
            clauses.append("site = ?")
            params.append(site)
        if board_key:
            clauses.append("board_key = ?")
            params.append(board_key)
        if kind:
            if kind not in {"hotlist", "newsflash", "gold"}:
                raise HistoryQueryError(f"Unknown history kind: {kind}")
            clauses.append("kind = ?")
            params.append(kind)
        if cursor:
            observed_at, capture_id, cursor_rank, item_id = _decode_cursor(cursor)
            clauses.append(
                "(observed_at, capture_id, COALESCE(-rank, 0), item_id) < (?, ?, ?, ?)"
            )
            params.extend([observed_at, capture_id, cursor_rank, item_id])

        params.append(page_limit + 1)
        rows = self._query(
            f"""
            SELECT
                capture_id AS "captureId",
                kind,
                site,
                board_key AS "boardKey",
                observed_at AS "observedAt",
                item_id AS "itemId",
                rank,
                COALESCE(-rank, 0) AS "__cursorRank",
                title,
                url,
                mobile_url AS "mobileUrl",
                hot,
                source,
                description,
                content,
                published_at AS "publishedAt",
                sell_price AS "sellPrice",
                recycle_price AS "recyclePrice"
            FROM history_items
            WHERE {" AND ".join(clauses)}
            ORDER BY
                observed_at DESC,
                capture_id DESC,
                COALESCE(-rank, 0) DESC,
                item_id DESC
            LIMIT ?
            """,
            params,
        )
        return self._page(rows, page_limit)

    def search_history(
        self,
        keyword: str,
        *,
        site: str | None = None,
        board_key: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not keyword.strip():
            raise HistoryQueryError("keyword must not be empty")
        start, end, page_limit = self._validated_window(since, until, limit)
        escaped_keyword = (
            keyword.strip()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped_keyword}%"
        clauses = [
            "observed_at >= ?",
            "observed_at <= ?",
            (
                "(title ILIKE ? ESCAPE '\\' "
                "OR COALESCE(description, '') ILIKE ? ESCAPE '\\' "
                "OR COALESCE(content, '') ILIKE ? ESCAPE '\\')"
            ),
        ]
        params: list[Any] = [start, end, pattern, pattern, pattern]
        if site:
            clauses.append("site = ?")
            params.append(site)
        if board_key:
            clauses.append("board_key = ?")
            params.append(board_key)
        if cursor:
            observed_at, capture_id, cursor_rank, item_id = _decode_cursor(cursor)
            clauses.append(
                "(observed_at, capture_id, COALESCE(-rank, 0), item_id) < (?, ?, ?, ?)"
            )
            params.extend([observed_at, capture_id, cursor_rank, item_id])
        params.append(page_limit + 1)
        rows = self._query(
            f"""
            SELECT
                capture_id AS "captureId",
                kind,
                site,
                board_key AS "boardKey",
                observed_at AS "observedAt",
                item_id AS "itemId",
                rank,
                COALESCE(-rank, 0) AS "__cursorRank",
                title,
                url,
                mobile_url AS "mobileUrl",
                hot,
                source,
                description,
                content,
                published_at AS "publishedAt",
                sell_price AS "sellPrice",
                recycle_price AS "recyclePrice"
            FROM history_items
            WHERE {" AND ".join(clauses)}
            ORDER BY
                observed_at DESC,
                capture_id DESC,
                COALESCE(-rank, 0) DESC,
                item_id DESC
            LIMIT ?
            """,
            params,
        )
        return self._page(rows, page_limit)

    def get_trend_series(
        self,
        *,
        site: str,
        board_key: str,
        item_id: str,
        bucket: str = "1h",
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        interval = _BUCKETS.get(bucket)
        if interval is None:
            raise HistoryQueryError(
                f"Unsupported bucket '{bucket}'. Valid values: {sorted(_BUCKETS)}"
            )
        start, end, _ = self._validated_window(since, until, 200)
        rows = self._query(
            f"""
            SELECT
                time_bucket({interval}, observed_at) AS "bucketStart",
                MIN(position) AS "bestRank",
                MAX(position) AS "worstRank",
                AVG(position) AS "averageRank",
                MIN(hot) AS "minHot",
                MAX(hot) AS "maxHot",
                COUNT(*) AS "samples"
            FROM hotlist_observations
            WHERE site = ?
              AND board_key = ?
              AND source_item_id = ?
              AND observed_at >= ?
              AND observed_at <= ?
            GROUP BY 1
            ORDER BY 1
            """,
            [site, board_key, item_id, start, end],
        )
        return {
            "site": site,
            "boardKey": board_key,
            "itemId": item_id,
            "bucket": bucket,
            "series": rows,
        }

    def get_capture(self, capture_id: str) -> dict[str, Any] | None:
        captures = self._query(
            """
            SELECT
                capture_id AS "captureId",
                run_key AS "runKey",
                job_id AS "jobId",
                site,
                board_key AS "boardKey",
                path_type AS "pathType",
                params_json AS "params",
                kind,
                title,
                type_label AS "type",
                scheduled_for AS "scheduledFor",
                observed_at AS "observedAt",
                response_update_at AS "responseUpdateAt",
                item_count AS "itemCount",
                content_hash AS "contentHash"
            FROM captures
            WHERE capture_id = ?
            """,
            [capture_id],
        )
        if not captures:
            return None
        items = self._query(
            """
            SELECT
                item_id AS "itemId",
                rank,
                title,
                url,
                mobile_url AS "mobileUrl",
                hot,
                source,
                description,
                content,
                published_at AS "publishedAt",
                sell_price AS "sellPrice",
                recycle_price AS "recyclePrice"
            FROM history_items
            WHERE capture_id = ?
            ORDER BY rank NULLS LAST, item_id
            """,
            [capture_id],
        )
        return {**captures[0], "items": items}

    def get_storage_stats(self) -> dict[str, Any]:
        counts = self._query(
            """
            SELECT
                (SELECT COUNT(*) FROM captures) AS "captures",
                (SELECT COUNT(*) FROM hotlist_observations) AS "hotlistRows",
                (
                    SELECT COUNT(*)
                    FROM (
                        SELECT DISTINCT site, board_key, source_item_id
                        FROM newsflash_occurrences
                    )
                ) AS "newsflashItems",
                (SELECT COUNT(*) FROM gold_observations) AS "goldRows",
                (SELECT MAX(observed_at) FROM captures) AS "latestObservedAt"
            """
        )
        return {"enabled": True, **counts[0]}

    def _query(
        self,
        sql: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            cursor = self.__connection.execute(sql, params or [])
            columns = [column[0] for column in cursor.description]
            return [
                {
                    key: value
                    for key, value in zip(columns, row, strict=True)
                    if value is not None
                }
                for row in cursor.fetchall()
            ]
        except HistoryQueryError:
            raise
        except Exception as exc:
            raise HistoryQueryError("History query failed.") from exc

    @staticmethod
    def _validated_window(
        since: datetime | None,
        until: datetime | None,
        limit: int,
    ) -> tuple[datetime, datetime, int]:
        if not 1 <= limit <= _MAX_LIMIT:
            raise HistoryQueryError(f"limit must be between 1 and {_MAX_LIMIT}")
        now = datetime.now(UTC)
        end = _utc(until, default=now)
        start = _utc(since, default=end - timedelta(days=7))
        if start > end:
            raise HistoryQueryError("since must not be after until")
        if end - start > _MAX_RANGE:
            raise HistoryRangeError("History range must not exceed 365 days.")
        return start, end, limit

    @staticmethod
    def _page(rows: list[dict[str, Any]], limit: int) -> dict[str, Any]:
        truncated = len(rows) > limit
        selected = rows[:limit]
        next_cursor = _encode_cursor(selected[-1]) if truncated and selected else None
        items = [
            {key: value for key, value in row.items() if key != "__cursorRank"}
            for row in selected
        ]
        return {
            "items": items,
            "nextCursor": next_cursor,
            "truncated": truncated,
        }

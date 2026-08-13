"""Contract v1 read-only DuckDB history queries."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from whats_hot_api.fetch import board_key_read_candidates
from whats_hot_api.history.cursor import (
    DEFAULT_CURSOR_TTL,
    HistoryCursorCodec,
    HistorySnapshotCursor,
)
from whats_hot_api.history.errors import (
    HistoryQueryError,
    HistoryRangeError,
    HistoryUnavailableError,
)
from whats_hot_api.history.text import normalize_search_text

_MAX_LIMIT = 200
_KINDS = frozenset({"hotlist", "newsflash", "gold"})
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


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise HistoryQueryError("History timestamps must include a timezone.")
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _append_board_filter(
    clauses: list[str],
    params: list[Any],
    *,
    column: str,
    board_key: str,
) -> None:
    candidates = board_key_read_candidates(board_key)
    placeholders = ", ".join("?" for _candidate in candidates)
    clauses.append(f"{column} IN ({placeholders})")
    params.extend(candidates)


class HistoryReader:
    """Public history API that never exposes SQL or a writable connection."""

    def __init__(
        self,
        path: str | Path,
        *,
        default_history_days: int = 7,
        max_history_days: int = 365,
        cursor_secret: bytes | None = None,
        cursor_ttl: timedelta = DEFAULT_CURSOR_TTL,
    ) -> None:
        if not 1 <= default_history_days <= max_history_days <= 3650:
            raise ValueError("Invalid history window limits.")
        database_path = Path(path).expanduser()
        if not database_path.exists():
            raise HistoryUnavailableError(
                f"History database does not exist: {database_path}"
            )
        self._default_range = timedelta(days=default_history_days)
        self._max_range = timedelta(days=max_history_days)
        self._cursor_codec = HistoryCursorCodec(
            cursor_secret or secrets.token_bytes(32),
            ttl=cursor_ttl,
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
        return self._history_page(
            query_name="history",
            keyword=None,
            site=site,
            board_key=board_key,
            kind=kind,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )

    def search_history(
        self,
        keyword: str,
        *,
        site: str | None = None,
        board_key: str | None = None,
        kind: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(keyword, str) or len(keyword) > 500:
            raise HistoryQueryError("keyword must contain at most 500 characters")
        normalized = normalize_search_text(keyword)
        if not normalized:
            raise HistoryQueryError("keyword must not be empty")
        return self._history_page(
            query_name="search",
            keyword=normalized,
            site=site,
            board_key=board_key,
            kind=kind,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )

    def _history_page(
        self,
        *,
        query_name: str,
        keyword: str | None,
        site: str | None,
        board_key: str | None,
        kind: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        page_limit = self._validate_limit(limit)
        self._validate_kind(kind)
        provided_since = _utc(since)
        provided_until = _utc(until)
        filters: dict[str, Any] = {
            "site": site,
            "boardKey": board_key,
            "kind": kind,
            "since": _iso(provided_since),
            "until": _iso(provided_until),
        }
        if keyword is not None:
            filters["keyword"] = keyword

        snapshot: HistorySnapshotCursor | None = None
        if cursor is not None:
            snapshot = self._cursor_codec.decode(
                cursor,
                query=query_name,
                filters=filters,
            )
            start, end = snapshot.since, snapshot.until
            as_of = snapshot.as_of
            watermark = snapshot.watermark
        else:
            as_of = datetime.now(UTC)
            start, end = self._validated_window(
                provided_since,
                provided_until,
                now=as_of,
            )
            watermark = self._max_watermark()

        # The ingest watermark prevents concurrent appends from entering a page
        # chain.  The timestamp boundary is independently required because rows
        # already below that watermark may carry an observed_at later than this
        # request's snapshot time (for example after clock skew or a backfill).
        base_clauses = ["h.ingest_sequence <= ?", "h.observed_at <= ?"]
        base_params: list[Any] = [watermark, as_of]
        if site is not None:
            base_clauses.append("h.site = ?")
            base_params.append(site)
        if board_key is not None:
            _append_board_filter(
                base_clauses,
                base_params,
                column="h.board_key",
                board_key=board_key,
            )
        if kind is not None:
            base_clauses.append("h.kind = ?")
            base_params.append(kind)

        page_clauses = ["h.observed_at >= ?", "h.observed_at <= ?"]
        page_params: list[Any] = [start, end]
        if keyword is not None:
            page_clauses.append("contains(h.search_text_normalized, ?)")
            page_params.append(keyword)
        if snapshot is not None:
            page_clauses.append(
                "(h.observed_at < ? OR "
                "(h.observed_at = ? AND h.ingest_sequence > ?))"
            )
            page_params.extend(
                [
                    snapshot.after_observed_at,
                    snapshot.after_observed_at,
                    snapshot.after_ingest_sequence,
                ]
            )

        rows = self._query(
            f"""
            WITH snapshot AS (
                SELECT h.*, c.response_update_at
                FROM history_items h
                JOIN captures c USING (capture_id)
                WHERE {" AND ".join(base_clauses)}
            ), lifecycle AS (
                SELECT
                    kind,
                    site,
                    board_key,
                    item_id,
                    MIN(observed_at) AS first_seen_at,
                    MAX(observed_at) AS last_seen_at
                FROM snapshot
                GROUP BY kind, site, board_key, item_id
            )
            SELECT
                h.kind,
                h.site,
                CASE WHEN h.board_key = 'default' THEN 'hot'
                     ELSE h.board_key END AS "boardKey",
                'duckdb:' || lpad(
                    CAST(h.ingest_sequence AS VARCHAR), 20, '0'
                ) AS "evidenceId",
                h.item_id AS "itemId",
                h.capture_id AS "captureId",
                h.title,
                h.url,
                h.description,
                h.rank,
                h.hot,
                h.response_update_at AS "updateTime",
                h.observed_at AS "observedAt",
                lifecycle.first_seen_at AS "firstSeenAt",
                lifecycle.last_seen_at AS "lastSeenAt",
                h.published_at AS "publishedAt",
                h.ingest_sequence AS "__ingestSequence"
            FROM snapshot h
            JOIN lifecycle USING (kind, site, board_key, item_id)
            WHERE {" AND ".join(page_clauses)}
            ORDER BY h.observed_at DESC, h.ingest_sequence ASC
            LIMIT ?
            """,
            [*base_params, *page_params, page_limit + 1],
        )
        return self._page(
            rows,
            limit=page_limit,
            query_name=query_name,
            filters=filters,
            since=start,
            until=end,
            as_of=as_of,
            watermark=watermark,
            coverage=self.get_data_coverage(
                site=site,
                board_key=board_key,
                kind=kind,
                watermark=watermark,
                as_of=as_of,
            ),
        )

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
        now = datetime.now(UTC)
        start, end = self._validated_window(_utc(since), _utc(until), now=now)
        watermark = self._max_watermark()
        board_candidates = board_key_read_candidates(board_key)
        board_placeholders = ", ".join("?" for _candidate in board_candidates)
        rows = self._query(
            f"""
            SELECT
                time_bucket({interval}, observed_at) AS "bucketStart",
                MIN(position) AS "bestRank",
                MAX(position) AS "worstRank",
                CAST(AVG(position) AS DOUBLE) AS "averageRank",
                MIN(hot) AS "minHot",
                MAX(hot) AS "maxHot",
                COUNT(*) AS "samples"
            FROM hotlist_observations
            WHERE site = ?
              AND board_key IN ({board_placeholders})
              AND source_item_id = ?
              AND observed_at >= ?
              AND observed_at <= ?
              AND ingest_sequence <= ?
            GROUP BY 1
            ORDER BY 1
            """,
            [
                site,
                *board_candidates,
                item_id,
                start,
                end,
                watermark,
            ],
        )
        return {
            "site": site,
            "boardKey": board_key,
            "itemId": item_id,
            "bucket": bucket,
            "series": rows,
            "coverage": self.get_data_coverage(
                site=site,
                board_key=board_key,
                kind="hotlist",
                watermark=watermark,
                as_of=now,
            ),
        }

    def get_data_coverage(
        self,
        *,
        site: str | None = None,
        board_key: str | None = None,
        kind: str | None = None,
        watermark: int | None = None,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        self._validate_kind(kind)
        effective_watermark = self._max_watermark() if watermark is None else watermark
        effective_as_of = _utc(as_of) or datetime.now(UTC)
        clauses = ["ingest_sequence <= ?", "observed_at <= ?"]
        params: list[Any] = [effective_watermark, effective_as_of]
        if site is not None:
            clauses.append("site = ?")
            params.append(site)
        if board_key is not None:
            _append_board_filter(
                clauses,
                params,
                column="board_key",
                board_key=board_key,
            )
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        where = " AND ".join(clauses)
        stats = self._query(
            f"""
            SELECT
                MIN(observed_at) AS "earliestAvailableAt",
                MAX(observed_at) AS "latestAvailableAt"
            FROM history_items
            WHERE {where}
            """,
            params,
        )[0]
        sites = self._query(
            f"""
            SELECT DISTINCT site
            FROM history_items
            WHERE {where}
            ORDER BY site
            """,
            params,
        )
        return {
            "historyEnabled": True,
            **stats,
            "configuredSites": [row["site"] for row in sites],
            "complete": False,
            "limitations": ["retention-window"],
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

    def _max_watermark(self) -> int:
        row = self._query(
            'SELECT MAX(ingest_sequence) AS "watermark" FROM history_items'
        )[0]
        return int(row.get("watermark", 0))

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

    def _validated_window(
        self,
        since: datetime | None,
        until: datetime | None,
        *,
        now: datetime,
    ) -> tuple[datetime, datetime]:
        end = min(until or now, now)
        start = since or end - self._default_range
        if start > end:
            raise HistoryQueryError("since must not be after until")
        if end - start > self._max_range:
            raise HistoryRangeError(
                "History range exceeds Backend capability."
            )
        return start, end

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if isinstance(limit, bool) or not 1 <= limit <= _MAX_LIMIT:
            raise HistoryQueryError(f"limit must be between 1 and {_MAX_LIMIT}")
        return limit

    @staticmethod
    def _validate_kind(kind: str | None) -> None:
        if kind is not None and kind not in _KINDS:
            raise HistoryQueryError(f"Unknown history kind: {kind}")

    def _page(
        self,
        rows: list[dict[str, Any]],
        *,
        limit: int,
        query_name: str,
        filters: dict[str, Any],
        since: datetime,
        until: datetime,
        as_of: datetime,
        watermark: int,
        coverage: dict[str, Any],
    ) -> dict[str, Any]:
        truncated = len(rows) > limit
        selected = rows[:limit]
        next_cursor: str | None = None
        if truncated and selected:
            last = selected[-1]
            next_cursor = self._cursor_codec.encode(
                query=query_name,
                filters=filters,
                since=since,
                until=until,
                as_of=as_of,
                watermark=watermark,
                after_observed_at=last["observedAt"],
                after_ingest_sequence=last["__ingestSequence"],
            )
        items = [
            {
                key: value
                for key, value in row.items()
                if key != "__ingestSequence"
            }
            for row in selected
        ]
        return {
            "items": items,
            "nextCursor": next_cursor,
            "truncated": truncated,
            "asOf": as_of,
            "coverage": coverage,
        }

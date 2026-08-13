"""Signed, filter-bound snapshot cursors for Contract v1 history reads."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from whats_hot_api.history.errors import (
    HistoryCursorError,
    HistoryCursorExpiredError,
)

CURSOR_CONTRACT_MAJOR = "1"
CURSOR_SORT = "observedAt:desc,evidenceId:asc"
DEFAULT_CURSOR_TTL = timedelta(hours=24)
_MAX_CURSOR_LENGTH = 4096


@dataclass(frozen=True, slots=True)
class HistorySnapshotCursor:
    query: str
    filters: dict[str, Any]
    since: datetime
    until: datetime
    as_of: datetime
    watermark: int
    after_observed_at: datetime
    after_ingest_sequence: int


class HistoryCursorCodec:
    """Encode and verify opaque HMAC-SHA256 cursor tokens."""

    def __init__(
        self,
        secret: bytes,
        *,
        ttl: timedelta = DEFAULT_CURSOR_TTL,
    ) -> None:
        if len(secret) < 16:
            raise ValueError("History cursor secret must be at least 16 bytes.")
        if ttl < timedelta(0):
            raise ValueError("History cursor TTL must not be negative.")
        self._secret = secret
        self._ttl = ttl

    def encode(
        self,
        *,
        query: str,
        filters: dict[str, Any],
        since: datetime,
        until: datetime,
        as_of: datetime,
        watermark: int,
        after_observed_at: datetime,
        after_ingest_sequence: int,
    ) -> str:
        payload = {
            "v": 1,
            "contract": CURSOR_CONTRACT_MAJOR,
            "query": query,
            "sort": CURSOR_SORT,
            "filters": filters,
            "window": {
                "since": _iso(since),
                "until": _iso(until),
            },
            "asOf": _iso(as_of),
            "expiresAt": _iso(as_of + self._ttl),
            "watermark": watermark,
            "after": {
                "observedAt": _iso(after_observed_at),
                "ingestSequence": after_ingest_sequence,
            },
        }
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        signature = hmac.new(self._secret, raw, hashlib.sha256).digest()
        return f"{_b64encode(raw)}.{_b64encode(signature)}"

    def decode(
        self,
        cursor: str,
        *,
        query: str,
        filters: dict[str, Any],
        now: datetime | None = None,
    ) -> HistorySnapshotCursor:
        try:
            if not cursor or len(cursor) > _MAX_CURSOR_LENGTH:
                raise ValueError("cursor length is invalid")
            encoded_payload, encoded_signature = cursor.split(".", 1)
            raw = _b64decode(encoded_payload)
            signature = _b64decode(encoded_signature)
            expected = hmac.new(self._secret, raw, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("cursor signature is invalid")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or set(payload) != {
                "v",
                "contract",
                "query",
                "sort",
                "filters",
                "window",
                "asOf",
                "expiresAt",
                "watermark",
                "after",
            }:
                raise ValueError("cursor payload shape is invalid")
            if (
                payload["v"] != 1
                or payload["contract"] != CURSOR_CONTRACT_MAJOR
                or payload["query"] != query
                or payload["sort"] != CURSOR_SORT
                or payload["filters"] != filters
            ):
                raise ValueError("cursor is not bound to this query")
            window = payload["window"]
            after = payload["after"]
            if not isinstance(window, dict) or set(window) != {"since", "until"}:
                raise ValueError("cursor window is invalid")
            if not isinstance(after, dict) or set(after) != {
                "observedAt",
                "ingestSequence",
            }:
                raise ValueError("cursor position is invalid")
            watermark = payload["watermark"]
            sequence = after["ingestSequence"]
            if (
                isinstance(watermark, bool)
                or not isinstance(watermark, int)
                or watermark < 0
                or isinstance(sequence, bool)
                or not isinstance(sequence, int)
                or sequence < 1
                or sequence > watermark
            ):
                raise ValueError("cursor watermark is invalid")
            since = _parse_datetime(window["since"])
            until = _parse_datetime(window["until"])
            as_of = _parse_datetime(payload["asOf"])
            expires_at = _parse_datetime(payload["expiresAt"])
            after_observed_at = _parse_datetime(after["observedAt"])
            if since > until or expires_at < as_of:
                raise ValueError("cursor timestamps are invalid")
        except (
            AttributeError,
            binascii.Error,
            json.JSONDecodeError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
        ) as exc:
            raise HistoryCursorError("Invalid history cursor.") from exc

        effective_now = now or datetime.now(UTC)
        if effective_now.tzinfo is None:
            effective_now = effective_now.replace(tzinfo=UTC)
        if effective_now.astimezone(UTC) >= expires_at:
            raise HistoryCursorExpiredError("History cursor has expired.")
        return HistorySnapshotCursor(
            query=query,
            filters=filters,
            since=since,
            until=until,
            as_of=as_of,
            watermark=watermark,
            after_observed_at=after_observed_at,
            after_ingest_sequence=sequence,
        )


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Cursor timestamps must include a timezone.")
    return value.astimezone(UTC).isoformat()


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise TypeError("cursor timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("cursor timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)

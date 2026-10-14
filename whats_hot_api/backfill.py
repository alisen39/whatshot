"""Newsflash backfill contract: how a route pages backwards in time.

Every newsflash route declares ``BACKFILL`` (path type -> ``BackfillSpec``;
``"*"`` covers all types). Routes whose strategy pages upstream also export::

    async def backfill_page(
        path_type: str,
        params: dict[str, str],
        cursor: str | None,
        *,
        before: datetime | None,
    ) -> BackfillPage

``cursor=None`` requests the newest page. ``next_cursor=None`` means the
upstream has no older page. Time cursors must be boundary-inclusive (items
sharing the previous page's oldest timestamp are returned again); callers
deduplicate by item id. Snapshot sources need no ``backfill_page``: the fetch
service reuses ``handle_route`` for their single current page.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from whats_hot_api.models import RouterData


class BackfillStrategy(StrEnum):
    TIME_CURSOR = "time_cursor"
    OPAQUE_CURSOR = "opaque_cursor"
    PAGE_NUMBER = "page_number"
    DATE_QUERY = "date_query"
    SNAPSHOT = "snapshot"
    UNSUPPORTED = "unsupported"


PAGED_STRATEGIES = frozenset(
    {
        BackfillStrategy.TIME_CURSOR,
        BackfillStrategy.OPAQUE_CURSOR,
        BackfillStrategy.PAGE_NUMBER,
        BackfillStrategy.DATE_QUERY,
    }
)

TimePrecision = Literal["second", "minute", "day"]


@dataclass(frozen=True, slots=True)
class BackfillSpec:
    strategy: BackfillStrategy
    notes: str
    max_pages: int | None = None
    page_size: int | None = None
    time_precision: TimePrecision = "second"
    min_interval_ms: int = 1000
    supports_before: bool = False
    verified_at: str | None = None

    def __post_init__(self) -> None:
        if not self.notes.strip():
            raise ValueError("BackfillSpec.notes must describe known limits or say 'none'")
        if self.max_pages is not None and self.max_pages < 1:
            raise ValueError("BackfillSpec.max_pages must be positive")

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "notes": self.notes,
            "maxPages": self.max_pages,
            "pageSize": self.page_size,
            "timePrecision": self.time_precision,
            "minIntervalMs": self.min_interval_ms,
            "supportsBefore": self.supports_before,
            "verifiedAt": self.verified_at,
        }


@dataclass(frozen=True, slots=True)
class BackfillPage:
    data: RouterData
    next_cursor: str | None
    raw_digest: str | None = None


BackfillPageHandler = Callable[..., Awaitable[BackfillPage]]


def unsupported(notes: str) -> BackfillSpec:
    return BackfillSpec(strategy=BackfillStrategy.UNSUPPORTED, notes=notes)


def snapshot(notes: str, **kwargs: Any) -> BackfillSpec:
    return BackfillSpec(strategy=BackfillStrategy.SNAPSHOT, notes=notes, **kwargs)


def resolve_spec(
    declared: Mapping[str, BackfillSpec] | None,
    path_type: str,
) -> BackfillSpec | None:
    if not declared:
        return None
    return declared.get(path_type) or declared.get("*")


def encode_cursor(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode_cursor(cursor: str | None) -> dict[str, Any]:
    if not cursor:
        return {}
    try:
        value = json.loads(cursor)
    except ValueError as exc:
        raise ValueError(f"invalid backfill cursor: {cursor!r}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"invalid backfill cursor: {cursor!r}")
    return value


def payload_digest(payload: Any) -> str:
    if isinstance(payload, bytes):
        raw = payload
    elif isinstance(payload, str):
        raw = payload.encode()
    else:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def oldest_timestamp_ms(data: RouterData) -> int | None:
    stamps = [item.timestamp for item in data.data if getattr(item, "timestamp", None)]
    return min(stamps) if stamps else None


def ms_to_datetime_cutoff(before: datetime | None) -> int | None:
    return int(before.timestamp() * 1000) if before is not None else None

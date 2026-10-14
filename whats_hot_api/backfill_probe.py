"""Read-only live probe of a route's backfill paging.

    uv run python -m whats_hot_api.backfill_probe jrj hot --hours 6
    uv run python -m whats_hot_api.backfill_probe cls telegraph --pages 5

Pages backwards through ``FetchService.backfill_page`` (no cache reads or
writes) and prints, per page, item count, time span, new ids, and whether the
page joins the previous one without a hole. Use it to record ``verified_at``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta

from whats_hot_api.fetch import FetchRequest
from whats_hot_api.registry import discover_and_register_routes, fetch_service


def _fmt(ms: int | None) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%m-%d %H:%M:%S") if ms else "-"


async def probe(site: str, path_type: str, *, hours: float, max_pages: int, params: dict[str, str]) -> dict:
    discover_and_register_routes()
    spec = fetch_service.describe_backfill(site, path_type)
    request = FetchRequest(site=site, path_type=path_type, params=params)
    since_ms = int((datetime.now(UTC) - timedelta(hours=hours)).timestamp() * 1000)
    cursor: str | None = None
    seen: set[str] = set()
    previous_oldest: int | None = None
    previous_inner = 0
    pages = []
    stop = "max_pages"
    for page_no in range(1, max_pages + 1):
        page = await fetch_service.backfill_page(request, cursor)
        items = page.data.data
        stamps = [i.timestamp for i in items if getattr(i, "timestamp", None)]
        oldest, newest = (min(stamps), max(stamps)) if stamps else (None, None)
        ids = [str(i.id) for i in items]
        fresh = [i for i in ids if i not in seen]
        seen.update(ids)
        # A hole is a page boundary gap clearly larger than gaps inside the pages.
        ordered = sorted(stamps)
        inner = max((b - a for a, b in zip(ordered, ordered[1:])), default=0)
        joined = (
            previous_oldest is None
            or newest is None
            or previous_oldest - newest <= max(60_000, 2 * max(inner, previous_inner))
        )
        previous_inner = inner
        pages.append({"page": page_no, "items": len(items), "new": len(fresh), "newest": _fmt(newest),
                      "oldest": _fmt(oldest), "joinsPrevious": joined, "nextCursor": page.next_cursor})
        print(f"p{page_no:>3} items={len(items):>3} new={len(fresh):>3} {_fmt(newest)} → {_fmt(oldest)}"
              f" joins={'yes' if joined else 'NO'} next={page.next_cursor}")
        previous_oldest = oldest if oldest is not None else previous_oldest
        if oldest is not None and oldest <= since_ms:
            stop = "reached_since"
            break
        if not items or page.next_cursor is None or not fresh:
            stop = "upstream_exhausted"
            break
        cursor = page.next_cursor
        await asyncio.sleep((spec.min_interval_ms if spec else 1000) / 1000)
    result = {"site": site, "pathType": path_type, "strategy": spec.strategy.value if spec else None,
              "stop": stop, "uniqueItems": len(seen), "pages": len(pages),
              "allJoined": all(p["joinsPrevious"] for p in pages)}
    print(json.dumps(result, ensure_ascii=False))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site")
    parser.add_argument("path_type")
    parser.add_argument("--hours", type=float, default=3.0)
    parser.add_argument("--pages", type=int, default=10)
    parser.add_argument("--param", action="append", default=[], help="extra board dimension k=v")
    args = parser.parse_args()
    params = dict(p.split("=", 1) for p in args.param)
    asyncio.run(probe(args.site, args.path_type, hours=args.hours, max_pages=args.pages, params=params))


if __name__ == "__main__":
    main()

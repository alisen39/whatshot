from __future__ import annotations

import asyncio
import html
import re
import time
from collections.abc import Awaitable, Callable

import httpx

# arXiv asks automated clients to keep at least three seconds between requests,
# back off 30-60 seconds when errors occur, and identify themselves with a
# descriptive User-Agent (https://info.arxiv.org/help/api/tou.html). Scheduler
# sweeps fire several arXiv boards at once, and bursts draw 429/503. During
# congestion windows the arXiv edge (Fastly/Varnish) also intermittently returns
# empty-body 406 and occasional 500 responses to httpx clients, so those are
# treated as transient too.
_MIN_SPACING_SECONDS = 3.0
# 406: empty-body edge glitch during congestion (not a real negotiation
# failure); 429: "Rate exceeded."; 500/503: edge/upstream overload.
_RETRYABLE_STATUSES = {406, 429, 500, 503}
_MAX_ATTEMPTS = 3
# Extra backoff before each retry, on top of the 3s cross-board pacing: one
# arXiv-recommended 30-60s backoff split across the two retries so a transient
# congestion window has time to clear.
_RETRY_DELAYS_SECONDS = (15.0, 45.0)

_spacing_lock = asyncio.Lock()
_last_request_at = -_MIN_SPACING_SECONDS

_USER_AGENT = "whats-hot-api/0.2 (+https://github.com/alisen39/whatshot)"


def arxiv_headers() -> dict:
    """Descriptive identity headers arXiv etiquette asks automated clients to send."""
    return {"User-Agent": _USER_AGENT}


def _monotonic() -> float:
    return time.monotonic()


async def _respect_spacing() -> None:
    global _last_request_at
    async with _spacing_lock:
        wait = _MIN_SPACING_SECONDS - (_monotonic() - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = _monotonic()


async def fetch_with_spacing[T](fetch: Callable[[], Awaitable[T]]) -> T:
    """Run one arXiv request with cross-board spacing and backed-off retries.

    Timeout and {406, 429, 500, 503} status errors are retried up to three
    total attempts: 15s before the first retry, 45s before the second, each
    on top of the regular 3s cross-board pacing. Non-retryable statuses
    re-raise immediately, and exhausting all attempts re-raises the last
    error.

    The caller supplies the fetch closure so per-module tests can keep patching
    their own ``get`` wrapper.
    """
    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        if attempt > 0:
            await asyncio.sleep(_RETRY_DELAYS_SECONDS[attempt - 1])
        await _respect_spacing()
        try:
            return await fetch()
        except httpx.TimeoutException as exc:
            last_error = exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _RETRYABLE_STATUSES:
                raise
            last_error = exc
    assert last_error is not None
    raise last_error


# --- Announcement listing pages (/list/{category}/new) ---
# tophub 的 arXiv 节点对应"最近一次公告"(新投稿 + 交叉投稿 + 替换版本),与 export API
# 的"按提交时间取 2000 条"不是同一个列表,且 export API 间歇 406;公告类路由改取始终
# 显示最近一次公告的列表页。解析结构:list-title、list-authors、p.mathjax、Total of N entries。
_LIST_ENTRY = re.compile(r"<dt>.*?<a href ?=\"/abs/([^\"]+)\".*?</dt>\s*<dd>(.*?)</dd>", re.DOTALL)
_LIST_TOTAL = re.compile(r"Total of (\d+) entries")
_LIST_HEADING = re.compile(r"<h3>(Showing new listings for [^<]+)</h3>")


def _listing_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_new_listing(page: str) -> tuple[str, list[dict]]:
    """Parse an arXiv announcement listing page into (heading, entries)."""
    entries = []
    for arxiv_id, dd in _LIST_ENTRY.findall(page):
        title = re.search(r"<div class='list-title[^']*'>(.*?)</div>", dd, re.DOTALL)
        authors = re.findall(r"<div class='list-authors'>(.*?)</div>", dd, re.DOTALL)
        abstract = re.search(r"<p class='mathjax'>(.*?)</p>", dd, re.DOTALL)
        names = re.findall(r"<a [^>]*>(.*?)</a>", authors[0], re.DOTALL) if authors else []
        entries.append({
            "id": arxiv_id,
            "title": _listing_text(title.group(1)).removeprefix("Title:").strip() if title else "",
            "author": _listing_text(names[0]) if names else None,  # 与既有路由一致:只取第一作者
            "desc": _listing_text(abstract.group(1))[:500] if abstract else None,
        })
    heading = _LIST_HEADING.search(page)
    return (heading.group(1) if heading else ""), entries


def check_listing_total(page: str, parsed: int, category: str, heading: str) -> str:
    """页面写明了本次公告总条数;解析数对不上说明结构变了或被 show=2000 截断,直接报错。"""
    total = _LIST_TOTAL.search(page)
    if total:
        if int(total.group(1)) != parsed:
            raise RuntimeError(
                f"arXiv {category} page declares {total.group(1)} entries but {parsed} were parsed"
            )
        return heading
    note = "page lacks \"Total of N entries\"; completeness not verifiable"
    return f"{heading}; {note}" if heading else note

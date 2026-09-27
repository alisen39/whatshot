from __future__ import annotations

import asyncio
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

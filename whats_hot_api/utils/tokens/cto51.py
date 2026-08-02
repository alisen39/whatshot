"""51CTO token fetching and request signing."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from whats_hot_api.utils.cache import CacheData, cache
from whats_hot_api.utils.http_client import get


def _md5(s: str) -> str:
    return hashlib.md5(s.encode(), usedforsecurity=False).hexdigest()


async def get_token() -> str:
    """Fetch a 51CTO API token, using cache when available."""
    cached = await cache.get("51cto-token")
    if cached and cached.data:
        return cached.data

    result = await get(url="https://api-media.51cto.com/api/token-get", no_cache=True)
    token: str = result.data["data"]["data"]["token"]

    await cache.set(
        "51cto-token",
        CacheData(
            update_time=datetime.now(timezone.utc).isoformat(),
            data=token,
        ),
    )
    return token


def sign(
    request_path: str,
    payload: dict | None = None,
    timestamp: int = 0,
    token: str = "",
) -> str:
    """Compute a 51CTO API request signature.

    Matches the JS logic: ``md5(md5(requestPath) + md5(sortedParams + md5(token) + timestamp))``
    where ``sortedParams`` is ``Object.keys(payload).sort()`` coerced to a string
    (i.e. ``Array.prototype.toString()`` which joins with commas).
    """
    if payload is None:
        payload = {}
    payload["timestamp"] = timestamp
    payload["token"] = token

    sorted_params = sorted(payload.keys())
    # JS Array.toString() joins with commas
    sorted_params_str = ",".join(sorted_params)
    return _md5(_md5(request_path) + _md5(sorted_params_str + _md5(token) + str(timestamp)))

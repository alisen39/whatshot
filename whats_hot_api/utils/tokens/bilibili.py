"""Bilibili Web WBI signature authentication."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

from whats_hot_api.utils.cache import CacheData, cache
from whats_hot_api.utils.http_client import get

_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5,
    49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55,
    40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57,
    62, 11, 36, 20, 34, 44, 52,
]


def _get_mixin_key(orig: str) -> str:
    """Shuffle characters of *orig* according to the encoding table."""
    return "".join(orig[n] for n in _MIXIN_KEY_ENC_TAB)[:32]


def _enc_wbi(params: dict[str, str | int], img_key: str, sub_key: str) -> str:
    """Sign request parameters with WBI."""
    mixin_key = _get_mixin_key(img_key + sub_key)
    curr_time = round(time.time())
    chr_filter = re.compile(r"[!'()*]")

    # Add wts field
    params["wts"] = curr_time

    # Sort by key and build query string
    parts: list[str] = []
    for key in sorted(params.keys()):
        value = chr_filter.sub("", str(params[key]))
        parts.append(f"{quote(key, safe='')}={quote(value, safe='')}")
    query = "&".join(parts)

    # Compute w_rid
    wbi_sign = hashlib.md5(
        (query + mixin_key).encode(), usedforsecurity=False
    ).hexdigest()
    return query + "&w_rid=" + wbi_sign


async def _get_wbi_keys() -> tuple[str, str]:
    """Fetch the latest img_key and sub_key from Bilibili."""
    result = await get(
        url="https://api.bilibili.com/x/web-interface/nav",
        headers={
            "Cookie": "SESSDATA=xxxxxx",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
            ),
            "Referer": "https://www.bilibili.com/",
        },
        no_cache=True,
    )
    wbi_img = result.data.get("data", {}).get("wbi_img", {})
    img_url: str = wbi_img.get("img_url", "")
    sub_url: str = wbi_img.get("sub_url", "")

    img_key = img_url[img_url.rfind("/") + 1 : img_url.rfind(".")]
    sub_key = sub_url[sub_url.rfind("/") + 1 : sub_url.rfind(".")]
    return img_key, sub_key


async def get_bili_wbi() -> str:
    """Return a WBI-signed query string, using cache when available."""
    cached = await cache.get("bilibili-wbi")
    if cached and cached.data:
        return cached.data

    img_key, sub_key = await _get_wbi_keys()
    params: dict[str, str | int] = {"foo": "114", "bar": "514", "baz": 1919810}
    query = _enc_wbi(params, img_key, sub_key)

    await cache.set(
        "bilibili-wbi",
        CacheData(
            update_time=datetime.now(timezone.utc).isoformat(),
            data=query,
        ),
    )
    return query

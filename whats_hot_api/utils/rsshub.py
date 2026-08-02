from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from whats_hot_api.config import config
from whats_hot_api.models import ListItem
from whats_hot_api.utils.http_client import CacheOnlyMiss, RequestResult, get

DEFAULT_RSSHUB_BASE_URLS = (
    "https://rss.datuan.dev",
    "https://rss.4040940.xyz",
    "https://rsshub.cups.moe",
    "https://rss.spriple.org",
    "https://rsshub-balancer.virworks.moe",
    "https://rsshub.umzzz.com",
    "https://rsshub.isrss.com",
)


async def fetch_rsshub_feed(
    *,
    route_name: str,
    route_path: str,
    params: dict[str, str | int | bool],
    no_cache: bool,
) -> dict[str, Any]:
    """Fetch one route-owned RSSHub feed with instance failover."""
    query = {"format": "json", **{key: str(value) for key, value in params.items()}}
    normalized_path = route_path if route_path.startswith("/") else f"/{route_path}"
    errors: list[str] = []
    cache_only_miss: CacheOnlyMiss | None = None
    for base_url in _base_urls():
        url = f"{base_url.rstrip('/')}{normalized_path}"
        try:
            result = await get(
                url=url,
                params=query,
                no_cache=no_cache,
                response_type="json",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "Accept": "application/json"},
                cache_key=f"whatshot:rsshub:{route_name}:{base_url}:{urlencode(query)}",
            )
            return {
                "from_cache": result.from_cache,
                "update_time": result.update_time,
                "data": parse_rsshub_items(result.data),
            }
        except CacheOnlyMiss as exc:
            cache_only_miss = exc
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{base_url}: {exc}")
    if cache_only_miss is not None:
        raise cache_only_miss
    raise RuntimeError(f"RSSHub fetch failed for {route_name}; tried {len(errors)} instances")


def parse_rsshub_items(payload: Any, *, limit: int = 30) -> list[ListItem]:
    items: list[ListItem] = []
    for row in (payload or {}).get("items") or []:
        title = _normalize(row.get("title"))
        url = row.get("url")
        if not title or not _valid_url(url):
            continue
        content = row.get("content_text") or row.get("content_html") or ""
        items.append(
            ListItem(
                id=str(row.get("id") or url),
                title=title,
                desc=_clean_html(content),
                cover=_image(row.get("image")) or _image_from_html(row.get("content_html")),
                timestamp=_timestamp(row.get("date_published")),
                url=url,
                mobileUrl=url,
            )
        )
    if any(item.timestamp for item in items):
        items.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return items[:limit]


def _base_urls() -> list[str]:
    configured = config.SOURCE_RSSHUB_BASE_URLS
    configured_urls = [piece.strip() for piece in re.split(r"[\s,]+", configured) if piece.strip()]
    urls: list[str] = []
    for value in [*configured_urls, *DEFAULT_RSSHUB_BASE_URLS]:
        candidate = value if re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I) else f"https://{value}"
        normalized = candidate.rstrip("/")
        if normalized not in urls:
            urls.append(normalized)
    return urls


def _timestamp(value: Any) -> int | None:
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_html(value: Any) -> str | None:
    text = _normalize(BeautifulSoup(str(value or ""), "lxml").get_text(" ", strip=True))
    return text[:500] or None


def _image(value: Any) -> str | None:
    return value if _valid_url(value) else None


def _image_from_html(value: Any) -> str | None:
    image = BeautifulSoup(str(value or ""), "lxml").find("img")
    return _image(image.get("src") if image else None)


def _valid_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))

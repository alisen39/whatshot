from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import metrics, strip_html, text_or_none

ROUTE_NAME = "who-outbreaks"

SOURCE_LINK = "https://www.who.int/emergencies/disease-outbreak-news"
_API_URL = "https://www.who.int/api/news/diseaseoutbreaknews"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "WHO 疫情通报",
    "description": "世界卫生组织最新疾病暴发新闻（Disease Outbreak News）",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="最新通报",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=_API_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "$orderby": "PublicationDate desc",
            "$top": "50",
        },
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": SOURCE_LINK,
        },
    )

    items = (result.data or {}).get("value") or []
    items = sorted(items, key=lambda item: str(item.get("PublicationDate") or ""), reverse=True)
    data: list[NewsFlashItem] = []
    seen: set[str] = set()
    for item in items:
        title = text_or_none(item.get("Title"))
        item_id = text_or_none(item.get("DonId")) or text_or_none(item.get("Id"))
        detail_url = _detail_url(item.get("ItemDefaultUrl"), item_id)
        if not title or not item_id or not detail_url or item_id in seen:
            continue
        seen.add(item_id)

        summary = _plain_text(item.get("Summary"))
        overview = _plain_text(item.get("Overview"))
        content, content_status = _bounded_content(summary or overview or title)
        data.append(
            NewsFlashItem(
                id=item_id,
                title=title,
                content=content,
                summary=summary[:500] or None,
                contentStatus=content_status,
                source="WHO",
                metrics=metrics(
                    lastModified=text_or_none(item.get("LastModified")),
                    dateCreated=text_or_none(item.get("DateCreated")),
                ),
                timestamp=get_time(item.get("PublicationDate")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )

    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _detail_url(value: object, item_id: str | None) -> str | None:
    path = text_or_none(value)
    if path and path.startswith("http"):
        return path
    if path:
        normalized = path if path.startswith("/") else f"/{path}"
        if normalized.startswith("/item/"):
            normalized = normalized.removeprefix("/item")
        return f"{SOURCE_LINK}/item{normalized}"
    return f"{SOURCE_LINK}/item/{item_id}" if item_id else None


def _plain_text(value: object) -> str:
    return " ".join(strip_html(value).split())


def _bounded_content(value: str, limit: int = 1200) -> tuple[str, str]:
    if len(value) <= limit:
        return value, "full"
    return f"{value[:limit].rstrip()}…", "truncated"

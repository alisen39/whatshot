from __future__ import annotations

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "qwen-research"

SOURCE_LINK = "https://qwen.ai/research"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Qwen Research",
    "description": "Qwen 模型发布与研究更新",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="研究动态",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url="https://qwen.ai/api/v2/article/retrieval",
        no_cache=no_cache,
        response_type="json",
        params={
            "type": "qwen_ai",
            "language": "en-US",
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": SOURCE_LINK,
        },
    )

    articles = (result.data or {}).get("data", {}).get("articles") or []
    articles = sorted(
        articles,
        key=lambda item: get_time((item.get("extra") or {}).get("date")) or 0,
        reverse=True,
    )
    data: list[ListItem] = []
    for article in articles:
        path = (article.get("path") or "").strip()
        title = (article.get("title") or "").strip()
        if not path or not title:
            continue
        extra = article.get("extra") if isinstance(article.get("extra"), dict) else {}
        url = f"https://qwen.ai/research/{path}"
        data.append(
            ListItem(
                id=str(article.get("id") or f"qwen-research-{path}"),
                title=title,
                cover=extra.get("cover_small") or None,
                author=(extra.get("author") or "").strip() or None,
                desc=_summary(extra.get("introduction") or extra.get("description")),
                timestamp=get_time(extra.get("date")),
                url=url,
                mobileUrl=url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _summary(value: object) -> str | None:
    if not value:
        return None
    text = BeautifulSoup(str(value), "lxml").get_text(" ", strip=True)
    return text[:240] or None

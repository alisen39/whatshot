from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "anthropic-research"
SOURCE_LINK = "https://www.anthropic.com/research"
TYPE_MAP = {"research": "Research"}
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Anthropic Research",
    "description": "Anthropic 官方研究论文、模型安全与社会影响研究动态",
    "link": SOURCE_LINK,
    "params": {
        "type": {
            "name": "内容分类",
            "type": TYPE_MAP,
        }
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_type = request.query_params.get("type", "research")
    board_type = requested_type if requested_type in TYPE_MAP else "research"
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type=TYPE_MAP[board_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=SOURCE_LINK,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="text",
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_page(result.data),
    }


def _parse_page(html: str, *, limit: int = 30) -> list[NewsFlashItem]:
    soup = BeautifulSoup(html, "lxml")
    data: list[NewsFlashItem] = []
    seen_ids: set[str] = set()

    for link in soup.select("li > a[href^='/research/']"):
        date_node = link.find("time")
        spans = link.find_all("span")
        if date_node is None or len(spans) < 2:
            continue

        item_id = _research_path(link.get("href"))
        title = _text(spans[-1].get_text(" ", strip=True))
        category = _text(spans[0].get_text(" ", strip=True))
        timestamp = _publish_timestamp(date_node.get_text(" ", strip=True))
        if not item_id or not title or not category or timestamp is None:
            continue
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        detail_url = urljoin(SOURCE_LINK, item_id)
        data.append(
            NewsFlashItem(
                id=item_id,
                title=title,
                content=title,
                summary=title,
                contentStatus="summary",
                source="Anthropic",
                tags=[category],
                timestamp=timestamp,
                url=detail_url,
                mobileUrl=detail_url,
            )
        )

    if not data:
        raise RuntimeError("Anthropic Research page contained no publication rows")
    data.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return data[:limit]


def _research_path(value: object) -> str | None:
    href = str(value or "").strip()
    absolute = urljoin(SOURCE_LINK, href)
    parsed = urlparse(absolute)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.anthropic.com"
        or not parsed.path.startswith("/research/")
        or parsed.path == "/research/"
    ):
        return None
    return parsed.path


def _publish_timestamp(value: object) -> int | None:
    try:
        date = datetime.strptime(_text(value), "%b %d, %Y").replace(tzinfo=UTC)
    except ValueError:
        return None
    return int(date.timestamp() * 1000)


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


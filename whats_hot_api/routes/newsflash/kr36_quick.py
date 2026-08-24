from __future__ import annotations

import hashlib
import json
import re
import time
from urllib.parse import parse_qs, urlsplit

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get, post
from whats_hot_api.utils.newsflash import (
    compact_objects,
    compact_urls,
    content_status,
    metrics,
    strip_html,
    text_or_none,
    to_int,
    truthy_flag,
)

ROUTE_NAME = "36kr-quick"

TYPE_MAP: dict[str, str] = {
    "hot": "全部快讯",
    "quick": "全部快讯",
    "quick-hot": "热点快讯",
    "quick-stock": "股市快讯",
    "quick-company": "公司快讯",
    "quick-macro": "宏观快讯",
}
_CATALOG_IDS: dict[str, int] = {
    "hot": 0,
    "quick": 0,
    "quick-hot": 1,
    "quick-stock": 2,
    "quick-company": 3,
    "quick-macro": 4,
}
SOURCE_LINK = "https://www.36kr.com/newsflashes/catalog/0"
API_URL = "https://gateway.36kr.com/api/mis/nav/newsflash/list"

_GATEWAY_SIGN_PATTERN = re.compile(
    r"window\.__GATEWAY_SIGN__\s*=\s*[\"']([^\"']+)[\"']"
)
_SOURCE_PATTERN = re.compile(r"[（(]([^）)]+)[）)]\s*$")

_PAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_API_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://www.36kr.com",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "36氪快讯",
    "description": "36氪 24 小时快讯",
    "params": {
        "type": {
            "name": "快讯栏目",
            "type": TYPE_MAP,
        },
    },
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_type = request.query_params.get("type", "hot")
    selected_type = requested_type if requested_type in _CATALOG_IDS else "hot"
    list_data = await _get_list(_CATALOG_IDS[selected_type], no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type=TYPE_MAP[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(catalog_id: int, no_cache: bool) -> dict:
    page_url = f"https://www.36kr.com/newsflashes/catalog/{catalog_id}"
    page_result = await get(
        url=page_url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="text",
        headers=_PAGE_HEADERS,
    )
    nonce = _extract_nonce(page_result.data)
    signed_body, sign = _build_signed_request(nonce, catalog_id)
    result = await post(
        url=f"{API_URL}?sign={sign}",
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        body=signed_body,
        headers={**_API_HEADERS, "Referer": page_url},
        cache_key=f"{API_URL}?catalog={catalog_id}",
    )
    payload = _response_payload(result.data)
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_items(payload.get("itemList")),
    }


def _extract_nonce(html: object) -> str:
    match = _GATEWAY_SIGN_PATTERN.search(str(html or ""))
    if match is None:
        raise ValueError("36kr page did not provide a gateway signing nonce")
    return match.group(1)


def _build_signed_request(nonce: str, catalog_id: int) -> tuple[str, str]:
    body = {
        "nonce": nonce,
        "partner_id": "web",
        "timestamp": int(time.time() * 1000),
        "param": {
            "pageSize": 20,
            "pageEvent": 0,
            "pageCallback": "",
            "siteId": 1,
            "type": catalog_id,
            "platformId": 2,
        },
    }
    signed_body = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    sign = hashlib.md5(
        (signed_body + nonce).encode("utf-8"), usedforsecurity=False
    ).hexdigest()
    return signed_body, sign


def _response_payload(response: object) -> dict:
    if not isinstance(response, dict) or response.get("code") != 0:
        raise ValueError("36kr newsflash API returned an unsuccessful response")
    payload = response.get("data")
    if not isinstance(payload, dict) or not isinstance(payload.get("itemList"), list):
        raise TypeError("36kr newsflash API returned an invalid payload")
    return payload


def _parse_items(raw_items: object) -> list[NewsFlashItem]:
    if not isinstance(raw_items, list):
        return []

    data: list[NewsFlashItem] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        material = raw.get("templateMaterial")
        if not isinstance(material, dict):
            continue

        item_id = text_or_none(raw.get("itemId"))
        title = strip_html(material.get("widgetTitle"))
        content = strip_html(material.get("widgetContent")) or title
        if item_id is None or not content:
            continue

        detail_url = f"https://www.36kr.com/newsflashes/{item_id}"
        source_url = _decode_source_url(material.get("sourceUrlRoute"))
        source = _extract_source(content) or "36氪"
        data.append(
            NewsFlashItem(
                id=item_id,
                title=title or content[:60],
                content=content,
                contentStatus=content_status(content),
                source=source,
                isImportant=truthy_flag(material.get("hasRed")),
                images=compact_urls(material.get("widgetImage")),
                symbols=compact_objects(material.get("relevantProject")),
                metrics=metrics(
                    commentCount=to_int(material.get("statComment")),
                    itemType=to_int(raw.get("itemType")),
                    templateType=to_int(material.get("templateType")),
                ),
                timestamp=get_time(material.get("publishTime")),
                url=source_url or detail_url,
                mobileUrl=detail_url,
            )
        )
    return data


def _extract_source(content: str) -> str | None:
    match = _SOURCE_PATTERN.search(content)
    return text_or_none(match.group(1)) if match is not None else None


def _decode_source_url(route: object) -> str | None:
    value = text_or_none(route)
    if value is None:
        return None
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"}:
        return value
    candidate = text_or_none(parse_qs(parsed.query).get("url", [None])[0])
    if candidate and urlsplit(candidate).scheme in {"http", "https"}:
        return candidate
    return None

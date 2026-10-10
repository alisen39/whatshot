from __future__ import annotations

import html
import json
import re
from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "zhihu-extra"

type_map: dict[str, str] = {
    "hot-search": "热搜",
    "pin-news": "想法热榜（每日新闻）",
    "new-books": "新书抢鲜",
    "weekly": "知乎周刊",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "知乎",
    "description": "知乎热搜、想法每日新闻、书店新书与知乎周刊(热榜由 zhihu 路由提供)。",
    "link": "https://www.zhihu.com/",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

_PIN_SPECIAL_ID = "972884951192113152"
_LINKS = {
    "hot-search": "https://www.zhihu.com/search",
    "pin-news": f"https://www.zhihu.com/pin/special/{_PIN_SPECIAL_ID}",
    "new-books": "https://www.zhihu.com/pub/features/new",
    "weekly": "https://www.zhihu.com/pub/weekly",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "hot-search")
    if type_param not in type_map:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    list_data = await _HANDLERS[type_param](no_cache)
    return RouterData(
        **{**ROUTE_META, "link": _LINKS[type_param]},
        type=type_map[type_param],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


async def _get_json(url: str, no_cache: bool, params: dict | None = None) -> dict:
    result = await get(url=url, params=params, no_cache=no_cache, response_type="json")
    payload = result.data if isinstance(result.data, dict) else {}
    if "error" in payload:
        raise RuntimeError(f"Zhihu API error: {payload['error']}")
    if not payload:
        raise RuntimeError(f"Zhihu API returned no data ({url})")
    return {"payload": payload, "from_cache": result.from_cache, "update_time": result.update_time}


async def _get_hot_search(no_cache: bool) -> dict:
    fetched = await _get_json("https://www.zhihu.com/api/v4/search/hot_search", no_cache)
    items = []
    for q in fetched["payload"].get("hot_search_queries") or []:
        word = q.get("real_query") or q.get("query") or ""
        url = f"https://www.zhihu.com/search?type=content&q={quote(word)}"
        # 活动位的 redirect_link 是 https 网页,用它;普通词是 zhihu:// 协议,拼搜索页。
        # request_click_id 每次都变,去掉保证同一条的 url 稳定;query_id 是请求编号,不能作 id
        redirect = q.get("redirect_link") or ""
        if redirect.lower().startswith(("https://", "http://")):
            url = re.sub(r"[?&]request_click_id=[^&]*", "", redirect).rstrip("?&")
        items.append(
            ListItem(
                id=word,
                title=q.get("query") or word,
                url=url,
                mobileUrl=url,
                hot=q.get("hot"),
                badges=_search_badge(q),
            )
        )
    if not items:
        raise RuntimeError("Zhihu hot search returned no items")
    return {"from_cache": fetched["from_cache"], "update_time": fetched["update_time"], "data": items}


def _search_badge(q: dict) -> list[dict]:
    # 已知 label(hot/new)用固定文案,图标非 http(s) 链接时不带图;
    # 其他 label 只在有图标时透传 code,不造文案;两者都没有就是无标识
    label = str(q.get("label") or "").strip()
    icon = str(q.get("icon_url") or "").strip()
    icon = icon if icon.startswith(("http://", "https://")) else ""
    if label in _SEARCH_BADGE_LABELS:
        badge = {"text": _SEARCH_BADGE_LABELS[label]}
        if icon:
            badge["imageUrl"] = icon
        return [badge]
    if icon:
        return [{"code": label or None, "imageUrl": icon}]
    return []


_SEARCH_BADGE_LABELS = {"hot": "热", "new": "新"}


async def _get_pin_news(no_cache: bool) -> dict:
    # tophub 的"想法热榜"节点实际是想法专题"每日新闻"(api.zhihu.com/pins/special/...);
    # 原站 /api/v4/pins/hot_list 的想法热榜停在 2020-02,不是同一份数据。
    # limit=20 一页实际回 15 条左右(服务端过滤一部分),取第一页
    fetched = await _get_json(
        f"https://api.zhihu.com/pins/special/{_PIN_SPECIAL_ID}/moments",
        no_cache,
        params={"order_by": "newest", "reverse_order": 0, "limit": 20},
    )
    items = []
    for row in fetched["payload"].get("data") or []:
        pin = row.get("target") or row
        blocks = pin.get("content") or []
        text_html = next((b.get("content") or "" for b in blocks if b.get("type") == "text"), "")
        first_line = _text(re.split(r"<br\s*/?>", text_html)[0]) or (pin.get("excerpt_title") or "")
        author = (pin.get("author") or {}).get("name") or ""
        image = next((b.get("url") for b in blocks if b.get("type") == "image" and b.get("url")), None)
        pin_id = pin.get("id")
        if not pin_id or not first_line:
            continue
        # 想法没有标题字段,标题取正文第一行
        items.append(
            ListItem(
                id=str(pin_id),
                title=first_line,
                url=f"https://www.zhihu.com/pin/{pin_id}",
                mobileUrl=f"https://www.zhihu.com/pin/{pin_id}",
                author=author or None,
                cover=image,
                hot=pin.get("reaction_count"),
                desc=_text(text_html)[:500] or None,
                timestamp=get_time(pin.get("created")),
            )
        )
    if not items:
        raise RuntimeError("Zhihu pin daily-news returned no items")
    return {"from_cache": fetched["from_cache"], "update_time": fetched["update_time"], "data": items}


def _book_item(b: dict) -> ListItem:
    authors = b.get("authors")
    if isinstance(authors, list):
        authors = "、".join(a.get("name", "") for a in authors if a.get("name"))
    url = b.get("url") or f"https://www.zhihu.com/pub/book/{b['id']}"
    return ListItem(
        id=str(b["id"]),
        title=b.get("title") or "",
        url=url,
        mobileUrl=url,
        author=authors or None,
        cover=b.get("cover") or None,
        desc=(b.get("description") or "").strip() or None,
    )


async def _get_new_books(no_cache: bool) -> dict:
    fetched = await _get_json(
        "https://www.zhihu.com/api/v3/books/features/new", no_cache, params={"limit": 20, "offset": 0}
    )
    items = [_book_item(b) for b in fetched["payload"].get("data") or [] if isinstance(b, dict) and b.get("id")]
    if not items:
        raise RuntimeError("Zhihu new-books returned no items")
    return {"from_cache": fetched["from_cache"], "update_time": fetched["update_time"], "data": items}


async def _get_weekly(no_cache: bool) -> dict:
    result = await get(
        url="https://www.zhihu.com/pub/weekly", no_cache=no_cache, response_type="text"
    )
    matched = re.search(r'<textarea id="zh-data-state">(.*?)</textarea>', result.data, re.DOTALL)
    if not matched:
        raise RuntimeError("Zhihu weekly page has no zh-data-state (page structure changed)")
    state = json.loads(html.unescape(matched.group(1)))
    books = ((state.get("weekly") or {}).get("allWeekly") or {}).get("data") or []
    items = [_book_item(b) for b in books if isinstance(b, dict) and b.get("id")]
    if not items:
        raise RuntimeError("Zhihu weekly returned no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


_HANDLERS = {
    "hot-search": _get_hot_search,
    "pin-news": _get_pin_news,
    "new-books": _get_new_books,
    "weekly": _get_weekly,
}

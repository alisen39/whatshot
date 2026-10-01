"""V2EX 节点 / 首页 tab / 会员主题 —— 官方 Atom feed。

与既有 v2ex 路由的边界:v2ex 只有全站 hot / latest(API)、share(4 个节点 JSON feed 合并)、
nodes(节点目录);本路由补节点、tab、会员三个维度,互不重叠。

- 26 个子榜全部是 https://www.v2ex.com 下的官方 Atom feed,保留 feed 原顺序输出
  (节点 / 会员按发帖时间倒序;tab 按最后回复排序,与首页 /?tab= 列表逐条同序,
  不能按 published 重排),feed 给多少条输出多少条:
  - 节点 20 个:/feed/{节点}.xml(节点页 /go/{节点} 页头的 RSS 链接就是它)
  - 首页 tab 4 个:/feed/tab/{tab}.xml
  - 会员 2 个:/feed/member/{用户名}.xml(标题自带 "[节点] " 前缀,feed 原样保留)
- 反爬口径:V2EX 的 Cloudflare 对冒充浏览器的请求出 403 "Just a moment..." 挑战页;
  如实表明是程序(httpx 缺省 User-Agent 就是 python-httpx/<版本>)则直接 200。
  这里刻意不传 User-Agent,也不要为绕开挑战改成浏览器 UA。
- feed 链接形如 https://www.v2ex.com/t/<id>#reply<N>:url 去掉锚点(锚点每来一条回复就变),
  主题号作 id,锚点里的 N(回复数)作 hot;不匹配时 url 原样输出、hot 为空。
- /api/topics/show.json 只回 10 条、部分会员 404,不用 API。
"""

from __future__ import annotations

import re
from typing import NamedTuple

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "v2ex-feeds"

_BASE = "https://www.v2ex.com"


class _Feed(NamedTuple):
    kind: str  # 节点 / 首页 / 会员,拼进 type 标签
    name: str  # 中文名(节点名、tab 名、用户名)
    path: str  # feed 路径
    page: str  # 对应的原站页面,写进 RouterData.link


def _node(name: str, node: str) -> _Feed:
    return _Feed("节点", name, f"/feed/{node}.xml", f"{_BASE}/go/{node}")


def _tab(name: str, tab: str) -> _Feed:
    return _Feed("首页", name, f"/feed/tab/{tab}.xml", f"{_BASE}/?tab={tab}")


def _member(user: str) -> _Feed:
    return _Feed("会员", user, f"/feed/member/{user}.xml", f"{_BASE}/member/{user}/topics")


_FEEDS: dict[str, _Feed] = {
    "node-android": _node("Android", "android"),
    "node-apple": _node("Apple", "apple"),
    "node-blog": _node("Blog", "blog"),
    "node-dns": _node("DNS", "dns"),
    "node-openai": _node("OpenAI", "openai"),
    "node-v2ex": _node("V2EX", "v2ex"),
    "node-internet": _node("互联网", "internet"),
    "node-deals": _node("优惠信息", "deals"),
    "node-creditcard": _node("信用卡", "creditcard"),
    "node-create": _node("分享创造", "create"),
    "node-share": _node("分享发现", "share"),
    "node-ideas": _node("奇思妙想", "ideas"),
    "node-bb": _node("宽带症候群", "bb"),
    "node-cosub": _node("拼车", "cosub"),
    "node-car": _node("汽车", "car"),
    "node-shenzhen": _node("深圳", "shenzhen"),
    "node-hardware": _node("硬件", "hardware"),
    "node-programmer": _node("程序员", "programmer"),
    "node-qna": _node("问与答", "qna"),
    "node-random": _node("随想", "random"),
    "tab-deals": _tab("交易", "deals"),
    "tab-creative": _tab("创意", "creative"),
    "tab-tech": _tab("技术", "tech"),
    "tab-jobs": _tab("酷工作", "jobs"),
    "member-idblife": _member("idblife"),
    "member-qiayue": _member("qiayue"),
}

# 声明序第一个是默认榜
type_map: dict[str, str] = {key: f"{feed.kind} · {feed.name}" for key, feed in _FEEDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "V2EX",
    "description": "V2EX 官方 Atom feed：节点最新主题、首页 tab（技术、创意、交易、酷工作）与会员主题",
    "link": f"{_BASE}/",
    "params": {"type": {"name": "节点 / tab / 会员", "type": type_map}},
}

# 不传 User-Agent:httpx 缺省 UA 即 python-httpx/<版本>,V2EX 对程序 UA 直接 200
_HEADERS = {
    "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8",
}

_TOPIC_LINK = re.compile(r"^https://www\.v2ex\.com/t/(\d+)(?:#reply(\d+))?$")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", next(iter(type_map)))
    if type_param not in type_map:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    list_data = await _get_feed(_FEEDS[type_param], no_cache)
    return RouterData(
        **{**ROUTE_META, "link": _FEEDS[type_param].page},
        type=type_map[type_param],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_feed(feed: _Feed, no_cache: bool) -> dict:
    result = await get(
        url=f"{_BASE}{feed.path}",
        headers=_HEADERS,
        no_cache=no_cache,
        response_type="text",
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_atom(str(result.data), feed),
    }


def _parse_atom(xml: str, feed: _Feed) -> list[ListItem]:
    if "Just a moment" in xml[:2000]:
        raise RuntimeError(
            f"V2EX returned a Cloudflare challenge page (403 Just a moment...): {feed.path}. "
            "The request deliberately keeps the program UA; retry later instead of faking a browser UA"
        )
    soup = BeautifulSoup(xml, "xml")
    items: list[ListItem] = []
    for entry in soup.find_all("entry"):
        link = entry.find("link")
        href = str(link.get("href") or "").strip() if link else ""
        title = _tag_text(entry, "title")
        if not title or not href.startswith(("http://", "https://")):
            continue
        matched = _TOPIC_LINK.match(href)
        if matched:
            item_id, url = matched.group(1), f"{_BASE}/t/{matched.group(1)}"
            hot = int(matched.group(2)) if matched.group(2) is not None else None
        else:
            # 链接形态变了:按原样输出,不硬造 id / 回复数
            item_id, url, hot = href, href, None
        author = entry.find("author")
        author_name = author.find("name") if author else None
        content = _tag_text(entry, "content")
        items.append(
            ListItem(
                id=item_id,
                title=title,
                url=url,
                mobileUrl=url,
                hot=hot,
                author=author_name.get_text(" ", strip=True) if author_name else None,
                desc=_html_text(content),
                cover=_first_image(content),
                timestamp=get_time(_tag_text(entry, "published")),
            )
        )
    if not items:
        raise RuntimeError(
            f"V2EX feed parsed no entries (possible challenge page or feed layout change): {feed.path}"
        )
    return items


def _tag_text(node, name: str) -> str:
    tag = node.find(name)
    return tag.get_text(" ", strip=True) if tag else ""


def _html_text(fragment: str) -> str | None:
    text = BeautifulSoup(fragment or "", "lxml").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()[:500] or None


def _first_image(fragment: str) -> str | None:
    image = BeautifulSoup(fragment or "", "lxml").find("img")
    src = str(image.get("src") or "").strip() if image else ""
    return src if src.startswith(("http://", "https://")) else None

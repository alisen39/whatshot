"""Science 新闻(science.org 官方新闻 RSS,Latest News from Science Magazine)。

board_api 单元 ``tmp/board_api/science_news`` 的 1:1 迁移,证据见该目录 README 与 ``verify/``。
1 个子榜(hot),每次运行 1 个请求,不需要任何请求头(board_api header_matrix:science.org 在
Cloudflare 后面,HTML 页面对脚本返回 403 质询页,RSS 不质询——无 UA、curl、httpx 默认 UA
都返回 200):

- https://www.science.org/rss/news_current.xml(RSS 1.0 / RDF,最新 10 篇)

feed 本身不是严格按时间排的(board_api 曾按时间重排,10 条里 6 条换了位置),所以不用
utils.feed.parse_feed(它会按 timestamp 重排),单独按 RDF 文档原顺序解析(与 tophub 同序)。
cover 不补:配图写在 <enc:enclosure rdf:resource=…>,这些图片地址不带 science.org 的会话
cookie 一律 403,前端直接显示是裂图(推翻性验证发现),与 board_api 输出一致留空。
feed 没有 guid,id 用链接(DOI 在 dc:identifier,未采用,与 board_api 一致)。
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "science-news"
FEED_URL = "https://www.science.org/rss/news_current.xml"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Science 杂志",
    "description": "Science 杂志新闻频道最新报道（Latest News）",
    "link": "https://www.science.org/news",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
}


def _tag_text(node: Tag, *names: str) -> str:
    for name in names:
        child = node.find(name)
        if child is not None:
            return child.get_text(" ", strip=True)
    return ""


def parse_items(xml: str) -> list[ListItem]:
    """RDF <item> 按文档原顺序解析(顺序是原站编辑顺序,同一天内不严格按时间,不重排)。"""
    soup = BeautifulSoup(xml, "xml")
    if not soup.find_all("item"):
        raise RuntimeError("science.org RSS did not return any <item> (blocked or non-feed response)")
    items: list[ListItem] = []
    for node in soup.find_all("item"):
        # feed 没有 guid,id 用链接(与 board_api 一致);<title> 与 <dc:title> 内容相同,取排在前面的
        title = _tag_text(node, "title")
        url = _tag_text(node, "link")
        if not title or not url.startswith(("http://", "https://")):
            continue
        items.append(
            ListItem(
                id=url,
                title=title,
                url=url,
                mobileUrl=url,
                author=_tag_text(node, "dc:creator", "creator") or None,
                desc=_tag_text(node, "description") or None,  # 一句话导语,原样(不是 HTML)
                # enc:enclosure 的图片地址不带会话 cookie 一律 403(裂图),不补 cover
                timestamp=get_time(_tag_text(node, "dc:date", "date")),  # ISO 8601(UTC)→ 毫秒
            )
        )
    return items


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await get(
        url=FEED_URL,
        headers=_HEADERS,
        no_cache=no_cache,
        response_type="text",
        cache_key=ROUTE_NAME,
    )
    items = parse_items(str(result.data))
    if not items:
        # 错误页 / 空解析不静默降级为空榜
        raise RuntimeError(f"science-news feed returned no items ({FEED_URL})")
    return RouterData(
        **ROUTE_META,
        type="Latest News",
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )

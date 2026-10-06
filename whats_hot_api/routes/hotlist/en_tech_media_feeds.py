"""英文科技媒体分类 feed：Ars Technica、NVIDIA、InfoQ、MacRumors、MIT News、TechCrunch、
The Register、The Verge、WIRED（多站点，type=站点-栏目）。

迁移自 board_api en_tech_media_feeds 单元（23 个已完成榜，4 个停更榜不做；
VentureBeat 全站最新已因上游不可达下线，现存 22 个）：
- 21 个子榜是站点官方 RSS / Atom，用共享 ``parse_feed`` 解析（字段映射与 whatshot 一致：
  id 取 guid/id 缺省链接、desc 去 HTML 前 500 字、cover 依次 media:thumbnail / media:content /
  image / enclosure / 摘要首图）；feed 给多少条输出多少条（7~100 条不等），不截断。
  21 个 feed 都按发布时间倒序（board_api 证据：相邻逆序 0 处），parse_feed 的时间倒序重排
  与 feed 原顺序一致
- register-ai-ml 取栏目页 https://www.theregister.com/ai_ml/（页面标 "SOFTWARE > AI + ML"，
  服务端渲染）的文章卡片，见 ``_parse_register_cards``。不用旧 feed
  software/ai_ml/headlines.atom：它 302 到 api.theregister.com 的
  query=(tag:software AND tag:"ai and ml")，只收同时带两个标签的文章，最新一条停在
  2026-09-18，与栏目页不是同一份（board_api 推翻性验证）；/ai_ml/headlines.atom、
  /ai_ml/headlines.rss 都是 404，页面没有 alternate feed。栏目页翻页由前端脚本加载，
  只取服务端渲染的第 1 页（约 70 条）
- 请求口径照 board_api 证据：所有子榜统一带 Chrome UA（board_api 项目缺省 UA，没有为任何
  站点专门改）、Accept 按 feed / 栏目页区分
- 不做的 4 个榜：Ars Cardboard、MacRumors Mac / iPhone、WIRED Guides，原站已停更
  （board_api README；门槛：日更/周更/期刊 3 个月，其他栏目 12 个月）
- Ars Technica 的分类页 HTML 返回 405（AWS WAF 验证页），只用 feed
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import NamedTuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "en-tech-media-feeds"

_ARS = "Ars Technica"


class _Feed(NamedTuple):
    site: str  # 站点名，写进 RouterData.title
    column: str  # 栏目名，写进 RouterData.type
    url: str  # feed 地址（kind=register 时是栏目页）
    page: str  # 栏目页，写进 RouterData.link
    kind: str = "feed"  # feed：RSS / Atom；register：The Register 栏目页的文章卡片


def _ars(column: str, path: str) -> _Feed:
    return _Feed(_ARS, column, f"https://arstechnica.com/{path}/feed/", f"https://arstechnica.com/{path}/")


# 声明序第一个是默认榜；board_api 单元的缺省子榜是 ars-tech，保持一致
_FEEDS: dict[str, _Feed] = {
    "ars-tech": _ars("Tech", "gadgets"),
    "ars-apple": _ars("Apple", "apple"),
    "ars-biz-it": _ars("Biz & IT", "information-technology"),
    "ars-cars": _ars("Cars", "cars"),
    "ars-features": _ars("Features", "features"),
    "ars-gaming": _ars("Gaming", "gaming"),
    "ars-policy": _ars("Policy", "tech-policy"),
    "ars-science": _ars("Science", "science"),
    "ars-staff": _ars("Staff", "staff"),
    "nvidia-tech-blog": _Feed(
        "NVIDIA Developer", "NVIDIA Technical Blog", "https://developer.nvidia.com/blog/feed", "https://developer.nvidia.com/blog/"
    ),
    "infoq-ai-ml": _Feed(
        "InfoQ", "AI, ML & Data Engineering", "https://feed.infoq.com/ai-ml-data-eng/", "https://www.infoq.com/ai-ml-data-eng/"
    ),
    "macrumors-front": _Feed(
        "MacRumors", "Front Page", "https://feeds.macrumors.com/MacRumors-Front", "https://www.macrumors.com/"
    ),
    "mit-machine-learning": _Feed(
        "MIT News",
        "Machine learning",
        "https://news.mit.edu/topic/mitmachine-learning-rss.xml",
        "https://news.mit.edu/topic/machine-learning",
    ),
    "techcrunch-apple": _Feed(
        "TechCrunch", "Apple", "https://techcrunch.com/tag/apple/feed/", "https://techcrunch.com/tag/apple/"
    ),
    "techcrunch-apps": _Feed(
        "TechCrunch", "Apps", "https://techcrunch.com/category/apps/feed/", "https://techcrunch.com/category/apps/"
    ),
    "techcrunch-startups": _Feed(
        "TechCrunch", "Startups", "https://techcrunch.com/category/startups/feed/", "https://techcrunch.com/category/startups/"
    ),
    "techcrunch-venture": _Feed(
        "TechCrunch", "Venture", "https://techcrunch.com/category/venture/feed/", "https://techcrunch.com/category/venture/"
    ),
    # 栏目页 /ai_ml/（旧地址 /software/ai_ml/ 302 到这里）；旧 feed 与栏目页不是同一份，不用
    "register-ai-ml": _Feed(
        "The Register", "Software: AI + ML", "https://www.theregister.com/ai_ml/", "https://www.theregister.com/ai_ml/", "register"
    ),
    "verge-science": _Feed(
        "The Verge", "Science", "https://www.theverge.com/rss/science/index.xml", "https://www.theverge.com/science"
    ),
    "verge-tech": _Feed("The Verge", "Tech", "https://www.theverge.com/rss/tech/index.xml", "https://www.theverge.com/tech"),
    "wired-ai": _Feed(
        "WIRED", "Artificial Intelligence", "https://www.wired.com/feed/tag/ai/latest/rss", "https://www.wired.com/tag/artificial-intelligence/"
    ),
    "wired-business": _Feed(
        "WIRED", "Business", "https://www.wired.com/feed/category/business/latest/rss", "https://www.wired.com/category/business/"
    ),
}

type_map: dict[str, str] = {key: f"{feed.site} · {feed.column}" for key, feed in _FEEDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "英文科技媒体分类 feed",
    "description": "Ars Technica、TechCrunch、WIRED、The Verge、MacRumors、MIT News、NVIDIA、InfoQ、The Register 的官方分类 feed 与栏目页",
    "link": "https://arstechnica.com/",
    "params": {"type": {"name": "站点-栏目", "type": type_map}},
}

# board_api 全部请求都带项目缺省的 Chrome UA
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_FEED_ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.8"
_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", next(iter(type_map)))
    if board not in _FEEDS:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    feed = _FEEDS[board]
    if feed.kind == "register":
        fetched = await _fetch_text(feed.url, _HTML_ACCEPT, f"{ROUTE_NAME}:register-ai-ml", no_cache)
        items = _parse_register_cards(fetched["text"], feed.page)
    else:
        fetched = await _fetch_text(feed.url, _FEED_ACCEPT, f"{ROUTE_NAME}:{board}", no_cache)
        items = parse_feed(fetched["text"])
    if not items:
        # 严格拒绝空解析：错误页 / 空壳 / 结构变化不得静默降级为空榜
        raise RuntimeError(
            f"{ROUTE_NAME} board '{feed.site} · {feed.column}' parsed no items "
            f"(upstream changed or empty): {feed.url}"
        )
    return RouterData(
        **{**ROUTE_META, "title": feed.site, "link": feed.page},
        type=type_map[board],
        total=len(items),
        fromCache=fetched["from_cache"],
        updateTime=fetched["update_time"],
        data=items,
    )


async def _fetch_text(url: str, accept: str, cache_key: str, no_cache: bool) -> dict:
    result = await get(
        url=url,
        headers={"User-Agent": _BROWSER_UA, "Accept": accept},
        no_cache=no_cache,
        response_type="text",
        cache_key=cache_key,
    )
    return {"from_cache": result.from_cache, "update_time": result.update_time, "text": str(result.data)}


def _parse_register_cards(html_text: str, page: str) -> list[ListItem]:
    """The Register 栏目页主区（section#main）的文章卡片，按页面顺序，同一链接只留一次。

    卡片：a@href（文章链接）、a@data-k5a-url（/a/<文章号> 短链，与旧 feed 的 id 同一形式）、
    h2.headline、p.subtitle、time@datetime（itemprop=datePublished）、img@src。
    卡片上没有作者，author 为空；页脚的 "About Us" 等 article 不在 section#main 里。
    """
    soup = BeautifulSoup(html_text, "lxml")
    main = soup.select_one("section#main")
    if main is None:
        return []
    items: list[ListItem] = []
    seen: set[str] = set()
    for card in main.find_all("article"):
        link = card.find("a", href=True)
        headline = card.select_one("h2.headline")
        href = link.get("href") if link else None
        if not isinstance(href, str) or headline is None:
            continue
        title = re.sub(r"\s+", " ", headline.get_text(" ", strip=True))
        if not title:
            continue
        url = urljoin(page, href)
        if url in seen:
            continue
        seen.add(url)
        short = link.get("data-k5a-url")
        image = card.find("img")
        src = image.get("src") if image else None
        stamp = card.find("time")
        items.append(
            ListItem(
                id=short if isinstance(short, str) and short else url,
                title=title,
                url=url,
                mobileUrl=url,
                cover=src if isinstance(src, str) and src.startswith(("http://", "https://")) else None,
                desc=_subtitle_text(card.select_one("p.subtitle")),
                timestamp=_datetime_ms(stamp.get("datetime") if stamp else None),
            )
        )
    return items


def _subtitle_text(node: Tag | None) -> str | None:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else None


def _datetime_ms(value: object) -> int | None:
    """time@datetime（ISO 8601）→ 毫秒；解析不了留空。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return get_time(int(datetime.fromisoformat(value.strip()).timestamp()))
    except ValueError:
        return None

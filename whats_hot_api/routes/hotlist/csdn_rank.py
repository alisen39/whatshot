from __future__ import annotations

import json
import re
from urllib.parse import quote

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "csdn-rank"

# CSDN 分类热榜（tophub 的 19 个 CSDN 节点）。whatshot 既有 csdn 路由取的是不带
# child_channel 的综合热榜（hot-rank?page=0&pageSize=30），与本路由的 19 个子榜无重叠。
# 领域 child_channel 取自热榜页导航 rank_nav_list.json 的 type（导航名"结构与算法"的
# type 是"数据结构与算法"）；声明序第一个是缺省榜（ai，人工智能热榜），照 board_api 口径。
_CHANNELS: dict[str, tuple[str, str]] = {
    # board: (榜名, child_channel)
    "ai": ("人工智能热榜", "人工智能"),
    "c-cpp": ("C/C++热榜", "c/c++"),
    "javascript": ("Javascript热榜", "javascript"),
    "java": ("Java热榜", "java"),
    "php": ("PHP热榜", "php"),
    "python": ("Python热榜", "python"),
    "blockchain": ("区块链热榜", "区块链"),
    "bigdata": ("大数据热榜", "大数据"),
    "embedded": ("嵌入式热榜", "嵌入式"),
    "devtools": ("开发工具热榜", "开发工具"),
    "algorithm": ("数据结构与算法热榜", "数据结构与算法"),
    "test": ("测试热榜", "测试"),
    "game": ("游戏热榜", "游戏"),
    "mobile": ("移动开发热榜", "移动开发"),
    "network": ("网络热榜", "网络"),
    "ops": ("运维热榜", "运维"),
}

_BOARDS: dict[str, str] = {
    **{key: label for key, (label, _) in _CHANNELS.items()},
    "new-author": "新晋作者热文榜",
    "csdnnews": "CSDN资讯",
    "headlines": "今日头条热点",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "CSDN",
    "description": "CSDN 热榜页的领域内容榜、新晋作者榜，CSDN资讯账号文章与首页资讯头条。",
    "link": "https://blog.csdn.net/rank/list",
    "params": {
        "type": {
            "name": "榜单",
            "type": _BOARDS,
        },
    },
}

_HOT_RANK = "https://blog.csdn.net/phoenix/web/blog/hot-rank"
_NEW_AUTHOR = "https://blog.csdn.net/phoenix/web/v2/rank"
_NEWS_RSS = "https://blog.csdn.net/csdnnews/rss/list"
_HOME = "https://www.csdn.net/"

# 热榜页前端每页 25 条（rank 页 JS 的 pageSize:25），领域内不足 25 条时照原样输出
_PAGE_SIZE = 25
# 新晋作者榜页码从 1 开始（page=0 返回空 list），取第 1 页
_AUTHOR_PAGE = 1

_JSON_HEADERS = {"Accept": "application/json, text/plain, */*"}
_RSS_HEADERS = {"Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"}
_HTML_HEADERS = {"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}


def _rank_page_link(channel: str) -> str:
    return f"https://blog.csdn.net/rank/list/content?type={quote(channel, safe='')}"


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", "ai")
    if board not in _BOARDS:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    if board in _CHANNELS:
        label, channel = _CHANNELS[board]
        list_data = await _get_hot_rank(channel, no_cache)
        link = _rank_page_link(channel)
    elif board == "new-author":
        label, list_data, link = "新晋作者热文榜", await _get_new_author(no_cache), "https://blog.csdn.net/rank/list/author"
    elif board == "csdnnews":
        label, list_data, link = "CSDN资讯", await _get_news_rss(no_cache), "https://blog.csdn.net/csdnnews"
    else:
        label, list_data, link = "今日头条热点", await _get_headlines(no_cache), _HOME
    return RouterData(
        **{**ROUTE_META, "link": link},
        type=label,
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_json(url: str, referer: str, no_cache: bool) -> tuple[dict, dict]:
    """取热榜页背后的 JSON 接口；业务壳（code != 200）按错误处理，不静默降级。

    csdn.net 有频率型 WAF（连续请求十几次后返回 HTTP 521 JS 挑战页）；Core 侧不做
    跨请求限速，靠热榜缓存与调用方节奏控制频率。"""
    result = await get(url=url, headers={**_JSON_HEADERS, "Referer": referer}, no_cache=no_cache)
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("code") != 200:
        raise RuntimeError(
            f"CSDN hot-rank API returned code={payload.get('code')} for {url.rsplit('?', 1)[0]}"
        )
    return result, payload


async def _get_hot_rank(channel: str, no_cache: bool) -> dict:
    # 领域热榜：页面缺省 page=0、type 为空字符串（综合排序）；接口没有发布时间
    # （period 实测全为 null），timestamp 留空
    url = f"{_HOT_RANK}?page=0&pageSize={_PAGE_SIZE}&child_channel={quote(channel, safe='')}&type="
    result, payload = await _get_json(url, _rank_page_link(channel), no_cache)
    rows = payload.get("data")
    # 壳变形按抓取失败处理,不是调用方类型错
    if not isinstance(rows, list):
        raise RuntimeError("CSDN hot-rank response data is not a list (feed changed)")  # noqa: TRY004
    items = []
    for row in rows:
        link = row.get("articleDetailUrl")
        if not row.get("productId") or not row.get("articleTitle") or not link:
            continue
        pics = row.get("picList") or []
        items.append(
            ListItem(
                id=row["productId"],
                title=str(row["articleTitle"]).strip(),
                url=link,
                mobileUrl=link,
                hot=row.get("hotRankScore"),
                cover=pics[0] if pics else None,
                author=row.get("nickName"),
            )
        )
    if not items:
        raise RuntimeError(f"CSDN {channel} hot rank returned no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


async def _get_new_author(no_cache: bool) -> dict:
    url = f"{_NEW_AUTHOR}?page={_AUTHOR_PAGE}&pageSize={_PAGE_SIZE}&rankType=new_author"
    result, payload = await _get_json(url, "https://blog.csdn.net/rank/list/author", no_cache)
    data = payload.get("data")
    rows = data.get("list") if isinstance(data, dict) else None
    # 壳变形按抓取失败处理,不是调用方类型错
    if not isinstance(rows, list):
        raise RuntimeError("CSDN new-author response has no data.list (feed changed)")  # noqa: TRY004
    items = []
    for row in rows:
        link = row.get("articleDetailUrl")
        if not row.get("articleId") or not row.get("articleTitle") or not link:
            continue
        items.append(
            ListItem(
                id=row["articleId"],
                title=str(row["articleTitle"]).strip(),
                url=link,
                mobileUrl=link,
                hot=row.get("hotRankScore"),
                author=row.get("nickName"),
            )
        )
    if not items:
        raise RuntimeError("CSDN new author rank returned no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


async def _get_news_rss(no_cache: bool) -> dict:
    # csdnnews 官方 RSS（blog.csdn.net 301 到 rss.csdn.net/csdnnews/rss/map，客户端自动跟随）
    result = await get(url=_NEWS_RSS, headers=_RSS_HEADERS, response_type="text", no_cache=no_cache)
    items = parse_feed(result.data)
    if not items:
        raise RuntimeError("CSDN news RSS returned no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


async def _get_headlines(no_cache: bool) -> dict:
    result = await get(url=_HOME, headers=_HTML_HEADERS, response_type="text", no_cache=no_cache)
    items = _parse_headlines(result.data)
    if not items:
        raise RuntimeError("CSDN home headlines returned no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


def _article_id(url: str) -> str | None:
    matched = re.search(r"/article/details/(\d+)", url)
    return matched.group(1) if matched else None


def _parse_headlines(page: str) -> list[ListItem]:
    """首页"资讯头条"区块：div.home-info 里轮播（home-info-banner）与文字列表
    （home-info-headlines）的链接，按页面顺序；标题、封面、作者、摘要从同页内嵌的
    www-info-list-home 按文章号补齐。桌面版显示前 10 条、占广告位时前 9 条，
    广告格的 <a> 没有 href，天然被 a[href] 过滤。内嵌数据的 editTime / timestamp
    是编辑把文章放进列表的时间，不是内容发布时间，timestamp 留空。"""
    items: list[ListItem] = []
    embedded = _embedded_list(page)
    by_id = {str(v.get("itemId")): v for v in embedded if isinstance(v, dict)}
    block = BeautifulSoup(page, "lxml").select_one("div.home-info")
    if block is None:
        raise RuntimeError("CSDN home page has no 'home-info' block (page structure changed)")
    seen: set[str] = set()
    for anchor in block.select("div.home-info-banner a[href], div.home-info-headlines a[href]"):
        link = str(anchor.get("href") or "").strip()
        if not link.startswith("http") or link in seen:
            continue
        seen.add(link)
        article_id = _article_id(link)
        info = by_id.get(article_id or "", {})
        title = str(info.get("title") or anchor.get_text(" ", strip=True) or "").strip()
        if not title:
            continue
        items.append(
            ListItem(
                id=article_id or link,
                title=title,
                url=link,
                mobileUrl=link,
                cover=info.get("cover"),
                author=info.get("nickname"),
                desc=info.get("summary"),
            )
        )
    return items


def _embedded_list(page: str) -> list:
    matched = re.search(r"window\.__INITIAL_STATE__\s*=\s*", page)
    if not matched:
        return []
    try:
        state, _ = json.JSONDecoder().raw_decode(page[matched.end():])
    except ValueError:
        return []
    if not isinstance(state, dict):
        return []
    page_data = state.get("pageData") or {}
    data = page_data.get("data") if isinstance(page_data, dict) else None
    info = (data or {}).get("www-info-list-home") if isinstance(data, dict) else None
    rows = info.get("list") if isinstance(info, dict) else None
    return rows if isinstance(rows, list) else []

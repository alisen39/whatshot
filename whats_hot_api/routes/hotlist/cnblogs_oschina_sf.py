"""博客园 / 开源中国两站的 8 个榜(多子榜路由)。

与 whatshot 既有路由无重叠:whatshot 此前没有这三个站点的路由。子榜与口径
照 board_api 证据(tmp/board_api/cnblogs_oschina_sf):

- 博客园:10 天推荐 / 48 小时评论 / 48 小时阅读排行、候选区、精华区取服务端渲染的
  HTML(#post_list article.post-item);首页推荐取官方 Atom(feed.cnblogs.com/blog/sitehome/rss,
  与首页 HTML 同一列表同序,标题带" - 作者")。候选区、精华区的官方 RSS 返回 HTTP 500,不能用。
  48 小时评论排行周末常为空:页面显示"当前博文列表为空!"时输出 0 条并带 message,
  既没有条目也没有该提示时报错(页面结构变了)。
- 开源中国:社区推荐 / 最新软件取
  /project 页(前端渲染)背后的 GET apiv1.oschina.net/oschinapi/project/query,
  onlyRecommend=true|false 区分两个榜,业务码 code!=200 按业务错误壳拒绝。

开源中国新闻 / 热门资讯与 SegmentFault 的 5 个榜已因上游不可达下线。

id 一律用上游稳定标识(文章/项目 id,禁名次);timestamp 统一毫秒
(博客园、开源中国软件库是北京时间字符串,由 get_time 归一化)。
UA/Referer 非必需(实测缺省 UA、不带 Referer 结果相同),这里按页面口径带上开源中国
软件库接口的 Referer/Origin。
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "cnblogs-oschina-sf"

# 子榜键 -> (榜名, 站点名, 取数方式, 地址或 onlyRecommend 取值)。
# cnblogs-sitehome 是 board_api 的缺省榜,声明序第一个即默认榜。
_BOARDS: dict[str, tuple[str, str, str, str]] = {
    "cnblogs-sitehome": ("首页推荐", "博客园", "feed", "https://feed.cnblogs.com/blog/sitehome/rss"),
    "cnblogs-topdiggs": ("10天推荐排行", "博客园", "cnblogs_html", "https://www.cnblogs.com/aggsite/topdiggs"),
    "cnblogs-topcommented48h": (
        "48小时评论排行", "博客园", "cnblogs_html", "https://www.cnblogs.com/aggsite/topcommented48h",
    ),
    "cnblogs-topviews": ("48小时阅读排行", "博客园", "cnblogs_html", "https://www.cnblogs.com/aggsite/topviews"),
    "cnblogs-candidate": ("候选区", "博客园", "cnblogs_html", "https://www.cnblogs.com/candidate/"),
    "cnblogs-pick": ("精华区", "博客园", "cnblogs_html", "https://www.cnblogs.com/pick/"),
    "oschina-project-recommend": ("社区推荐软件", "开源中国", "osc_project", "true"),
    "oschina-project-latest": ("社区最新软件", "开源中国", "osc_project", "false"),
}

type_map: dict[str, str] = {key: label for key, (label, _, _, _) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "博客园 / 开源中国",
    "description": "博客园排行、候选区、精华区、首页推荐;开源中国软件库。",
    "link": "https://www.cnblogs.com/",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

DEFAULT_TYPE = next(iter(type_map))

_FEED_HEADERS = {
    "Accept": "application/atom+xml, application/rss+xml, application/xml;q=0.9, */*;q=0.8",
}
# feed 子榜对应的原站页面(响应 link 用;board_api 同口径)
_FEED_PAGE_LINK = {
    "cnblogs-sitehome": "https://www.cnblogs.com/",
}
# 博客园列表每条的计数按榜单取:推荐排行、候选区、精华区取推荐数,评论排行取评论数,阅读排行取阅读数
_CNB_HOT_LABEL = {
    "cnblogs-topdiggs": "推荐",
    "cnblogs-topcommented48h": "评论",
    "cnblogs-topviews": "阅读",
    "cnblogs-candidate": "推荐",
    "cnblogs-pick": "推荐",
}
_CNB_EMPTY = "当前博文列表为空"

_OSC_PROJECT_API = "https://apiv1.oschina.net/oschinapi/project/query"
# /project 页前端一页 10 条(pageSize:10,滚动加载 pageNum+=1);缺省值照页面 JS
_OSC_PROJECT_PARAMS_BASE: dict[str, Any] = {
    "languageId": "",
    "osId": "",
    "orderBy": "",
    "pageNum": 1,
    "pageSize": 10,
}
_OSC_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.oschina.net/",
    "Origin": "https://www.oschina.net",
}

async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", DEFAULT_TYPE)
    if type_param not in _BOARDS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    label, site, mode, target = _BOARDS[type_param]
    list_data = await _get_list(type_param, label, site, mode, target, no_cache)
    return RouterData(
        **{**ROUTE_META, "title": site, "link": list_data["link"]},
        type=label,
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
        message=list_data.get("message"),
    )


async def _get_list(
    board: str, label: str, site: str, mode: str, target: str, no_cache: bool
) -> dict:
    message: str | None = None
    if mode == "feed":
        result = await get(url=target, headers=_FEED_HEADERS, response_type="text", no_cache=no_cache)
        items = parse_feed(result.data)
        link = _FEED_PAGE_LINK[board]
    elif mode == "cnblogs_html":
        result = await get(url=target, response_type="text", no_cache=no_cache)
        items, message = _cnblogs_items(result.data, board)
        link = target
    else:  # osc_project
        result = await get(
            url=_OSC_PROJECT_API,
            params={**_OSC_PROJECT_PARAMS_BASE, "onlyRecommend": target},
            headers=_OSC_HEADERS,
            response_type="json",
            no_cache=no_cache,
        )
        items = _osc_project_items(result.data)
        link = "https://www.oschina.net/project"
    if not items and message is None:
        raise RuntimeError(f"{site} {label} returned no items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
        "link": link,
        "message": message,
    }


def _cnblogs_items(page: str, board: str) -> tuple[list[ListItem], str | None]:
    """解析博客园 #post_list article.post-item;一页 20 条,按页面顺序输出。"""
    hot_label = _CNB_HOT_LABEL[board]
    items: list[ListItem] = []
    for article in BeautifulSoup(page, "lxml").select("#post_list article.post-item"):
        anchor = article.select_one("a.post-item-title")
        if anchor is None or not anchor.get("href"):
            continue
        link = str(anchor["href"]).strip()
        # 计数按钮 title 形如"评论 11""推荐 40""阅读 1673"
        counts: dict[str, int | None] = {}
        for btn in article.select("footer a.post-meta-item"):
            label_text, _, number = str(btn.get("title") or "").partition(" ")
            counts[label_text] = _int(number)
        author = article.select_one("a.post-item-author")
        summary = article.select_one("p.post-item-summary")
        date = article.select_one("footer span.post-meta-item > span")
        cover = article.select_one("figure img")
        items.append(
            ListItem(
                id=str(article.get("data-post-id") or link),
                title=anchor.get_text(" ", strip=True),
                url=link,
                mobileUrl=link,
                hot=counts.get(hot_label),
                cover=str(cover["src"]) if cover and cover.get("src") else None,
                author=author.get_text(" ", strip=True) if author else None,
                desc=summary.get_text(" ", strip=True) if summary else None,
                # 页面时间是北京时间,如"2026-09-21 08:50"
                timestamp=get_time(date.get_text(strip=True)) if date else None,
            )
        )
    message = None
    if not items:
        if _CNB_EMPTY not in page:
            raise RuntimeError("cnblogs list page has no post-item and no empty marker (page changed)")
        # 48 小时评论排行周末常为空;原站明示列表为空是合法态,输出 0 条并说明
        message = "博客园当前列表为空(页面显示「当前博文列表为空!」);48 小时评论排行在周末常为空,工作日再看"
    return items, message


def _osc_project_items(payload: Any) -> list[ListItem]:
    """开源中国软件库接口;业务码 code!=200 或 result 不是列表按业务错误壳拒绝。"""
    if (
        not isinstance(payload, dict)
        or payload.get("code") != 200
        or not isinstance(payload.get("result"), list)
    ):
        raise RuntimeError(f"oschina project/query returned error shell: {str(payload)[:200]}")
    items: list[ListItem] = []
    for row in payload["result"]:
        if not isinstance(row, dict):
            continue
        ident = str(row.get("ident") or "").strip()
        name = str(row.get("name") or "").strip()
        if not ident or not name:
            continue
        # 标题与现在的软件库页面组件一致:"软件名 - 一句话介绍"
        tagline = str(row.get("title") or "").strip()
        title = f"{name} - {tagline}" if tagline else name
        link = f"https://www.oschina.net/p/{ident}"
        items.append(
            ListItem(
                id=str(row.get("id") or ident),
                title=title,
                url=link,
                mobileUrl=link,
                hot=row.get("viewCount"),
                cover=row.get("imgUrl") or None,
                desc=str(row.get("detail") or "").strip() or None,
                # createTime 是收录时间,北京时间,如"2026-09-03 15:47:18"
                timestamp=get_time(str(row.get("createTime") or "")) or None,
            )
        )
    return items


def _int(text: str | None) -> int | None:
    matched = re.search(r"\d+", text or "")
    return int(matched.group()) if matched else None

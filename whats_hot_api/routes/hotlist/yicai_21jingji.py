"""第一财经与 21 财经多榜路由（board_api 单元 yicai_21jingji 的迁移）。

数据口径全部来自 board_api 证据（tmp/board_api/yicai_21jingji，2026-09-30 定稿）：

第一财经（www.yicai.com，公开、无签名、无 cookie，httpx 缺省 UA 即可），每个子榜 1 个请求
- 四个"X排行"周榜：``/api/ajax/getranklistbykeys?keys=<newsRank|videoRank|imageRank|liveRank>``
  取 ``week``（每榜 10 条）。频道页右栏"X排行"块由 common.js 用这个接口渲染，缺省显示
  "周榜"tab；条目只有 id、标题、链接，``timestamp``、``hot`` 留空。
- 头条：首页"头条 / 最新 / 最热"三个 tab 里的"头条"（``#headlist``），首屏 30 条是页面
  内嵌 ``var headList`` 的前 30 条（index.js 按 30 条切片）。tophub 这个节点抓的其实是
  "最热"tab（快照里有旧文），board_api 按"榜名与内容不符时按榜名取原站列表"取"头条"。
- 汽车新闻：频道页 ``/news/automobile/`` 内嵌 ``var firstlist`` 前 25 条（newslist.js 按
  25 条切片）。
- 头条 / 汽车新闻的 ``mobileUrl``：按原站 ``assets/gotoMurl.js`` 的规则（手机访问电脑版
  页面时把"协议 + 域名"换成 ``https://m.yicai.com/``、路径不变）由 url 生成。不用内嵌
  数据的 ``ShareUrl``：首页普通稿、视频、图集的 ShareUrl 为空，会员稿给的
  ``m.yicai.com/news/<id>.html`` 实测 404。

21 财经（m.21jingji.com 手机站接口），每个子榜 2 个请求
- 先 ``POST /reader/cbhChannelAuth`` 取 token（不用登录、无请求体，返回 ``Bearer`` JWT，
  有效期 120 秒），再带 ``Authorization: <token>`` 请求列表第 1 页（20 行）。
  手机站对程序 UA 返回 ``493 JFE Forbidden``，必须带浏览器 UA；不带 Authorization 或
  token 错误返回 404 页。token 在 Core 侧缓存 60 秒（页面 app.js 同款缓存期，
  短于 120 秒有效期）。
- 新健康：``/channel/healthnews?short=healthnews``；热门：手机站首页第一个 tab "热点"
  ``/reader/index?more=1``（"热门"对应"热点"是 board_api 的推断，依据见其 README）。
- 列表里 ``isAD=1`` 的是广告位（手机站页面渲染时不读 isAD，没有"广告"标记），不算条目；
  专题行（``type=link``，指向 /jujiao/getList?ztid=）是页面上的正常条目，保留，
  id 加前缀 ``zt``（专题与文章是两套编号）。
- ``timestamp`` 取 ``updatetime``：栏目接口里是 Unix 秒、热点接口里是"YYYY-MM-DD HH:MM"
  字符串，两种都认；列表显示的"N分钟前"就是按它算的。
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get, post

ROUTE_NAME = "yicai-21jingji"

_YICAI = "https://www.yicai.com"
_M21 = "https://m.21jingji.com"

# 子榜 -> (中文名, 排行 key)。声明序第一个是默认榜（与 board_api DEFAULT_TYPE 一致）。
_YICAI_RANK_BOARDS: dict[str, tuple[str, str]] = {
    "yicai-news-rank": ("第一财经 · 新闻排行周榜", "newsRank"),
    "yicai-video-rank": ("第一财经 · 视频排行周榜", "videoRank"),
    "yicai-image-rank": ("第一财经 · 图集排行周榜", "imageRank"),
    "yicai-live-rank": ("第一财经 · 大直播排行周榜", "liveRank"),
}

# 子榜 -> (中文名, 内嵌变量名, 页面地址, 首屏条数)。
# 首页"头条"30 条（index.js 按 30 切片）、汽车频道 25 条（newslist.js 按 25 切片）。
_YICAI_EMBEDDED_BOARDS: dict[str, tuple[str, str, str, int]] = {
    "yicai-headline": ("第一财经 · 头条", "headList", f"{_YICAI}/", 30),
    "yicai-auto": ("第一财经 · 汽车新闻", "firstlist", f"{_YICAI}/news/automobile/", 25),
}

# 子榜 -> (中文名, 手机站列表接口路径与页面同款标记)
_M21_BOARDS: dict[str, tuple[str, str]] = {
    "21jingji-health": ("21财经 · 新健康", "/channel/healthnews?short=healthnews"),
    "21jingji-hot": ("21财经 · 热门（手机站热点）", "/reader/index?more=1"),
}

type_map: dict[str, str] = {
    "yicai-news-rank": "第一财经 · 新闻排行周榜",
    "yicai-video-rank": "第一财经 · 视频排行周榜",
    "yicai-image-rank": "第一财经 · 图集排行周榜",
    "yicai-live-rank": "第一财经 · 大直播排行周榜",
    "yicai-headline": "第一财经 · 头条",
    "yicai-auto": "第一财经 · 汽车新闻",
    "21jingji-health": "21财经 · 新健康",
    "21jingji-hot": "21财经 · 热门（手机站热点）",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "第一财经与 21 财经",
    "description": (
        "第一财经新闻 / 视频 / 图集 / 大直播排行周榜、首页头条、汽车新闻；"
        "21 财经新健康、手机站热点"
    ),
    "link": "https://www.yicai.com/",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

_DEFAULT_TYPE = "yicai-news-rank"

_M21_TOKEN_URL = f"{_M21}/reader/cbhChannelAuth"
# token 有效期 120 秒（exp - iat）；缓存 60 秒与页面 app.js 同款缓存期，不会发过期 token
_M21_TOKEN_TTL_SECONDS = 60
# 21 财经手机站对程序 UA 返回 493 JFE Forbidden，必须带浏览器 UA（board_api 实测）
_M21_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{_M21}/",
}


def _yicai_mobile_url(url: str) -> str:
    """原站 gotoMurl.js 的规则：把"协议 + 域名"换成 https://m.yicai.com，路径不变。"""
    return re.sub(r"^https?://[^/]+/", "https://m.yicai.com/", url)


def _embedded_array(html: str, var: str) -> list[Any]:
    """取页面内嵌的 ``var <名字> = [...]``。"""
    start = html.find(f"var {var}")
    bracket = html.find("[", start) if start >= 0 else -1
    if bracket < 0:
        raise RuntimeError(f"Yicai page has no 'var {var}' (page changed)")
    value, _ = json.JSONDecoder().raw_decode(html[bracket:])
    if isinstance(value, list):
        return value
    raise RuntimeError(f"Yicai 'var {var}' is not a list (page changed)")


async def _get_yicai_rank(label: str, key: str, no_cache: bool) -> dict:
    result = await get(
        url=f"{_YICAI}/api/ajax/getranklistbykeys?keys={key}",
        no_cache=no_cache,
        response_type="json",
        cache_key=f"yicai-21jingji:yicai-rank:{key}",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    ranking = payload.get(key)
    rows = ranking.get("week") if isinstance(ranking, dict) else None
    items: list[ListItem] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        news_id = row.get("NewsID")
        link = row.get("url") or ""
        title = str(row.get("NewsTitle") or "").strip()
        if not news_id or not link or not title:
            continue
        url = urljoin(_YICAI, str(link))
        # 排行条目只有 id、标题、链接，没有时间和热度
        items.append(ListItem(id=news_id, title=title, url=url, mobileUrl=url))
    if not items:
        raise RuntimeError(f"Yicai {label} rank board returned no items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
        "message": None,
    }


async def _get_yicai_embedded(label: str, var: str, page_url: str, limit: int, no_cache: bool) -> dict:
    result = await get(
        url=page_url,
        no_cache=no_cache,
        response_type="text",
        cache_key=f"yicai-21jingji:yicai-page:{var}",
    )
    rows = _embedded_array(str(result.data), var)
    items: list[ListItem] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        news_id = row.get("NewsID")
        link = row.get("url") or ""
        title = str(row.get("NewsTitle") or "").strip()
        if not news_id or not link or not title:
            continue
        url = urljoin(_YICAI, str(link))
        items.append(
            ListItem(
                id=news_id,  # 会员稿的 NewsID 与链接里的 id 不同，照内嵌数据取 NewsID
                title=title,
                url=url,
                mobileUrl=_yicai_mobile_url(url),  # gotoMurl.js 规则，不用内嵌 ShareUrl
                hot=row.get("NewsHot") or None,
                cover=row.get("originPic") or row.get("NewsThumbs") or None,
                author=row.get("NewsAuthor") or None,
                desc=row.get("NewsNotes") or None,
                timestamp=get_time(row.get("CreateDate")),  # 页面显示的时间就是 CreateDate
            )
        )
    if not items:
        raise RuntimeError(f"Yicai {label} board returned no items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
        "message": None,
    }


async def _get_m21_token(no_cache: bool) -> str:
    result = await post(
        url=_M21_TOKEN_URL,
        headers=dict(_M21_HEADERS),
        no_cache=no_cache,
        response_type="json",
        ttl=_M21_TOKEN_TTL_SECONDS,
        cache_key="yicai-21jingji:m21-token",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("status") != 1 or not payload.get("token"):
        raise RuntimeError(f"21jingji token endpoint returned no token: {str(payload)[:200]}")
    return str(payload["token"])


async def _get_m21(board: str, label: str, path_and_marker: str, no_cache: bool) -> dict:
    token = await _get_m21_token(no_cache)
    result = await get(
        # 与手机站 app.js getNews 拼法一致：<栏目接口>?short=…|more=1&type=json&page=N
        url=f"{_M21}{path_and_marker}&type=json&page=1",
        headers={**_M21_HEADERS, "Authorization": token, "Content-Type": "application/json"},
        no_cache=no_cache,
        response_type="json",
        cache_key=f"yicai-21jingji:m21:{board}",
    )
    # 不带 Authorization / token 错误时接口返回 404 HTML 页
    rows = result.data if isinstance(result.data, list) else None
    if rows is None:
        raise RuntimeError(f"21jingji {label} endpoint did not return a list: {str(result.data)[:120]}")
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("isAD"):
            # 原站标的广告位（车贷推广、活动征集页、品牌软文），不算条目
            continue
        link = str(row.get("url") or "").strip()
        title = str(row.get("title") or "").strip()
        if not link or not title or link in seen:
            continue
        seen.add(link)
        is_topic = row.get("type") == "link" or row.get("model") == "zhuanti"
        items.append(
            ListItem(
                # 专题 id 与文章 id 是两套编号，加前缀避免撞号
                id=f"zt{row.get('id')}" if is_topic else (row.get("id") or link),
                title=title,
                url=link,
                mobileUrl=link,  # 本身就是手机站链接
                cover=row.get("listthumb") or row.get("list_thumb") or row.get("thumb") or None,
                author=row.get("author") or None,  # 记者署名；mp.name 是发布账号，不当作者
                desc=row.get("description") or None,
                # updatetime：栏目接口是 Unix 秒、热点接口是"YYYY-MM-DD HH:MM"，两种都认
                timestamp=get_time(row.get("updatetime")),
            )
        )
    if not items:
        raise RuntimeError(f"21jingji {label} board returned no items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
        "message": None,
    }


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", _DEFAULT_TYPE)
    if type_param not in type_map:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    if type_param in _YICAI_RANK_BOARDS:
        label, key = _YICAI_RANK_BOARDS[type_param]
        list_data = await _get_yicai_rank(label, key, no_cache)
    elif type_param in _YICAI_EMBEDDED_BOARDS:
        label, var, page_url, limit = _YICAI_EMBEDDED_BOARDS[type_param]
        list_data = await _get_yicai_embedded(label, var, page_url, limit, no_cache)
    else:
        label, path_and_marker = _M21_BOARDS[type_param]
        list_data = await _get_m21(type_param, label, path_and_marker, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[type_param],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
        message=list_data.get("message"),
    )

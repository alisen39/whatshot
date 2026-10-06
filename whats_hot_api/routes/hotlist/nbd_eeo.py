"""每经网与经济观察网多榜路由（board_api 单元 nbd_eeo 的迁移）。

数据口径全部来自 board_api 证据（tmp/board_api/nbd_eeo，2026-09-30 定稿）：

每经网（www.nbd.com.cn，公开、无签名、无 cookie，httpx 缺省 UA 即可）
- 7 个栏目都是服务端渲染的栏目页 ``/columns/<id>/``：``div.g-list-text div.m-list``
  按天分组（``p.u-channeltime`` 是日期），每条 ``li.u-news-title`` 是链接 + 时刻。
  一页 50 条（重磅原创 20 条），照页面顺序输出；时间取栏目页的日期 + 时刻
  （链接里的日期是建稿日期，不一定是发布日期）。
- 带 ``news-title-a`` 样式的链接文字被原站截短，不是完整标题。补全：取同一栏目的
  手机版 ``m.nbd.com.cn/columns/<id>/``（每页 20 条、标题完整），最多翻 3 页，
  按文章 id 对上且完整标题以截短文字开头才替换；手机版对不上的（如栏目 332 的
  手机版是另一份旧列表）再取文章页 ``<title>``（最多 5 篇），仍补不上的照页面
  原样并在 message 里写明条数。补全请求失败只降级为不补全，不影响榜单本身。

经济观察网（www.eeo.com.cn，公开、无签名、无 cookie）
- 8 个频道按电脑版现行导航取新版 ``/jg/`` 频道页（2026-09-30 主 Agent 口径，
  导航改名的取改名后的频道：财经→金融、地产→城市、评论→观察家、商业产业→产业、
  营销→现代广告）。页面顺序：频道页顶部的编辑推荐区 ``#top-bjtj``（服务端渲染，
  多数频道为空）在前，接口 ``app.eeo.com.cn`` ``getMoreArticle`` 第 1 页在后，按 id
  去重。接口不带 ``jsoncallback`` 时直接返回 JSON（与带回调同一份，board_api 实测）；
  ``contentid=0`` 或没有 ``published`` 的是广告位，不算条目；标题里的换行与连续
  空白压成一个空格。推荐区条目没有时间，按链接日期当天 0 点；同一篇也在列表里时
  用列表的发布时间。
- 每日热新闻：首页右栏 ``div.box_R_item.news`` 的第 1 个 tab（第 2 个是每周热新闻），
  标题取链接的 ``title`` 属性（链接文字会被截短），日期只能从链接 ``/YYYY/MMDD/``
  取，按北京时间当天 0 点。
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.logger import logger

ROUTE_NAME = "nbd-eeo"

_NBD = "https://www.nbd.com.cn"
_NBD_M = "https://m.nbd.com.cn"
_EEO = "https://www.eeo.com.cn"
_EEO_API = "https://app.eeo.com.cn/"

# 子榜 -> (中文名, 每经栏目 id)。声明序第一个是默认榜（与 board_api DEFAULT_TYPE 一致）。
_NBD_BOARDS: dict[str, tuple[str, str]] = {
    "nbd-news": ("每经网 · 要闻", "3"),
    "nbd-market-events": ("每经网 · 影响市场重大事件", "2226"),
    "nbd-headline": ("每经网 · 每经头条", "1161"),
    "nbd-hot-comment": ("每经网 · 每经热评", "1072"),
    "nbd-investigation": ("每经网 · 每经调查", "587"),
    "nbd-original": ("每经网 · 重磅原创", "332"),
    "nbd-flash": ("每经网 · 首发快讯", "1320"),
}

# 子榜 -> (中文名, getMoreArticle 的 uuid, 频道页路径)。uuid 取自频道页
# input#catid_lyp 与首页导航 data-id（board_api 核对一致）；eeo-daily-hot 取首页。
_EEO_CHANNELS: dict[str, tuple[str, str, str]] = {
    "eeo-tmt": ("经济观察网 · TMT", "6fae9c5391224500af5b81167ae2a016", "/jg/chanye/tmt/"),
    "eeo-listed-company": (
        "经济观察网 · 上市公司",
        "dee83eed1979438aa0d29b636a7793da",
        "/jg/tuijian/shangshigongsi/",
    ),
    # 电脑版导航"产业"（tophub 榜名"商业产业"）
    "eeo-business": (
        "经济观察网 · 商业产业",
        "317476ab2e7b4c34918b73f7d04e2e52",
        "/jg/chanye/",
    ),
    # 电脑版导航"产业 > 城市"（tophub 榜名"地产"）
    "eeo-real-estate": (
        "经济观察网 · 地产",
        "3f0daa0ad2ea49c8b3af1a6fc23814d8",
        "/jg/chanye/chengshi/",
    ),
    "eeo-auto": ("经济观察网 · 汽车", "1ff57cd555884d0da498e8617216498e", "/jg/chanye/qiche/"),
    # 电脑版导航"现代广告"（tophub 榜名"营销"）
    "eeo-marketing": (
        "经济观察网 · 营销",
        "9af7a040a2984b57b4f8daf0d884f3ea",
        "/jg/tuijian/xiandaiguanggao/",
    ),
    # 电脑版导航"观察家"（tophub 榜名"评论"）
    "eeo-opinion": ("经济观察网 · 评论", "e71afa970ed44f3d9ded2bdccaf9ba78", "/jg/guanchajia/"),
    # 电脑版导航"金融"（tophub 榜名"财经"）
    "eeo-finance": ("经济观察网 · 财经", "9cdd41e11a114e5d8cbb8be12474aadd", "/jg/jinrong/"),
}

type_map: dict[str, str] = {
    "nbd-news": "每经网 · 要闻",
    "nbd-market-events": "每经网 · 影响市场重大事件",
    "nbd-headline": "每经网 · 每经头条",
    "nbd-hot-comment": "每经网 · 每经热评",
    "nbd-investigation": "每经网 · 每经调查",
    "nbd-original": "每经网 · 重磅原创",
    "nbd-flash": "每经网 · 首发快讯",
    "eeo-tmt": "经济观察网 · TMT",
    "eeo-listed-company": "经济观察网 · 上市公司",
    "eeo-business": "经济观察网 · 商业产业",
    "eeo-real-estate": "经济观察网 · 地产",
    "eeo-auto": "经济观察网 · 汽车",
    "eeo-marketing": "经济观察网 · 营销",
    "eeo-opinion": "经济观察网 · 评论",
    "eeo-finance": "经济观察网 · 财经",
    "eeo-daily-hot": "经济观察网 · 每日热新闻",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "每经网与经济观察网",
    "description": (
        "每经网 7 个栏目（要闻、影响市场重大事件、每经头条、每经热评、每经调查、"
        "重磅原创、首发快讯）；经济观察网 8 个频道与首页每日热新闻"
    ),
    "link": "https://www.nbd.com.cn/",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

_DEFAULT_TYPE = "nbd-news"

# 手机版每页 20 条，3 页覆盖电脑版一页 50 条；文章页补全最多 5 篇（board_api 口径）
_NBD_MOBILE_PAGES = 3
_NBD_ARTICLE_FALLBACK = 5
_EEO_PAGE_SIZE = 10

_NBD_ARTICLE_ID = re.compile(r"/articles/\d{4}-\d{2}-\d{2}/(\d+)\.html")
_NBD_ARTICLE_TITLE = re.compile(r"<title>\s*(.*?)\s*(?:\|\s*每经网)?\s*</title>", re.DOTALL)
_EEO_ARTICLE_ID = re.compile(r"/(\d{4})/(\d{2})(\d{2})/(\d+)\.shtml")


def _one_line(text: str) -> str:
    """经观标题里有换行和连续空白，压成一个空格（board_api one_line 口径）。"""
    return " ".join((text or "").split())


# ---------------- 每经网 ----------------


def _parse_nbd_column(html: str) -> list[dict[str, Any]]:
    """电脑版栏目页 -> [{id, url, text, truncated, timestamp}]，照页面顺序。"""
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict[str, Any]] = []
    for block in soup.select("div.g-list-text div.m-list"):
        day_el = block.select_one("p.u-channeltime")
        day = day_el.get_text(strip=True) if day_el else ""
        for li in block.select("li.u-news-title"):
            a = li.find("a", href=True)
            if not isinstance(a, Tag):
                continue
            href = str(a["href"])
            matched = _NBD_ARTICLE_ID.search(href)
            text = a.get_text(strip=True)
            if not matched or not text:
                continue
            span = li.find("span")
            clock = span.get_text(strip=True) if isinstance(span, Tag) else ""
            # 栏目页日期 + 时刻（北京时间）；没有时刻时按当天 0 点
            timestamp = get_time(f"{day} {clock}") if day and clock else get_time(day)
            rows.append(
                {
                    "id": matched.group(1),
                    "url": href,
                    "text": text,
                    "truncated": "news-title-a" in (a.get("class") or []),
                    "timestamp": timestamp,
                }
            )
    return rows


def _parse_nbd_mobile(html: str) -> dict[str, str]:
    """手机版栏目页 -> {文章 id: 完整标题}。"""
    out: dict[str, str] = {}
    for a in BeautifulSoup(html, "lxml").select("div.articleList a[href]"):
        matched = _NBD_ARTICLE_ID.search(str(a["href"]))
        title = a.get_text(" ", strip=True)
        if matched and title:
            out.setdefault(matched.group(1), title)
    return out


def _parse_nbd_article_title(html: str) -> str | None:
    matched = _NBD_ARTICLE_TITLE.search(html)
    return matched.group(1).strip() if matched else None


async def _get_nbd(board: str, column_id: str, no_cache: bool) -> dict:
    result = await get(
        url=f"{_NBD}/columns/{column_id}/",
        no_cache=no_cache,
        response_type="text",
        cache_key=f"nbd-eeo:nbd-column:{column_id}",
    )
    rows = _parse_nbd_column(str(result.data))
    if not rows:
        raise RuntimeError(f"NBD column {column_id} page has no list rows (page changed)")
    full_titles = await _complete_nbd_titles(rows, column_id, no_cache)
    items: list[ListItem] = []
    incomplete = 0
    for row in rows:
        title = str(row["text"])
        if row["truncated"]:
            candidate = full_titles.get(str(row["id"]), "")
            if candidate.startswith(title) and len(candidate) >= len(title):
                title = candidate
            elif candidate != title:
                incomplete += 1
        items.append(
            ListItem(
                id=str(row["id"]),
                title=title,
                url=str(row["url"]),
                timestamp=row["timestamp"],
            )
        )
    if not items:
        raise RuntimeError(f"NBD {board} board returned no items")
    message = (
        f"{incomplete} 条标题在栏目页被截短且未能补全，照栏目页原样" if incomplete else None
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
        "message": message,
    }


async def _complete_nbd_titles(
    rows: list[dict[str, Any]], column_id: str, no_cache: bool
) -> dict[str, str]:
    """补全被截短的标题：先手机版（最多 3 页），再文章页（最多 5 篇）。

    补全请求是增强信息，任何失败都只降级为不补全，不让整张榜失败。
    """
    full: dict[str, str] = {}
    need = {str(row["id"]) for row in rows if row["truncated"]}
    if not need:
        return full
    known_ids = {str(row["id"]) for row in rows}
    for page in range(1, _NBD_MOBILE_PAGES + 1):
        if need <= full.keys():
            break
        try:
            mobile = await get(
                url=f"{_NBD_M}/columns/{column_id}/" + (f"page/{page}/" if page > 1 else ""),
                no_cache=no_cache,
                response_type="text",
                cache_key=f"nbd-eeo:nbd-mobile:{column_id}:{page}",
            )
        except Exception as exc:  # noqa: BLE001 - 手机版不可达时放弃该补全来源
            logger.warning(f"⚠️ [NBD] mobile column {column_id} page {page} failed: {exc}")
            break
        got = {
            key: value
            for key, value in _parse_nbd_mobile(str(mobile.data)).items()
            if key in known_ids
        }
        if not got:
            # 手机版是另一份列表（如栏目 332），不再往下翻
            break
        full.update(got)
    if need <= full.keys():
        return full
    by_id = {str(row["id"]): row for row in rows}
    pending = [
        row_id
        for row_id in (str(row["id"]) for row in rows)
        if row_id in need and row_id not in full
    ][:_NBD_ARTICLE_FALLBACK]
    for article_id in pending:
        try:
            article = await get(
                url=str(by_id[article_id]["url"]),
                no_cache=no_cache,
                response_type="text",
                cache_key=f"nbd-eeo:nbd-article:{article_id}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"⚠️ [NBD] article {article_id} title fallback failed: {exc}")
            continue
        title = _parse_nbd_article_title(str(article.data))
        if title:
            full[article_id] = title
    return full


# ---------------- 经济观察网 ----------------


def _parse_eeo_rows(rows: Any) -> list[ListItem]:
    """getMoreArticle 的 data[] -> 条目；contentid=0 / 没有 published 的是广告位。"""
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        content_id = str(row.get("contentid") or "0")
        if content_id == "0" or not row.get("published") or not row.get("url"):
            continue
        if content_id in seen:
            # 翻页时接口会把上一页末条再给一次；第 1 页内不该重复，这里是保险
            continue
        seen.add(content_id)
        items.append(
            ListItem(
                id=content_id,
                title=_one_line(str(row.get("title") or "")),
                url=str(row["url"]),
                mobileUrl=row.get("m_url") or None,
                hot=row.get("pv") or None,
                cover=row.get("thumb") or None,
                author=row.get("author") or None,
                desc=row.get("description") or None,
                timestamp=get_time(str(row["published"])),
            )
        )
    return items


def _parse_eeo_top(html: str) -> list[ListItem]:
    """新版频道页顶部的编辑推荐区 ``#top-bjtj``（大图 + 短标题 <b> + 导语 <span>，无时间）。"""
    items: list[ListItem] = []
    for a in BeautifulSoup(html, "lxml").select("#top-bjtj a[href]"):
        href = str(a["href"])
        matched = _EEO_ARTICLE_ID.search(href)
        if not matched:
            continue
        b = a.find("b")
        span = a.find("span")
        img = a.find("img")
        if isinstance(b, Tag):
            title = _one_line(b.get_text(" "))
        else:
            alt = str(img.get("alt") or "") if isinstance(img, Tag) else ""
            title = _one_line(alt or a.get_text(" "))
        desc = _one_line(span.get_text(" ")) if isinstance(span, Tag) else ""
        if not title:
            continue
        cover = str(img.get("src") or "") if isinstance(img, Tag) else ""
        items.append(
            ListItem(
                id=matched.group(4),
                title=title,
                url=href,
                # 与接口 m_url 同一规则：手机站同路径（board_api 实测能打开）
                mobileUrl=(
                    f"http://m.eeo.com.cn/{matched.group(1)}/{matched.group(2)}"
                    f"{matched.group(3)}/{matched.group(4)}.shtml"
                ),
                cover=cover or None,
                desc=desc or None,
                # 推荐区不显示时间，按链接日期当天 0 点
                timestamp=get_time(f"{matched.group(1)}-{matched.group(2)}-{matched.group(3)}"),
            )
        )
    return items


def _parse_eeo_daily_hot(html: str) -> list[ListItem]:
    box = BeautifulSoup(html, "lxml").select_one("div.box_R_item.news")
    tabs = box.select("ul.tab_content") if box else []
    if not tabs:
        raise RuntimeError("EEO homepage daily-hot block not found (page changed)")
    items: list[ListItem] = []
    for a in tabs[0].select("li a[href]"):  # 第 1 个 tab 是每日热新闻，第 2 个是每周
        href = str(a["href"])
        matched = _EEO_ARTICLE_ID.search(href)
        title = _one_line(str(a.get("title") or a.get_text(strip=True)))
        if not matched or not title:
            continue
        items.append(
            ListItem(
                id=matched.group(4),
                title=title,
                url=href,
                timestamp=get_time(
                    f"{matched.group(1)}-{matched.group(2)}-{matched.group(3)}"
                ),
            )
        )
    return items


async def _get_eeo_channel(
    board: str, label: str, uuid: str, channel_path: str, no_cache: bool
) -> dict:
    """推荐区（频道页 #top-bjtj）在前、接口第 1 页在后，按 id 去重。"""
    page_result = await get(
        url=f"{_EEO}{channel_path}",
        no_cache=no_cache,
        response_type="text",
        cache_key=f"nbd-eeo:eeo-channel-page:{board}",
    )
    top_items = _parse_eeo_top(str(page_result.data))
    api_result = await get(
        # 不带 jsoncallback 时接口直接返回 JSON，与频道页"加载更多"的 JSONP 同一份
        url=(
            f"{_EEO_API}?app=article&controller=index&action=getMoreArticle"
            f"&uuid={uuid}&page=0&pageSize={_EEO_PAGE_SIZE}&prevUuid=&prevPublishDate="
        ),
        no_cache=no_cache,
        response_type="json",
        cache_key=f"nbd-eeo:eeo-api:{board}",
    )
    payload = api_result.data if isinstance(api_result.data, dict) else {}
    if payload.get("code") != 200:
        raise RuntimeError(
            f"EEO getMoreArticle returned code={payload.get('code')} for {label}"
        )
    listed_items = _parse_eeo_rows(payload.get("data"))
    listed_by_id = {item.id: item for item in listed_items}
    for item in top_items:
        # 推荐区只有日期；同一篇也在列表里时，用列表的发布时间
        if item.id in listed_by_id:
            item.timestamp = listed_by_id[item.id].timestamp
    top_ids = {item.id for item in top_items}
    items = top_items + [item for item in listed_items if item.id not in top_ids]
    if not items:
        raise RuntimeError(f"EEO {label} board returned no items")
    return {
        "from_cache": page_result.from_cache and api_result.from_cache,
        "update_time": api_result.update_time,
        "data": items,
        "message": None,
    }


async def _get_eeo_daily_hot(no_cache: bool) -> dict:
    result = await get(
        url=f"{_EEO}/",
        no_cache=no_cache,
        response_type="text",
        cache_key="nbd-eeo:eeo-home",
    )
    items = _parse_eeo_daily_hot(str(result.data))
    if not items:
        raise RuntimeError("EEO daily-hot board returned no items")
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
    if type_param in _NBD_BOARDS:
        _, column_id = _NBD_BOARDS[type_param]
        list_data = await _get_nbd(type_param, column_id, no_cache)
    elif type_param in _EEO_CHANNELS:
        label, uuid, channel_path = _EEO_CHANNELS[type_param]
        list_data = await _get_eeo_channel(type_param, label, uuid, channel_path, no_cache)
    else:
        list_data = await _get_eeo_daily_hot(no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[type_param],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
        message=list_data.get("message"),
    )

"""腾讯新闻栏目(news.qq.com PC 前端背后的 i.news.qq.com 公开接口,无签名、无 cookie)。

board_api 单元 `tmp/board_api/tencent_news_channels` 的 1:1 迁移,证据见该目录 README、
`analysis_report.md` 与 `verify/header_check.txt`、`verify/top3_check.md`。4 个子榜:

- 娱乐榜(ent-rank):`GET /gw/event/pc_hot_ranking_list?rank_id=ent`。现行 PC 前端没有
  显示位置(ent 频道右栏组件调的是 rank_id=hot),但接口仍每 10 分钟更新、内容与 tophub
  "娱乐榜"一致,按 board_api"入口没了但仍在更新"的口径做。前端 i5() 去掉说明占位
  (articletype "560")和没有 url / hotEvent 的条目,置顶(hotEvent.is_top)在前,最多 50 条
  (u5(list, 50));标题取条目自身的 title(文章标题;hotEvent.title 短标题是显示总热点榜
  组件的规则,这份榜不适用——board_api 推翻性验证后改),链接照前端 lN() 拼成
  news.qq.com/rain/a/<id>。与既有 qq-news(总热点榜 r.inews.qq.com)和 tencent-hot
  (getTagInfo 综合热点)不同源不同榜
- 热问(hot-question):`GET /web_backend/getHotQuestionList` 的 data.hot_questions
  (长问句,链接到回答页 new.qq.com/rain/a/<回答 id>)。上游没有条目时间
- 谷雨实验室(guyu-lab):作者页 news.qq.com/omn/author/8QMd3Hta64Advz3Z 的
  `GET /getSubNewsMixedList?tabId=om_index`。tabId 取作者页缺省页签"主页"
  (getUserHomepageInfo 的 defaultChannelId,图文与视频混排);"图文"页签是 om_article。
  前端 bJ() 只保留有 id、title 且 articletype 不是空串 / 标签("123")的条目
- 科技频道(tech-feed):`POST /web_feed/getPCList`,JSON 体照前端 N1()(channel_id=
  news_news_tech、item_count=12、qimei36 = device_id = 随机 36 位,推荐流按它个性化,
  不带也能返回)。articletype "525" 的"热点精选"卡片的 sub_item 是顶部模块,其余是
  信息流;标题照前端 $q() 取 short_title || tlTitle || title,封面取
  pic_info.big_img[0] || small_img[0] || thumbnails_qqnews[0],没有封面不显示;
  链接照前端 lN(id, {adChannelId}) 拼成 news.qq.com/rain/a/<id>?adChannelId=tech;
  先顶部模块再信息流,按 id 去重

请求头口径(header_check 实测):四个接口用 curl 缺省 UA、不带 Referer / Origin / cookie
都 200,这里只照页面 XHR 带 Referer 保持一致。时间口径:娱乐榜与谷雨的 timestamp 是
Unix 秒、科技是北京时间字符串,统一转毫秒;热问没有时间。
"""

from __future__ import annotations

import random
import re
import string
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get, post

ROUTE_NAME = "tencent-news-channels"

# 声明序第一个(ent-rank)是默认榜。
type_map: dict[str, str] = {
    "ent-rank": "娱乐榜",
    "hot-question": "热问",
    "guyu-lab": "谷雨实验室",
    "tech-feed": "科技频道",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "腾讯新闻栏目",
    "description": "腾讯新闻栏目:娱乐热点榜、热问、谷雨实验室(作者页主页)与科技频道信息流",
    "link": "https://news.qq.com/",
    "params": {
        "type": {
            "name": "栏目",
            "type": type_map,
        },
    },
}

_DEFAULT_TYPE = next(iter(type_map))
_API = "https://i.news.qq.com"
_ARTICLE_URL = "https://news.qq.com/rain/a/{id}"
# 娱乐榜:前端 l5(rank_id, page_size=51) 的固定参数;只带 rank_id 也 200,
# 但不带 page_size 只返回 21 条(header_check),照页面带上。
_RANK_PARAMS: dict[str, str] = {
    "ids_hash": "",
    "offset": "0",
    "page_size": "51",
    "appver": "15.5_qqnews_7.1.60",
    "rank_id": "ent",
}
_RANK_HEADERS = {"Referer": "https://news.qq.com/ch/ent"}
_RANK_TIP_TYPE = "560"  # 第 1 条"每10分钟更新一次"的说明占位,前端 i5() 去掉
_RANK_MAX = 50  # 前端 u5(list, 50)
_QUESTION_HEADERS = {"Referer": "https://news.qq.com/"}
_GUYU_SUID = "8QMd3Hta64Advz3Z"
_GUYU_TAB = "om_index"  # 作者页缺省页签"主页"(defaultChannelId);图文页签是 om_article
_GUYU_HEADERS = {"Referer": f"https://news.qq.com/omn/author/{_GUYU_SUID}"}
_TAG_TYPE = "123"  # 前端 bJ() 过滤掉的标签类条目
_TECH_CHANNEL = "news_news_tech"
_TECH_ITEM_COUNT = 12  # 前端 N1():item_count u=12
_TECH_HOT_MODULE_TYPE = "525"  # "热点精选"卡片,sub_item 进顶部模块
_TECH_HEADERS = {"Referer": "https://news.qq.com/ch/tech"}
_TECH_CACHE_KEY = f"{ROUTE_NAME}:tech-feed"  # 请求体带随机 qimei36,固定缓存键才能命中
_BEIJING = timezone(timedelta(hours=8))


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _first_cover(*groups: Any) -> str | None:
    """取第一组里第一个以 http 开头的字符串(board_api 的 _first 口径)。"""
    for group in groups:
        if isinstance(group, list) and group:
            first = group[0]
            if isinstance(first, str) and first.startswith("http"):
                return first
    return None


def _bj_timestamp(value: Any) -> int | None:
    """北京时间字符串("2026-09-28 07:04:30")→ Unix 秒;解析失败返回 None。"""
    try:
        moment = datetime.strptime(str(value).strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=_BEIJING)
    except ValueError:
        return None
    return int(moment.timestamp())


def _row_timestamp(row: dict[str, Any]) -> int | None:
    """行内秒级 timestamp 优先,退回北京时间字符串 time;统一由 get_time 转毫秒。"""
    if isinstance(row.get("timestamp"), int):
        return get_time(row["timestamp"])
    return get_time(_bj_timestamp(row.get("time")))


async def _fetch_ent_rank(no_cache: bool) -> dict:
    result = await get(
        url=f"{_API}/gw/event/pc_hot_ranking_list",
        params=_RANK_PARAMS,
        headers=_RANK_HEADERS,
        no_cache=no_cache,
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("ret") != 0:
        raise RuntimeError(
            f"Tencent ent rank returned ret={payload.get('ret')} (feed changed or blocked)"
        )
    idlist = payload.get("idlist")
    rows = idlist[0].get("newslist") if isinstance(idlist, list) and idlist and isinstance(idlist[0], dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("Tencent ent rank response has no idlist[0].newslist (feed changed)")  # noqa: TRY004 - 上游结构漂移是路由级错误
    # 前端 i5():去掉说明占位与没有 url / hotEvent 的条目;c5():置顶(is_top)在前
    kept = [
        row
        for row in rows
        if isinstance(row, dict)
        and str(row.get("articletype")) != _RANK_TIP_TYPE
        and row.get("url")
        and isinstance(row.get("hotEvent"), dict)
    ]
    kept = [row for row in kept if row["hotEvent"].get("is_top")] + [
        row for row in kept if not row["hotEvent"].get("is_top")
    ]
    data: list[ListItem] = []
    for row in kept[:_RANK_MAX]:
        event = row["hotEvent"]
        item_id = str(event.get("id") or row.get("id") or "").strip()
        # 标题取条目自身(文章标题,与 tophub 一致);hotEvent.title 短标题是总热点榜组件的规则
        title = _clean(row.get("title")) or _clean(event.get("title"))
        if not item_id or not title:
            continue
        data.append(
            ListItem(
                id=item_id,
                title=title,
                url=_ARTICLE_URL.format(id=item_id),
                mobileUrl=row.get("url") or None,
                hot=event.get("hotScore"),
                cover=_first_cover(
                    row.get("thumbnails_qqnews"),
                    row.get("thumbnails_big"),
                    row.get("thumbnails"),
                    row.get("bigImage"),
                ),
                author=_clean(row.get("source")) or _clean(row.get("chlname")) or None,
                timestamp=_row_timestamp(row),
            )
        )
    if not data:
        raise RuntimeError("Tencent ent rank parsed no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}


async def _fetch_hot_question(no_cache: bool) -> dict:
    result = await get(url=f"{_API}/web_backend/getHotQuestionList", headers=_QUESTION_HEADERS, no_cache=no_cache)
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("code") != 0:
        raise RuntimeError(
            f"Tencent hot question returned code={payload.get('code')} message={payload.get('message')}"
        )
    data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    rows = data_obj.get("hot_questions")
    if not isinstance(rows, list):
        raise RuntimeError("Tencent hot question response has no data.hot_questions (feed changed)")  # noqa: TRY004 - 上游结构漂移是路由级错误
    data: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = _clean(row.get("title"))
        url = str(row.get("url") or "").strip()
        if not title or not url.startswith("http"):
            continue
        data.append(
            ListItem(
                # 问题 id;个别条目缺 cms_id 时退回答页链接,仍不是名次
                id=str(row.get("cms_id") or url),
                title=title,
                url=url,
                mobileUrl=url,
                cover=row.get("image") or None,
                author=_clean(row.get("answer_name")) or None,
                desc=_clean(row.get("main_points")) or None,
                # 上游没有条目时间
            )
        )
    if not data:
        raise RuntimeError("Tencent hot question parsed no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}


async def _fetch_guyu(no_cache: bool) -> dict:
    query = {"offset_info": "", "guestSuid": _GUYU_SUID, "tabId": _GUYU_TAB, "caller": "1", "from_scene": "103"}
    result = await get(
        url=f"{_API}/getSubNewsMixedList",
        params=query,
        headers=_GUYU_HEADERS,
        no_cache=no_cache,
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("ret") != 0 or not isinstance(payload.get("newslist"), list):
        raise RuntimeError(f"Tencent guyu list returned ret={payload.get('ret')} (feed changed)")
    data: list[ListItem] = []
    for row in payload["newslist"]:
        # 前端 bJ():要有 id、title,articletype 不是空串或标签("123")
        if (
            not isinstance(row, dict)
            or not row.get("id")
            or not row.get("title")
            or str(row.get("articletype", "")) in ("", _TAG_TYPE)
        ):
            continue
        item_id = str(row["id"])
        data.append(
            ListItem(
                id=item_id,
                title=_clean(row.get("title")),
                url=_ARTICLE_URL.format(id=item_id),
                mobileUrl=row.get("url") or None,
                cover=_first_cover(row.get("thumbnails_qqnews"), row.get("thumbnails_big"), row.get("thumbnails")),
                author=_clean(row.get("source")) or _clean(row.get("chlname")) or None,
                desc=_clean(row.get("abstract")) or None,
                timestamp=_row_timestamp(row),
            )
        )
    if not data:
        raise RuntimeError("Tencent guyu list parsed no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}


def _feed_item(row: dict[str, Any]) -> ListItem | None:
    """照前端 $q():标题 short_title || tlTitle || title;封面
    pic_info.big_img[0] || small_img[0] || thumbnails_qqnews[0],没有封面不显示。"""
    item_id = str(row.get("id") or "").strip()
    title = _clean(row.get("short_title") or row.get("tlTitle") or row.get("title"))
    pic = row.get("pic_info") if isinstance(row.get("pic_info"), dict) else {}
    cover = _first_cover(pic.get("big_img"), pic.get("small_img"), row.get("thumbnails_qqnews"))
    if not item_id or not title or not cover:
        return None
    link = row.get("link_info") if isinstance(row.get("link_info"), dict) else {}
    media = row.get("media_info") if isinstance(row.get("media_info"), dict) else {}
    url = f"{_ARTICLE_URL.format(id=item_id)}?{urlencode({'adChannelId': 'tech'})}"
    return ListItem(
        id=item_id,
        title=title,
        url=url,
        mobileUrl=link.get("url") or url,
        cover=cover,
        author=_clean(media.get("chl_name")) or None,
        desc=_clean(row.get("desc")) or None,
        timestamp=get_time(_bj_timestamp(row.get("publish_time"))),
    )


async def _fetch_tech(no_cache: bool) -> dict:
    # qimei36 = device_id = 随机 36 位(推荐流按它个性化,不带也能返回,board_api 同口径);
    # 缓存键固定,随机体不影响命中。
    qimei = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(36))
    result = await post(
        url=f"{_API}/web_feed/getPCList",
        headers=_TECH_HEADERS,
        body={
            "base_req": {"from": "pc"},
            "forward": "2",
            "qimei36": qimei,
            "device_id": qimei,
            "flush_num": 1,
            "channel_id": _TECH_CHANNEL,
            "item_count": _TECH_ITEM_COUNT,
            "is_local_chlid": "0",
        },
        no_cache=no_cache,
        cache_key=_TECH_CACHE_KEY,
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("code") != 0 or not isinstance(payload.get("data"), list):
        raise RuntimeError(f"Tencent tech feed returned code={payload.get('code')} (feed changed)")
    hot_module: list[ListItem] = []
    feed: list[ListItem] = []
    for row in payload["data"]:
        if not isinstance(row, dict):
            continue
        if str(row.get("articletype")) == _TECH_HOT_MODULE_TYPE:
            subs = row.get("sub_item") if isinstance(row.get("sub_item"), list) else []
            hot_module.extend(item for sub in subs if isinstance(sub, dict) and (item := _feed_item(sub)))
        elif item := _feed_item(row):
            feed.append(item)
    data: list[ListItem] = []
    seen: set[str] = set()
    for item in hot_module + feed:  # 先顶部模块再信息流,按 id 去重
        if item.id in seen:
            continue
        seen.add(item.id)
        data.append(item)
    if not data:
        raise RuntimeError("Tencent tech feed parsed no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}


_FETCHERS = {
    "ent-rank": _fetch_ent_rank,
    "hot-question": _fetch_hot_question,
    "guyu-lab": _fetch_guyu,
    "tech-feed": _fetch_tech,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", _DEFAULT_TYPE)
    if board not in _FETCHERS:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    list_data = await _FETCHERS[board](no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[board],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )

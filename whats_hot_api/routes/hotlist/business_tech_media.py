"""商业科技媒体：36氪、钛媒体、华尔街见闻、财富中文网、虎嗅（多站点，type=站点-栏目）。

迁移自 board_api business_tech_media 单元（18 个已完成榜），每个子榜 1 个请求：
- 36氪：页面服务端渲染时写进 ``window.initialState`` 的 JSON（页面首屏按它渲染，逐条相同）
  - 24小时热榜：首页 ``homeData.data.hotlist.data``；AI/创投/资讯推荐：频道页
    ``information.informationList.itemList``；深氪：专栏页 ``motifDetailData…itemList``；
    综合榜：``/hot-list/zonghe/<北京日期>/1`` 的 ``hotListDetail.articleList.itemList``。
    综合榜不带日期是 404，目录页"查看完整榜单"链到当天日期；刚过零点原站可能还没生成
    当天的榜，此时为时段性空榜，输出 0 条 + message，不算失败
  - 视频榜：m 站热榜接口 ``POST gateway.36kr.com/api/mis/nav/home/nav/rank/video``。
    48 小时窗口内没有新视频时上游返回 ``code=0, videoList=[]``，同为时段性空榜。
    注意 whatshot 既有 36kr 路由的 video 榜 ``hot`` 取 ``statCollect``（视频条目没有）、
    链接拼成文章页 ``/p/<id>``，均为需修点；本路由按证据取 ``statRead`` 与 ``/video/<id>``
- 钛媒体：api.tmtpost.com。请求头必须带 ``app-version``（缺了 406 miss app_version header）；
  页面脚本还给每个请求加 ``Authorization = "13:<毫秒时间戳>|44:<md5(base64(lower(pc+web1.0+t)))><12位随机串>"``
  （两端带双引号），照页面算法生成；实测服务端当前不校验它（board_api param_matrix）。
  热门文章榜单必须带 ``duration=259200``（72 小时窗口），不带返回 2014/2019 年旧文章；
  limit=20 对应「热门文章」完整榜单页 /hot 的首屏（推翻性验证后的口径）
- 华尔街见闻：api-one.wallstcn.com。周排行取 ``articles/hot?period=all`` 响应里的
  ``week_items``（PC 页面的「最热文章」组件只展示 day_items，week_items 在同一响应里）；
  早餐取 ``information-flow?channel=breakfast``，只保留 ``resource_type=article`` 的条目
- 财富中文网：服务端渲染 HTML。头条 ``div.s1-box`` + ``li.news-item``；首页较新条目的
  日期显示为相对时间（"11分钟前"），这类取链接里的 /c/YYYY-MM/DD/ 日期兜底
- 虎嗅：POST 表单接口（platform=www 必需，缺了返回"platform类型不正确"）。早报的
  ``format_publish_time`` 只有显示时间（"48分钟前"、"2026-09-24"），按显示换算，
  以响应 Date 头为基准（不用本机当前时间，避免缓存/时钟偏差放大）

不做：虎嗅晚报（brief_column_id=2，最新一期停在 2025-06-27，已停更，见 board_api README）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import re
import string
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get, post

ROUTE_NAME = "business-tech-media"

_TYPE_MAP: dict[str, str] = {
    "36kr-24h": "36氪 · 24小时热榜",
    "36kr-ai": "36氪 · AI频道",
    "36kr-contact": "36氪 · 创投频道",
    "36kr-shenke": "36氪 · 深氪",
    "36kr-zonghe": "36氪 · 综合榜",
    "36kr-video": "36氪 · 视频榜",
    "36kr-recommend": "36氪 · 资讯推荐",
    "tmtpost-nictation": "钛媒体 · 7X24快报",
    "tmtpost-new": "钛媒体 · 最新",
    "tmtpost-hot": "钛媒体 · 热门文章榜单",
    "wallstreetcn-week": "华尔街见闻 · 周排行",
    "wallstreetcn-breakfast": "华尔街见闻 · 早餐",
    "fortunechina-shangye": "财富中文网 · 商业频道",
    "fortunechina-latest": "财富中文网 · 最新",
    "huxiu-brief": "虎嗅 · 早报",
    "huxiu-latest": "虎嗅 · 最新",
    "huxiu-hot": "虎嗅 · 热文",
    "huxiu-finance": "虎嗅 · 金融财经",
}

_DEFAULT_TYPE = "36kr-24h"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "商业科技媒体",
    "description": "36氪、钛媒体、华尔街见闻、财富中文网、虎嗅的热榜与栏目列表。",
    "link": "https://36kr.com/",
    "params": {"type": {"name": "站点-栏目", "type": _TYPE_MAP}},
}

_CHINA_TZ = timezone(timedelta(hours=8))
_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_JSON_ACCEPT = "application/json, text/plain, */*"
# board_api 证据的全部请求都带这组客户端头（common.http.DEFAULT_HEADERS）
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_BASE_HEADERS = {"User-Agent": _BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", _DEFAULT_TYPE)
    if board not in _TYPE_MAP:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    site = board.split("-", 1)[0]
    fetchers = {
        "36kr": _get_36kr,
        "tmtpost": _get_tmtpost,
        "wallstreetcn": _get_wallstreetcn,
        "fortunechina": _get_fortunechina,
        "huxiu": _get_huxiu,
    }
    list_data = await fetchers[site](board, no_cache)
    return RouterData(
        **ROUTE_META,
        type=_TYPE_MAP[board],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
        message=list_data.get("message"),
    )


def _finish(result: Any, items: list[ListItem], message: str | None = None) -> dict:
    if not items and message is None:
        raise RuntimeError(f"{ROUTE_NAME} board returned no items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
        "message": message,
    }


# ---------------------------------------------------------------- 36氪

_KR_PAGES = {
    "36kr-24h": "https://36kr.com/",
    "36kr-ai": "https://36kr.com/information/AI/",
    "36kr-contact": "https://36kr.com/information/contact/",
    "36kr-recommend": "https://36kr.com/information/web_recommend/",
    "36kr-shenke": "https://36kr.com/motif/327685423105",
}
_KR_VIDEO_API = "https://gateway.36kr.com/api/mis/nav/home/nav/rank/video"


def _initial_state(html: str, url: str) -> dict[str, Any]:
    if "安全检测" in html[:20000] and "window.initialState" not in html:
        # 36kr SSR 页面在火山引擎风控下会返回"正在进行安全检测"挑战壳（200 + 17KB，
        # 2026-10-01 实测对 curl/httpx 都如此）；严格拒绝，不降级为空榜，也不绕过
        raise RuntimeError(f"36kr page {url} returned a volcano-engine security-check shell (challenge), not SSR data")
    match = re.search(r"window\.initialState\s*=\s*(\{.*?\})\s*</script>", html, re.DOTALL)
    if not match:
        raise RuntimeError(f"36kr page {url} has no window.initialState (page changed)")
    return json.loads(match.group(1))


def _kr_item(row: dict[str, Any], hot_key: str | None = None) -> ListItem | None:
    # 首页/频道页条目的字段在 templateMaterial 里；综合榜条目是扁平的
    material = row.get("templateMaterial")
    tm: dict[str, Any] = material if isinstance(material, dict) else row
    item_id = str(row.get("itemId") or tm.get("itemId") or "").strip()
    if not item_id:
        return None
    return ListItem(
        id=item_id,
        title=str(tm.get("widgetTitle") or "").strip(),
        url=f"https://www.36kr.com/p/{item_id}",
        mobileUrl=f"https://m.36kr.com/p/{item_id}",
        cover=tm.get("widgetImage"),
        author=tm.get("authorName") or tm.get("author"),
        desc=tm.get("summary") or tm.get("content"),
        hot=tm.get(hot_key) if hot_key else None,
        timestamp=get_time(tm.get("publishTime") or row.get("publishTime")),
    )


def _kr_zonghe_url() -> str:
    # 热榜目录页"查看完整榜单"链到当天的 /hot-list/zonghe/<北京日期>/1；不带日期是 404
    return f"https://36kr.com/hot-list/zonghe/{datetime.now(_CHINA_TZ):%Y-%m-%d}/1"


async def _get_36kr(board: str, no_cache: bool) -> dict:
    if board == "36kr-video":
        return await _get_36kr_video(no_cache)
    url = _kr_zonghe_url() if board == "36kr-zonghe" else _KR_PAGES[board]
    result = await get(
        url=url,
        headers={**_BASE_HEADERS, "Accept": _HTML_ACCEPT},
        no_cache=no_cache,
        response_type="text",
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    state = _initial_state(str(result.data), url)
    if board == "36kr-24h":
        rows = ((state.get("homeData") or {}).get("data") or {}).get("hotlist", {}).get("data")
    elif board == "36kr-shenke":
        rows = (
            (((state.get("motifDetailData") or {}).get("data") or {}).get("motifArticleList") or {}).get("data")
            or {}
        ).get("itemList")
    elif board == "36kr-zonghe":
        rows = ((state.get("hotListDetail") or {}).get("articleList") or {}).get("itemList")
    else:
        rows = ((state.get("information") or {}).get("informationList") or {}).get("itemList")
    if not isinstance(rows, list):
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
            f"36kr page {url} initialState has no list (page changed)"
        )
    # 综合榜页面每条显示"N收藏"（statCollect）；其余页面不显示数值
    hot_key = "statCollect" if board == "36kr-zonghe" else None
    items = [item for row in rows if isinstance(row, dict) and (item := _kr_item(row, hot_key=hot_key))]
    message = None
    if board == "36kr-zonghe" and not items:
        message = "36氪当天的综合榜为空（刚过零点时原站可能还没生成当天的榜）"
    return _finish(result, items, message)


async def _get_36kr_video(no_cache: bool) -> dict:
    # 与 m 站热榜「视频榜」tab 相同的请求；timestamp 是毫秒（实测去掉结果相同，照页面带上）
    body = {
        "partner_id": "wap",
        "param": {"siteId": 1, "platformId": 2},
        "timestamp": int(time.time() * 1000),
    }
    result = await post(
        url=_KR_VIDEO_API,
        headers={
            **_BASE_HEADERS,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": _JSON_ACCEPT,
        },
        body=body,
        no_cache=no_cache,
        cache_key=f"{ROUTE_NAME}:36kr-video",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("code") != 0:
        raise RuntimeError(f"36kr video API returned code={payload.get('code')} (business error)")
    videos = (payload.get("data") or {}).get("videoList")
    if not isinstance(videos, list):
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
            "36kr video API response has no videoList (feed changed)"
        )
    items: list[ListItem] = []
    for row in videos:
        if not isinstance(row, dict):
            continue
        tm = row.get("templateMaterial") if isinstance(row.get("templateMaterial"), dict) else {}
        video_id = str(row.get("itemId") or tm.get("itemId") or "").strip()
        if not video_id:
            continue
        items.append(
            ListItem(
                id=video_id,
                title=str(tm.get("widgetTitle") or "").strip(),
                url=f"https://www.36kr.com/video/{video_id}",
                cover=tm.get("widgetImage"),
                hot=tm.get("statRead"),  # 视频条目只有 statRead（阅读），没有 statCollect
                timestamp=get_time(tm.get("publishTime") or row.get("publishTime")),
            )
        )
    message = None
    if not items:
        # 48 小时窗口内没有新视频时上游就是空列表（code=0），属时段性空榜
        message = "36氪视频榜上游为空（48 小时内没有新视频时的时段性空榜）"
    return _finish(result, items, message)


# ---------------------------------------------------------------- 钛媒体

_TMT_API = "https://api.tmtpost.com"
# 取自页面脚本 dist/entry.*.js 的 headerKeys（app-version 缺了返回 406）
_TMT_HEADERS = {
    "device": "pc",
    "app-version": "web1.0",
    "app-key": "2015042403",
    "app-secret": "F3x47g39Wc4M96nwA28T",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": _JSON_ACCEPT,
}
_TMT_NICTATION_PARAMS: dict[str, Any] = {
    "time_start": "",
    "time_end": "",
    "keyword": "",
    "limit": 20,
    "offset": 0,
    "if_keyword_highlight": "true",
    "platform": "pc",
    "fields": (
        "number_of_bookmarks;number_of_comments;number_of_upvotes;if_current_user_bookmarked;"
        "if_current_user_voted;share_link;share_link;share_description;share_image;word_comments;"
        "stock_list;is_important;audio;duration;word_classify;stock;"
    ),
    "word_fields": (
        "number_of_bookmarks;number_of_comments;number_of_upvotes;if_current_user_bookmarked;"
        "if_current_user_voted;share_link;share_link;share_description;share_image;word_comments;"
        "stock_list;is_important;word_classify;stock;word_thumbnail_image;post_list;"
    ),
}
# /new 页首屏参数：subtype 必需（不带时接口只返回文章，与页面混排不一致）
_TMT_NEW_PARAMS: dict[str, Any] = {
    "limit": 20,
    "offset": 0,
    "subtype": "post;atlas;video_article;fm_audios;",
    "focus_post_image_size": '["448_252","512_288"]',
    "thumb_image_size": '["448_252"]',
    "atlas_cover_image_size": '["448_252",""512_288""]',
    "atlas_image_size": '["448_252","512_288"]',
    "video_image_size": '["448_252","800_450"]',
    "cover_image_size": '["448_252","512_288"]',
    "ad_image_size": '["448_252","512_288"]',
    "image_size": '["448_252","512_288"]',
    "word_image_size": '["448_252","512_288"]',
    "post_fields": "access;authors;number_of_reads;is_pro_post;is_paid_special_column_post;available;",
    "word_fields": "word_cover_image;number_of_comments;",
    "video_article_fields": "main;authors;number_of_reads;number_of_comments;",
    "fm_audio_fields": "number_of_plays;fm_albums;authors;number_of_plays;number_of_comments;",
    "fm_album_fields": "number_of_audios;authors;",
    "atlas_fields": "atlas_content;authors;number_of_contents",
    "live_stream_fields": "live_status;authors;user;is_current_user_following;number_of_reads;",
    "personal_live_stream_fields": "user;live_status;description;user;is_current_user_following;number_of_reads;",
}
# 「热门文章」页 /hot 首屏；duration=259200 必需（不带返回 2014、2019 年的旧文章）
_TMT_HOT_PARAMS: dict[str, Any] = {"limit": 20, "offset": 0, "duration": 259200}
# 页面 publicJumpWithType：非文章条目的链接模板
_TMT_LINKS = {"video_article": "/video/{}.html", "fm_audios": "/fm/{}.html", "atlas": "/photoset/{}.html"}


def _tmt_authorization(now_ms: int | None = None, rnd: str | None = None) -> str:
    """页面 getSecretKey()：``"13:${t}|44:${md5(Base64(device+app_version+t).toLowerCase())+randomString(12)}"``。

    t 为毫秒时间戳；返回值两端带双引号（页面模板字符串里写死的）。
    实测服务端当前不校验（去掉/乱写/1 天前时间戳结果相同），照页面算法生成。
    """
    t = now_ms if now_ms is not None else int(time.time() * 1000)
    digest = hashlib.md5(base64.b64encode(f"pcweb1.0{t}".lower().encode())).hexdigest()
    rand = rnd if rnd is not None else "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(12))
    return f'"13:{t}|44:{digest}{rand}"'


async def _tmt_get(
    path: str, params: dict[str, Any], board: str, no_cache: bool
) -> tuple[Any, list[dict[str, Any]]]:
    result = await get(
        url=f"{_TMT_API}{path}",
        params=params,
        headers={**_BASE_HEADERS, **_TMT_HEADERS, "Authorization": _tmt_authorization()},
        no_cache=no_cache,
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("result") != "ok" or not isinstance(payload.get("data"), list):
        raise RuntimeError(f"tmtpost {path} returned non-ok envelope: {str(payload)[:200]}")
    return result, payload["data"]


def _tmt_cover(row: dict[str, Any]) -> str | None:
    for key in ("thumb_image", "video_image", "cover_image", "image"):
        img = row.get(key)
        if isinstance(img, dict):
            for sizes in img.values():
                if isinstance(sizes, list) and sizes and isinstance(sizes[0], dict) and sizes[0].get("url"):
                    return str(sizes[0]["url"])
    return None


async def _get_tmtpost(board: str, no_cache: bool) -> dict:
    items: list[ListItem] = []
    seen: set[str] = set()

    def add(item: ListItem) -> None:
        if item.id not in seen:
            seen.add(item.id)
            items.append(item)

    if board == "tmtpost-nictation":
        result, rows = await _tmt_get("/v1/lists/word_paid_special_column_post", _TMT_NICTATION_PARAMS, board, no_cache)
        for row in rows:
            if not isinstance(row, dict):
                continue
            # 第 1 行 item_type=pc_power_pos 是"PC正能量组"：页面在列表最上方滚动展示的重要快报，
            # 照页面顺序放在最前
            words = row.get("items") if row.get("item_type") == "pc_power_pos" else [row]
            for word in words or []:
                if not isinstance(word, dict) or word.get("item_type", "word") != "word" or not word.get("guid"):
                    continue
                guid = str(word["guid"])
                add(
                    ListItem(
                        id=guid,
                        title=str(word.get("title") or "").strip(),
                        url=word.get("share_link") or f"https://www.tmtpost.com/nictation/{guid}.html",
                        author=word.get("author_name"),
                        desc=str(word.get("detail") or "").strip() or None,
                        timestamp=get_time(word.get("time_published")),
                    )
                )
    elif board == "tmtpost-new":
        result, rows = await _tmt_get("/v1/lists/new", _TMT_NEW_PARAMS, board, no_cache)
        for row in rows:
            if not isinstance(row, dict):
                continue
            guid = str(row.get("guid") or "")
            if not guid:
                continue
            kind = row.get("item_type") or "post"
            link = row.get("short_url") if kind == "post" else None
            link = link or urljoin("https://www.tmtpost.com", _TMT_LINKS.get(kind, "/{}.html").format(guid))
            authors = [
                str(author["username"])
                for author in row.get("authors") or []
                if isinstance(author, dict) and author.get("username")
            ]
            add(
                ListItem(
                    id=guid,
                    title=str(row.get("title") or "").strip(),
                    url=link,
                    cover=_tmt_cover(row),
                    author="、".join(authors) or None,
                    desc=str(row.get("summary") or "").strip() or None,
                    timestamp=get_time(row.get("time_published")),
                )
            )
    else:
        result, rows = await _tmt_get("/v1/posts/list/hot", _TMT_HOT_PARAMS, board, no_cache)
        for row in rows:
            if not isinstance(row, dict):
                continue
            guid = str(row.get("post_guid") or row.get("guid") or "")
            if not guid:
                continue
            add(
                ListItem(
                    id=guid,
                    title=str(row.get("title") or "").strip(),
                    url=row.get("short_url") or f"https://www.tmtpost.com/{guid}.html",
                    timestamp=get_time(row.get("time_published")),
                )
            )
    return _finish(result, items)


# ---------------------------------------------------------------- 华尔街见闻

_WSCN_API = "https://api-one.wallstcn.com/apiv1/content"


def _wscn_row(row: dict[str, Any]) -> ListItem | None:
    item_id = row.get("id")
    if item_id is None:
        return None
    author = row.get("author") if isinstance(row.get("author"), dict) else {}
    image = row.get("image") if isinstance(row.get("image"), dict) else {}
    return ListItem(
        id=str(item_id),
        title=str(row.get("title") or "").strip(),
        url=row.get("uri") or f"https://wallstreetcn.com/articles/{item_id}",
        hot=row.get("pageviews"),
        cover=image.get("uri"),
        author=author.get("display_name"),
        desc=str(row.get("content_short") or "").strip() or None,
        timestamp=get_time(row.get("display_time")),
    )


async def _get_wallstreetcn(board: str, no_cache: bool) -> dict:
    headers = {**_BASE_HEADERS, "Accept": _JSON_ACCEPT, "Referer": "https://wallstreetcn.com/"}
    if board == "wallstreetcn-week":
        # period=all 同时返回 day_items 与 week_items；PC 页面组件只展示 day_items，
        # week_items（60 条，按阅读量倒序）才是周榜
        result = await get(
            url=f"{_WSCN_API}/articles/hot",
            params={"period": "all"},
            headers=headers,
            no_cache=no_cache,
            cache_key=f"{ROUTE_NAME}:{board}",
        )
        payload = result.data if isinstance(result.data, dict) else {}
        rows = (payload.get("data") or {}).get("week_items") if isinstance(payload.get("data"), dict) else None
    else:
        # /news/breakfast 页 ArticleList 组件的首屏请求；页面只保留 article 资源（广告另行插入，不算）
        result = await get(
            url=f"{_WSCN_API}/information-flow",
            params={"channel": "breakfast", "accept": "article", "cursor": "", "limit": 20, "action": "upglide"},
            headers=headers,
            no_cache=no_cache,
            cache_key=f"{ROUTE_NAME}:{board}",
        )
        payload = result.data if isinstance(result.data, dict) else {}
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        flow = data.get("items") if isinstance(data.get("items"), list) else []
        rows = [
            entry.get("resource")
            for entry in flow
            if isinstance(entry, dict) and entry.get("resource_type") == "article" and isinstance(entry.get("resource"), dict)
        ]
    if payload.get("code") != 20000 or not isinstance(rows, list):
        raise RuntimeError(f"wallstreetcn API returned non-20000 envelope: {str(payload)[:200]}")
    items = [item for row in rows if isinstance(row, dict) and (item := _wscn_row(row))]
    return _finish(result, items)


# ---------------------------------------------------------------- 财富中文网

_FC_PAGES = {
    "fortunechina-shangye": "https://www.fortunechina.com/shangye/",
    "fortunechina-latest": "https://www.fortunechina.com/",
}


def _fc_date_sec(text: str) -> int | None:
    try:
        return int(datetime.strptime(text.strip(), "%Y-%m-%d").replace(tzinfo=_CHINA_TZ).timestamp())
    except ValueError:
        return None


def _fc_url_date_sec(href: str) -> int | None:
    match = re.search(r"/c/(\d{4})-(\d{2})/(\d{2})/", href)
    return _fc_date_sec(f"{match.group(1)}-{match.group(2)}-{match.group(3)}") if match else None


def _fc_entry(block: Tag, page: str) -> ListItem | None:
    """一条资讯：标题在 h2 里，链接是 h2 里的 a（频道页）或包住 h2 的 a（首页），指向 .../content_<id>.htm。"""
    h2 = block.select_one("h2")
    if h2 is None:
        return None
    link = h2.select_one("a[href]") or h2.find_parent("a")
    href = urljoin(page, str(link.get("href") or "").strip()) if link else ""
    title = re.sub(r"\s+", " ", h2.get_text(" ", strip=True))
    if not href.startswith("http") or not title:
        return None
    # 文章是 .../content_<id>.htm；资讯流里偶尔有专题页（如 /4040/2026.htm），用路径作 id
    match = re.search(r"content_(\d+)\.htm", href)
    item_id = match.group(1) if match else re.sub(r"^https?://[^/]+/", "", href)
    author = block.select_one(".info .author")
    date = block.select_one(".info .date")
    desc = block.select_one(".text-mod p")
    img = block.select_one(".pic img")
    timestamp = None
    if date is not None:
        # 页面日期多数是"2026-09-28"（北京时间 0 点）；首页较新条目显示相对时间，
        # 解析不了时用链接里的 /c/YYYY-MM/DD/ 日期兜底（推翻性验证后的口径）
        timestamp = get_time(_fc_date_sec(date.get_text(strip=True)))
    if timestamp is None:
        timestamp = get_time(_fc_url_date_sec(href))
    return ListItem(
        id=item_id,
        title=title,
        url=href,
        author=author.get_text(" ", strip=True) if author else None,
        desc=desc.get_text(" ", strip=True) if desc else None,
        cover=str(img.get("src")) if img and img.get("src") else None,
        timestamp=timestamp,
    )


async def _get_fortunechina(board: str, no_cache: bool) -> dict:
    page = _FC_PAGES[board]
    result = await get(
        url=page,
        headers={**_BASE_HEADERS, "Accept": _HTML_ACCEPT},
        no_cache=no_cache,
        response_type="text",
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    soup = BeautifulSoup(str(result.data), "lxml")
    # 头条（div.s1-box）在前，然后是页面上全部 li.news-item；首页的资讯流按时间倒序
    # 分在几个区块里（中间插着活动、视频、广告区块，不是 li.news-item）
    head = soup.select_one("div.s1-box")
    blocks: list[Tag] = ([head] if head is not None else []) + soup.select("li.news-item")
    if len(blocks) <= 1:
        raise RuntimeError(f"fortunechina page {page} has no news items (page changed)")
    items: list[ListItem] = []
    seen: set[str] = set()
    for block in blocks:
        item = _fc_entry(block, page)
        if item and item.id not in seen:
            seen.add(item.id)
            items.append(item)
    return _finish(result, items)


# ---------------------------------------------------------------- 虎嗅

_HX_HEADERS = {
    "Accept": _JSON_ACCEPT,
    "Origin": "https://www.huxiu.com",
    "Referer": "https://www.huxiu.com/",
}
# platform=www 是页面 hx-http 插件给每个 POST 加的（缺了返回"platform类型不正确"）
_HX_CALLS: dict[str, tuple[str, dict[str, str]]] = {
    "huxiu-brief": (
        "https://api-ms-club.huxiu.com/v1/briefColumn/briefList",
        {"platform": "www", "brief_column_id": "1", "last_id": ""},
    ),
    "huxiu-latest": (
        "https://api-ms-article.huxiu.com/v1/channel/pcArticleList",
        {"platform": "www", "channel_id": "0", "last_id": "", "pagesize": "12"},
    ),
    "huxiu-finance": (
        "https://api-ms-article.huxiu.com/v1/channel/pcArticleList",
        {"platform": "www", "channel_id": "115", "last_id": "", "pagesize": "12"},
    ),
    "huxiu-hot": (
        "https://api-ms-article.huxiu.com/v1/index/hotArticleList",
        {"platform": "www", "time_type": "2"},
    ),
}


def _relative_sec(text: str, now: datetime) -> int | None:
    """页面显示的发布时间（"刚刚"/"N分钟前"/"N小时前"/"昨天 H:MM"/"MM-DD"/"YYYY-MM-DD"）→ 秒。

    now 是响应生成时刻（调用方传响应的 Date 头，虎嗅接口只给显示时间）。
    """
    value = (text or "").strip()
    if not value:
        return None
    if value == "刚刚":
        return int(now.timestamp())
    if match := re.fullmatch(r"(\d+)\s*分钟前", value):
        return int((now - timedelta(minutes=int(match.group(1)))).timestamp())
    if match := re.fullmatch(r"(\d+)\s*小时前", value):
        return int((now - timedelta(hours=int(match.group(1)))).timestamp())
    if match := re.fullmatch(r"昨天\s*(\d{1,2}):(\d{2})", value):
        dt = (now - timedelta(days=1)).replace(
            hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0
        )
        return int(dt.timestamp())
    if match := re.fullmatch(r"(\d{1,2})-(\d{1,2})", value):
        dt = now.replace(month=int(match.group(1)), day=int(match.group(2)), hour=0, minute=0, second=0, microsecond=0)
        if dt > now:
            dt = dt.replace(year=dt.year - 1)
        return int(dt.timestamp())
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return _fc_date_sec(value)
    return None


def _response_date_now(headers: dict[str, Any]) -> datetime:
    """从响应头取 Date（相对时间的换算基准），取不到退回当前北京时间。"""
    raw = next((value for key, value in headers.items() if str(key).lower() == "date"), None)
    try:
        return parsedate_to_datetime(str(raw)).astimezone(_CHINA_TZ)
    except (TypeError, ValueError):
        return datetime.now(_CHINA_TZ)


async def _get_huxiu(board: str, no_cache: bool) -> dict:
    url, form = _HX_CALLS[board]
    if board == "huxiu-brief":
        # 早报只有显示时间，需要响应 Date 头做相对时间换算基准
        result = await post(
            url=url,
            headers={**_BASE_HEADERS, **_HX_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            body=urlencode(form),
            no_cache=no_cache,
            origin_info=True,
            cache_key=f"{ROUTE_NAME}:{board}",
        )
        wrapped = result.data if isinstance(result.data, dict) and isinstance(result.data.get("headers"), dict) else {}
        payload = wrapped.get("data") if isinstance(wrapped.get("data"), dict) else {}
        now = _response_date_now(wrapped.get("headers") or {})
    else:
        result = await post(
            url=url,
            headers={**_BASE_HEADERS, **_HX_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            body=urlencode(form),
            no_cache=no_cache,
            cache_key=f"{ROUTE_NAME}:{board}",
        )
        payload = result.data if isinstance(result.data, dict) else {}
        now = datetime.now(_CHINA_TZ)
    if not payload.get("success"):
        raise RuntimeError(f"huxiu {url} returned non-success envelope: {str(payload)[:200]}")
    data = payload.get("data")
    if isinstance(data, list):
        rows: list[Any] | None = data
    elif isinstance(data, dict):
        rows = data.get("datalist")
    else:
        rows = None
    if not isinstance(rows, list):
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
            f"huxiu {url} response has no list (feed changed)"
        )
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if board == "huxiu-brief":
            brief_id = row.get("brief_id")
            if brief_id is None:
                continue
            items.append(
                ListItem(
                    id=str(brief_id),
                    title=str(row.get("title") or "").strip(),
                    url=row.get("url") or f"https://www.huxiu.com/brief/{brief_id}.html",
                    mobileUrl=f"https://m.huxiu.com/brief/{brief_id}.html",
                    # 接口只给页面上显示的时间（"48分钟前"、"2026-09-24"），按显示换算，
                    # 以这次响应的 Date 头为基准，不用本机当前时间
                    timestamp=get_time(_relative_sec(str(row.get("format_publish_time") or ""), now)),
                )
            )
            continue
        article_id = row.get("aid")
        if article_id is None:
            continue
        user = row.get("user_info") if isinstance(row.get("user_info"), dict) else {}
        pic = row.get("pic_path")
        items.append(
            ListItem(
                id=str(article_id),
                title=str(row.get("title") or "").strip(),
                url=row.get("url") or f"https://www.huxiu.com/article/{article_id}.html",
                mobileUrl=f"https://m.huxiu.com/article/{article_id}.html",
                cover=None if not pic or "article_default_picpath" in str(pic) else pic,
                author=user.get("username"),
                desc=str(row.get("short_content") or "").strip() or None,
                timestamp=get_time(row.get("dateline") or row.get("publish_time")),
            )
        )
    return _finish(result, items)

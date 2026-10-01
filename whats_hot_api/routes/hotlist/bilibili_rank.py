from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.cache import CacheData, cache
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.logger import logger
from whats_hot_api.utils.tokens.bilibili import _enc_wbi

ROUTE_NAME = "bilibili-rank"

API = "https://api.bilibili.com"

# 视频分区排行:子榜 → (中文名, rid)。rid 是 2025 年后的新版分区 ID(board_api 逐个点
# tab 实测取得,与站点头部分区配置的 tid 一致);旧版 rid(如科技 188)已不适用
VIDEO_RANKS: dict[str, tuple[str, int]] = {
    "all": ("全站", 0),
    "douga": ("动画", 1005),
    "game": ("游戏", 1008),
    "kichiku": ("鬼畜", 1007),
    "music": ("音乐", 1003),
    "dance": ("舞蹈", 1004),
    "cinephile": ("影视", 1001),
    "ent": ("娱乐", 1002),
    "knowledge": ("知识", 1010),
    "tech": ("科技数码", 1012),
    "food": ("美食", 1020),
    "car": ("汽车", 1013),
    "fashion": ("时尚美妆", 1014),
    "sports": ("体育运动", 1018),
    "animal": ("动物", 1024),
}

# 番剧 / 影视排行:子榜 → (中文名, season_type)。番剧走旧接口 pgc/web/rank/list,其余走
# pgc/season/rank/web/list
PGC_RANKS: dict[str, tuple[str, int]] = {
    "bangumi": ("番剧", 1),
    "guochuang": ("国创", 4),
    "documentary": ("纪录片", 3),
    "movie": ("电影", 2),
    "tv": ("电视剧", 5),
    "variety": ("综艺", 7),
}

OTHER_RANKS: dict[str, str] = {
    "hot": "热搜",
    "popular": "综合热门",
    "weekly": "每周必看",
    "precious": "入站必刷",
    "article": "专栏热门",
}

# 声明序即榜单序,第一个是默认榜(/bilibili-rank/all)
BOARD_TYPES: dict[str, str] = {
    **{key: f"{name}排行" for key, (name, _rid) in VIDEO_RANKS.items()},
    **{key: f"{name}排行" for key, (name, _st) in PGC_RANKS.items()},
    **OTHER_RANKS,
}

DEFAULT_TYPE = next(iter(BOARD_TYPES))

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "哔哩哔哩",
    "description": "B 站排行榜（新版分区）、番剧影视排行、热搜、综合热门、每周必看、入站必刷",
    "link": "https://www.bilibili.com/v/popular/rank/all",
    "params": {"type": {"name": "榜单", "type": BOARD_TYPES}},
}

# 页面埋点位置标识:排行 / 热门页 333.934,搜索页 333.337;随参数参与 WBI 签名
# (热搜接口例外:web_location 在签名后追加,与浏览器 URL 里 w_rid/wts 夹在参数中间一致)
WEB_LOCATION = "333.934"
SEARCH_WEB_LOCATION = "333.337"

# 综合热门取前 5 页(每页 20 条)
POPULAR_PAGES = 5

# 上游 UA 黑名单会拦 python-httpx / python-requests 这类脚本库默认 UA(HTTP 412),
# 固定用桌面 Chrome UA(board_api 客户端矩阵实测)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# 接口 → 浏览器里发起它的页面地址(作为 Referer),按前缀匹配,先长后短。
# 不能用首页 https://www.bilibili.com/ 作 Referer:同一出口请求多了以后,首页 Referer
# 会被单独判 -352(board_api 两轮推翻性验证的时间线);页面地址在所有对照里都通过
_PAGE_REFERER: list[tuple[str, str]] = [
    ("/x/web-interface/popular/series", "https://www.bilibili.com/v/popular/weekly"),
    ("/x/web-interface/popular/precious", "https://www.bilibili.com/v/popular/history"),
    ("/x/web-interface/popular", "https://www.bilibili.com/v/popular/all"),
    ("/x/web-interface/wbi/search", "https://search.bilibili.com/all"),
    ("/x/web-interface/ranking", "https://www.bilibili.com/v/popular/rank/all"),
    ("/pgc/", "https://www.bilibili.com/v/popular/rank/all"),
]

# bootstrap(spi 取 buvid3 + nav 取 WBI 密钥)的缓存语义照 bilibili.py 的 get_bili_wbi
# 模式:先查共享缓存,未命中才发起两个请求。密钥按天轮换、buvid3 长期有效,默认 TTL 足够
_BOOTSTRAP_CACHE_KEY = "bilibili-rank-bootstrap"

# 遇 -352(风控)的退避秒数,重试前换一套 buvid 与密钥。board_api 建议 5s/20s;Core 在
# 请求路径上,收紧退避,仍失败就明确报错,交给调度器下一轮再试
_RETRY_WAITS_352 = (1.0, 5.0)

_sleep = asyncio.sleep


async def _fetch_bootstrap() -> dict[str, str]:
    """取设备标识与 WBI 密钥:finger/spi 给 buvid3,nav 给 img_key / sub_key(未登录也返回)。"""
    spi = await get(
        f"{API}/x/frontend/finger/spi",
        headers={"User-Agent": _USER_AGENT},
        no_cache=True,
        cache_key=f"{ROUTE_NAME}:spi",
    )
    spi_data = (spi.data or {}).get("data") or {}
    buvid3 = spi_data.get("b_3")
    if not buvid3:
        raise RuntimeError(f"Bilibili finger/spi returned no buvid3: {spi_data!r}")

    nav = await get(
        f"{API}/x/web-interface/nav",
        headers={"User-Agent": _USER_AGENT},
        no_cache=True,
        cache_key=f"{ROUTE_NAME}:nav",
    )
    wbi_img = ((nav.data or {}).get("data") or {}).get("wbi_img") or {}
    img_url: str = wbi_img.get("img_url") or ""
    sub_url: str = wbi_img.get("sub_url") or ""
    if not img_url or not sub_url:
        raise RuntimeError(f"Bilibili nav returned no wbi_img: {wbi_img!r}")
    img_key = img_url.rsplit("/", 1)[1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[1].split(".")[0]
    return {
        "buvid3": buvid3,
        "buvid4": spi_data.get("b_4") or "",
        "img_key": img_key,
        "sub_key": sub_key,
    }


async def _get_bootstrap(refresh: bool = False) -> dict[str, str]:
    if not refresh:
        cached = await cache.get(_BOOTSTRAP_CACHE_KEY)
        if cached and cached.data:
            return cached.data
    bootstrap = await _fetch_bootstrap()
    await cache.set(
        _BOOTSTRAP_CACHE_KEY,
        CacheData(update_time=datetime.now(UTC).isoformat(), data=bootstrap),
    )
    return bootstrap


async def _api_get(
    path: str,
    params: dict[str, str | int],
    no_cache: bool,
    cache_key: str,
    *,
    unsigned: dict[str, str] | None = None,
) -> tuple[object, dict]:
    """带 WBI 签名与 buvid cookie 的 GET;遇 -352 退避换 bootstrap 重试。

    返回 (RequestResult, payload)。响应不是 JSON 对象(挑战 / 风控页)或 code 非 0
    都按上游故障抛错,不静默降级为空榜。签名后追加的参数(热搜的 web_location)经
    *unsigned* 传入,不参与签名。
    """
    bootstrap = await _get_bootstrap()
    attempts = (0.0,) + _RETRY_WAITS_352
    result = None
    payload: dict = {}
    for index, wait in enumerate(attempts):
        if wait:
            await _sleep(wait)
            bootstrap = await _get_bootstrap(refresh=True)
        query = _enc_wbi(dict(params), bootstrap["img_key"], bootstrap["sub_key"])
        if unsigned:
            query += "".join(f"&{key}={value}" for key, value in unsigned.items())
        headers = {
            "User-Agent": _USER_AGENT,
            "Cookie": (
                f"buvid3={bootstrap['buvid3']}; buvid4={bootstrap['buvid4']};"
                f" b_nut={int(time.time())}"
            ),
        }
        referer = next(
            (ref for prefix, ref in _PAGE_REFERER if path.startswith(prefix)), None
        )
        if referer:
            headers["Referer"] = referer
        result = await get(
            f"{API}{path}?{query}",
            headers=headers,
            no_cache=no_cache,
            cache_key=cache_key,
        )
        payload = result.data if isinstance(result.data, dict) else {}
        code = payload.get("code")
        if code == 0:
            return result, payload
        if code != -352 or index == len(attempts) - 1:
            break
    hint = (
        "risk control (-352); wait a few minutes and retry"
        if payload.get("code") == -352
        else "unexpected response envelope"
    )
    raise RuntimeError(
        f"Bilibili API {path} failed: code={payload.get('code')} "
        f"message={payload.get('message')!r} ({hint})"
    )


def _https(url: str | None) -> str | None:
    return url.replace("http://", "https://", 1) if url else None


def _rcmd_reason(row: dict) -> str | None:
    # 综合热门是 {"content": ...},每周必看是纯字符串;防御两种形态
    raw = row.get("rcmd_reason")
    if isinstance(raw, dict):
        return (raw.get("content") or "").strip() or None
    if isinstance(raw, str) and raw.strip():
        return raw
    return None


def _video_item(row: dict, reason: str | None = None) -> ListItem:
    # 字段口径照 board_api:hot=播放数,author=UP 主,timestamp=发布时间;
    # desc 优先放推荐理由(综合热门 / 每周必看 / 入站必刷才有),否则视频简介
    bvid = row.get("bvid") or ""
    stat = row.get("stat") if isinstance(row.get("stat"), dict) else {}
    return ListItem(
        id=bvid,
        title=row.get("title") or "",
        url=f"https://www.bilibili.com/video/{bvid}",
        mobileUrl=f"https://m.bilibili.com/video/{bvid}",
        hot=stat.get("view"),
        cover=_https(row.get("pic")),
        author=((row.get("owner") or {}).get("name")),
        desc=reason or row.get("desc"),
        timestamp=get_time(row.get("pubdate")),
    )


async def _fetch_video_board(key: str, rid: int, no_cache: bool) -> dict:
    # type=all 是页面上的"全部"排行;rid 是新版分区 ID
    result, payload = await _api_get(
        "/x/web-interface/ranking/v2",
        {"rid": rid, "type": "all", "web_location": WEB_LOCATION},
        no_cache,
        f"{ROUTE_NAME}:ranking:{key}",
    )
    rows = (payload.get("data") or {}).get("list") or []
    return {
        "type": f"排行榜 · {VIDEO_RANKS[key][0]}",
        "data": [_video_item(row) for row in rows],
        "from_cache": result.from_cache,
        "update_time": result.update_time,
    }


async def _fetch_pgc_board(key: str, season_type: int, no_cache: bool) -> dict:
    # day=3:统计周期(三日),页面固定传 3
    path = "/pgc/web/rank/list" if season_type == 1 else "/pgc/season/rank/web/list"
    result, payload = await _api_get(
        path,
        {"day": 3, "season_type": season_type, "web_location": WEB_LOCATION},
        no_cache,
        f"{ROUTE_NAME}:pgc:{key}",
    )
    # 番剧旧接口信封是 result,其余是 data
    rows = ((payload.get("result") or payload.get("data") or {}).get("list")) or []
    items = []
    for row in rows:
        season_id = row.get("season_id")
        # desc:评分 · 更新进度 · 徽章
        extra = " · ".join(
            str(part)
            for part in (
                row.get("rating"),
                (row.get("new_ep") or {}).get("index_show"),
                row.get("badge"),
            )
            if part
        )
        url = row.get("url") or f"https://www.bilibili.com/bangumi/play/ss{season_id}"
        items.append(
            ListItem(
                id=season_id,
                title=row.get("title") or "",
                url=url,
                mobileUrl=f"https://m.bilibili.com/bangumi/play/ss{season_id}",
                hot=(row.get("stat") or {}).get("view"),
                cover=_https(row.get("cover")),
                desc=extra or None,
            )
        )
    return {
        "type": f"排行榜 · {PGC_RANKS[key][0]}",
        "data": items,
        "from_cache": result.from_cache,
        "update_time": result.update_time,
    }


async def _fetch_hot_search(no_cache: bool) -> dict:
    # 热搜只对 limit / platform / wts 签名,web_location 在签名后追加(与浏览器一致);
    # limit 实测最大 50
    result, payload = await _api_get(
        "/x/web-interface/wbi/search/square",
        {"limit": 50, "platform": "web"},
        no_cache,
        f"{ROUTE_NAME}:hot",
        unsigned={"web_location": SEARCH_WEB_LOCATION},
    )
    rows = ((payload.get("data") or {}).get("trending") or {}).get("list") or []
    items = []
    for row in rows:
        keyword = row.get("keyword") or ""
        items.append(
            ListItem(
                id=keyword,
                title=row.get("show_name") or keyword,
                url=f"https://search.bilibili.com/all?keyword={quote(keyword)}",
                mobileUrl=f"https://m.bilibili.com/search?keyword={quote(keyword)}",
                hot=row.get("heat_score"),
            )
        )
    return {
        "type": "热搜",
        "data": items,
        "from_cache": result.from_cache,
        "update_time": result.update_time,
    }


async def _fetch_popular(no_cache: bool) -> dict:
    items: list[ListItem] = []
    from_cache = True
    update_time = ""
    # 综合热门带 buvid3 与不带时是两份不同口径的列表;原站 /v/popular/all 页面展示的
    # 是带 buvid3 那份(board_api 浏览器抓包 20/20 逐位相同),数据口径以原站为准
    for pn in range(1, POPULAR_PAGES + 1):
        # ps:每页条数(页面固定 20);pn:页码
        result, payload = await _api_get(
            "/x/web-interface/popular",
            {"ps": 20, "pn": pn, "web_location": WEB_LOCATION},
            no_cache,
            f"{ROUTE_NAME}:popular:pn{pn}",
        )
        from_cache = from_cache and result.from_cache
        update_time = result.update_time
        data = payload.get("data") or {}
        items += [
            _video_item(row, _rcmd_reason(row)) for row in data.get("list") or []
        ]
        if data.get("no_more"):
            break
    seen: set[str] = set()  # 翻页间偶有重复稿件,按 bvid 去重
    data = [item for item in items if not (item.id in seen or seen.add(item.id))]
    return {
        "type": "综合热门",
        "data": data,
        "from_cache": from_cache,
        "update_time": update_time,
    }


async def _fetch_weekly(no_cache: bool) -> dict:
    # 期数列表按期号倒序,第一项就是最新一期
    _result, payload = await _api_get(
        "/x/web-interface/popular/series/list",
        {"web_location": WEB_LOCATION},
        no_cache,
        f"{ROUTE_NAME}:weekly-list",
    )
    series_list = (payload.get("data") or {}).get("list") or []
    number = (series_list[0] or {}).get("number") if series_list else None
    if not number:
        raise RuntimeError("Bilibili weekly series/list returned no issue number")
    result, payload = await _api_get(
        "/x/web-interface/popular/series/one",
        {"number": number, "web_location": WEB_LOCATION},
        no_cache,
        f"{ROUTE_NAME}:weekly:{number}",
    )
    data = payload.get("data") or {}
    label = (data.get("config") or {}).get("label") or f"第{number}期"
    return {
        "type": f"每周必看 · {label}",
        "data": [_video_item(row, _rcmd_reason(row)) for row in data.get("list") or []],
        "from_cache": result.from_cache,
        "update_time": result.update_time,
    }


async def _fetch_precious(no_cache: bool) -> dict:
    result, payload = await _api_get(
        "/x/web-interface/popular/precious",
        {"page_size": 100, "page": 1, "web_location": WEB_LOCATION},
        no_cache,
        f"{ROUTE_NAME}:precious",
    )
    rows = (payload.get("data") or {}).get("list") or []
    # 入站必刷的 desc 放成就语(achievement)
    return {
        "type": "入站必刷",
        "data": [_video_item(row, row.get("achievement") or None) for row in rows],
        "from_cache": result.from_cache,
        "update_time": result.update_time,
    }


async def _fetch_article(no_cache: bool) -> dict:
    # 专栏排行页 /read/ranking 已 404;接口仍在更新,但 cid(月/周/昨日/前日)已不区分,
    # 返回同一份列表。该接口不带 WBI 签名
    result = await get(
        f"{API}/x/article/rank/list",
        params={"cid": 1},
        headers={"User-Agent": _USER_AGENT},
        no_cache=no_cache,
        cache_key=f"{ROUTE_NAME}:article",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("code") != 0:
        raise RuntimeError(
            f"Bilibili API /x/article/rank/list failed: code={payload.get('code')} "
            f"message={payload.get('message')!r}"
        )
    items = []
    for row in payload.get("data") or []:
        article_id = row.get("id")
        images = row.get("image_urls") or []
        url = f"https://www.bilibili.com/read/cv{article_id}"
        items.append(
            ListItem(
                id=f"cv{article_id}",
                title=row.get("title") or "",
                url=url,
                mobileUrl=url,
                hot=(row.get("stats") or {}).get("view"),
                cover=_https(row.get("banner_url") or (images[0] if images else None)),
                author=((row.get("author") or {}).get("name")),
                desc=row.get("summary"),
                timestamp=get_time(row.get("publish_time")),
            )
        )
    return {
        "type": "专栏热门",
        "data": items,
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "message": "原专栏排行页已下线,接口不再区分月 / 周 / 日",
    }


async def _fetch_board(type_param: str, no_cache: bool) -> dict:
    if type_param in VIDEO_RANKS:
        return await _fetch_video_board(type_param, VIDEO_RANKS[type_param][1], no_cache)
    if type_param in PGC_RANKS:
        return await _fetch_pgc_board(type_param, PGC_RANKS[type_param][1], no_cache)
    fetcher = {
        "hot": _fetch_hot_search,
        "popular": _fetch_popular,
        "weekly": _fetch_weekly,
        "precious": _fetch_precious,
        "article": _fetch_article,
    }[type_param]
    return await fetcher(no_cache)


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", DEFAULT_TYPE)
    if type_param not in BOARD_TYPES:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    fetched = await _fetch_board(type_param, no_cache)
    if not fetched["data"]:
        # 空列表大概率是风控空壳,按上游故障处理,不静默降级为空榜
        raise RuntimeError(
            f"Bilibili board '{type_param}' returned no items (possible risk-control shell)"
        )
    logger.info(f"✅ [bilibili-rank] {type_param}: {len(fetched['data'])} items")
    return RouterData(
        **ROUTE_META,
        type=fetched["type"],
        total=len(fetched["data"]),
        fromCache=fetched["from_cache"],
        updateTime=fetched["update_time"],
        data=fetched["data"],
        message=fetched.get("message"),
    )

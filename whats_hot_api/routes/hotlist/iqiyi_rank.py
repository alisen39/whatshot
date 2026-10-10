from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.logger import logger

ROUTE_NAME = "iqiyi-rank"

API = "https://mesh.if.iqiyi.com/portal/pcw/rankList/comSecRankList"
SITE_LINK = "https://www.iqiyi.com/ranks1/-1/0"

# 频道键 -> (cid, 页面上的频道名)。cid 取自页面导航 navs;总榜的 cid 是 -1,
# 但请求里 channelId 固定传 0(照页面脚本 channelId:"-1"===cid?0:cid)
CHANNELS: dict[str, tuple[int, str]] = {
    "all": (-1, "总榜"),
    "tv": (2, "电视剧"),
    "movie": (1, "电影"),
    "variety": (6, "综艺"),
    "cartoon": (4, "动漫"),
    "child": (15, "少儿"),
    "doc": (3, "纪录片"),
    "knowledge": (912, "知识"),
}

# 子榜键 -> (频道键, 榜 id, 页面上的榜名)。固定榜 id:热播 0、飙升 -1、高分 -4、
# 必看 -6、期待 -8、上新 -5;标签榜 id 取自页面导航 navs[].tagList[].tagId。
# 以下 6 个 id 导航里没有页签,只有旧地址(须与榜名一致,原站随时可能改指向别的列表):
# tv-costume / tv-romance / variety-iqiyi-made / movie-new / child-new / cartoon-workplace。
# 电视剧悬疑榜(3233)、动漫日本榜(3833)是改名前旧 id,与现行悬疑罪案榜、日漫榜逐条相同,取现行 id
BOARDS: dict[str, tuple[str, str, str]] = {
    "all-hot": ("all", "0", "热播榜"),
    "all-rise": ("all", "-1", "飙升榜"),
    "all-must": ("all", "-6", "必看榜"),
    "all-expect": ("all", "-8", "期待榜"),
    "tv-hot": ("tv", "0", "热播榜"),
    "tv-rise": ("tv", "-1", "飙升榜"),
    "tv-must": ("tv", "-6", "必看榜"),
    "tv-score": ("tv", "-4", "高分榜"),
    "tv-police": ("tv", "7245663290192433", "警匪榜"),
    "tv-suspense": ("tv", "5836257895783433", "悬疑罪案榜"),
    "tv-costume": ("tv", "2289882683101933", "古装榜"),
    "tv-romance": ("tv", "8732878771828133", "爱情榜"),
    "movie-hot": ("movie", "0", "热播榜"),
    "movie-rise": ("movie", "-1", "飙升榜"),
    "movie-must": ("movie", "-6", "必看榜"),
    "movie-score": ("movie", "-4", "高分榜"),
    "movie-gunfight": ("movie", "8201844980650933", "枪战榜"),
    "movie-action": ("movie", "7086834452347833", "动作榜"),
    "movie-scifi": ("movie", "2771984357569433", "科幻榜"),
    "movie-fantasy": ("movie", "8035796650176933", "奇幻榜"),
    "movie-youth": ("movie", "8902937931540733", "青春榜"),
    "movie-new": ("movie", "-5", "上新榜"),
    "variety-hot": ("variety", "0", "热播榜"),
    "variety-rise": ("variety", "-1", "飙升榜"),
    "variety-must": ("variety", "-6", "必看榜"),
    "variety-music": ("variety", "1733179584798033", "音乐榜"),
    "variety-culture": ("variety", "1026471472974333", "文化榜"),
    "variety-food": ("variety", "1295197031954033", "美食榜"),
    "variety-puzzle": ("variety", "8540358968380133", "益智榜"),
    "variety-reality": ("variety", "7220796148913633", "真人秀榜"),
    "variety-comedy": ("variety", "4749323172149933", "搞笑榜"),
    "variety-iqiyi-made": ("variety", "3027933", "爱奇艺出品榜"),
    "cartoon-hot": ("cartoon", "0", "热播榜"),
    "cartoon-rise": ("cartoon", "-1", "飙升榜"),
    "cartoon-score": ("cartoon", "-4", "高分榜"),
    "cartoon-japan": ("cartoon", "6234934322090433", "日漫榜"),
    "cartoon-action": ("cartoon", "7086834452347833", "动作榜"),
    "cartoon-romance": ("cartoon", "1843878471780633", "恋爱榜"),
    "cartoon-adventure": ("cartoon", "5354958387163433", "冒险榜"),
    "cartoon-fantasy": ("cartoon", "8035796650176933", "奇幻榜"),
    "cartoon-comedy": ("cartoon", "1708312443519433", "搞笑榜"),
    "cartoon-workplace": ("cartoon", "3025633", "职场榜"),
    "child-hot": ("child", "0", "热播榜"),
    "child-rise": ("child", "-1", "飙升榜"),
    "child-score": ("child", "-4", "高分榜"),
    "child-age7to10": ("child", "2913165546764733", "7-10岁榜"),
    "child-puzzle": ("child", "3822019452208733", "益智榜"),
    "child-cartoon": ("child", "7418128947447833", "动画片榜"),
    "child-movie": ("child", "4633009124233433", "少儿电影榜"),
    "child-song": ("child", "2475985159768133", "儿歌榜"),
    "child-music": ("child", "1247067081091833", "音乐榜"),
    "child-new": ("child", "-5", "上新榜"),
    "doc-hot": ("doc", "0", "热播榜"),
    "doc-rise": ("doc", "-1", "飙升榜"),
    "doc-score": ("doc", "-4", "高分榜"),
    "knowledge-hot": ("knowledge", "0", "热度榜"),
    "knowledge-rise": ("knowledge", "-1", "飙升榜"),
}

# 声明序即榜单序,第一个是默认榜(/iqiyi-rank/all-hot)
BOARD_TYPES: dict[str, str] = {
    key: f"{CHANNELS[channel][1]} · {name}" for key, (channel, _tag, name) in BOARDS.items()
}

DEFAULT_TYPE = next(iter(BOARD_TYPES))

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "爱奇艺风云榜",
    "description": (
        "爱奇艺风云榜:总榜、电视剧、电影、综艺、动漫、少儿、纪录片、知识 8 个频道的"
        "热播、飙升、高分、必看、期待、上新榜和标签榜(第 1 页 25 条)"
    ),
    "link": SITE_LINK,
    "params": {"type": {"name": "榜单", "type": BOARD_TYPES}},
}

# 地区口径(board_api 推翻性验证):接口按访问者地区出榜,ip 参数为空时按请求方 IP 定位,
# 海外 IP 得到按海外版权过滤后的另一份列表(56 个榜只有 4 个两版相同,电影必看 0 重合,
# 海外版 9 个榜不足 25 条);本机出口分流时同一请求隔几分钟会在两版间切换。
# 固定传一个大陆 IP(202.106.0.20,北京联通 DNS),输出大陆访客看到的版本,不依赖出口。
# 换成海外 IP(如 1.1.1.1)得到的是 tophub 抓取的海外版
REGION_IP = "202.106.0.20"

# indexType 语义:1 实时热度、5 最高热度是热度值;2 飙升幅度(%)、3 推荐分(9.7 这类)、
# 8 期待榜综合值(预约人数)不是热度,hot 留空
HEAT_INDEX_TYPES = {"1", "5"}

# 偶发 code=-1 "error"(board_api 实测翻页时出现过);首页偶发同样按上游瞬时故障重试,
# 隔 2 秒重试 2 次,仍失败就明确报错
_RETRY_WAITS = (0.0, 2.0, 2.0)

_sleep = asyncio.sleep


def _page_url(board_key: str) -> str:
    channel, tag, _name = BOARDS[board_key]
    return f"https://www.iqiyi.com/ranks1/{CHANNELS[channel][0]}/{tag}"


def _api_params(board_key: str) -> dict[str, str]:
    channel, tag, _name = BOARDS[board_key]
    cid = CHANNELS[channel][0]
    # 照页面脚本 getRanks1Id 的公共参数:v=1、device/auth/uid 是登录态留空、
    # refresh=0、server=false、date 是票房类榜子日期留空、pg_num 固定第 1 页;
    # tag 与 page_st 同值(tag 服务端不看,照页面带上);总榜 channelId 传 0
    return {
        "v": "1",
        "device": "",
        "auth": "",
        "uid": "",
        "ip": REGION_IP,
        "refresh": "0",
        "server": "false",
        "category_id": str(cid),
        "channelId": "0" if cid == -1 else str(cid),
        "page_st": tag,
        "tag": tag,
        "date": "",
        "pg_num": "1",
    }


def _https_url(url: str) -> str:
    """页面里是 //www.iqiyi.com/v_….html(https 页面下即 https),接口给 http://,统一成 https。"""
    url = (url or "").strip()
    if url.startswith("//"):
        return f"https:{url}"
    hostname = urlsplit(url).hostname if url.startswith("http://") else None
    if hostname and hostname.endswith("iqiyi.com"):
        return f"https://{url[len('http://'):]}"
    return url


def _parse_items(contents: list[dict], board_key: str) -> list[ListItem]:
    page = _page_url(board_key)
    items: list[ListItem] = []
    for position, row in enumerate(contents, start=1):
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        # 期待榜未上线的片子没有 pageUrl,页面上是空 href(指回榜单页),同样指回榜单页
        url = _https_url(str(row.get("pageUrl") or "")) or page
        index_type = str(row.get("indexType") or "")
        heat = row.get("mainIndex") if index_type in HEAT_INDEX_TYPES else None
        description = str(row.get("desc") or "").strip() or None
        reason = str(row.get("promptDesc") or "").strip() or None
        badges = _badge_texts(row)
        items.append(
            ListItem(
                id=str(row.get("id") or row.get("aid") or row.get("tvid") or url),
                title=title,
                url=url,
                mobileUrl=url,
                hot=heat,
                hotLabel=INDEX_TYPE_LABELS.get(index_type, "热度"),
                badges=badges,
                sourceRank=_positive_int(row.get("order")) or position,
                metrics=_index_metrics(row, index_type),
                # desc 没有时取 promptDesc(推荐语)进 desc;两者都有时推荐语单列
                desc=description or reason,
                recommendationReason=reason if description and reason else None,
                cover=_https_url(str(row.get("img") or "")) or None,
                # 主演只在各频道格式不一的 tags 字符串里,条目是作品没有发布时间
            )
        )
    return items


INDEX_TYPE_LABELS = {
    "1": "实时热度",
    "5": "最高热度",
    "2": "飙升幅度",
    "3": "推荐分",
    "8": "期待值",
}


def _badge_texts(row: dict) -> list[dict] | None:
    # 角标文案(弹幕量/上新标记等)逐字保留;空串与缺失一律不造
    texts = [
        str(row.get(key) or "").strip()
        for key in ("bulletIndex", "recIndex", "onlineTimeTag", "theaterTag")
    ]
    badges = [{"text": text} for text in texts if text]
    return badges or ([] if any(key in row for key in ("bulletIndex", "recIndex")) else None)


def _index_metrics(row: dict, index_type: str) -> dict[str, int] | None:
    metrics: dict[str, int] = {}
    if index_type not in HEAT_INDEX_TYPES:
        value = _positive_int(row.get("mainIndex"))
        if value is not None:
            metrics["index"] = value
    want = _positive_int(row.get("orderPeopleCount"))
    if want is not None:
        metrics["want"] = want
    return metrics or None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


async def _fetch_board(board_key: str, no_cache: bool) -> dict:
    channel, _tag, name = BOARDS[board_key]
    result = None
    payload: dict = {}
    card: dict = {}
    for wait in _RETRY_WAITS:
        if wait:
            await _sleep(wait)
        result = await get(
            API,
            params=_api_params(board_key),
            headers={"Accept": "application/json, text/plain, */*"},
            no_cache=no_cache,
            cache_key=f"{ROUTE_NAME}:{board_key}",
        )
        payload = result.data if isinstance(result.data, dict) else {}
        cards = (payload.get("data") or {}).get("items") or []
        card = cards[0] if cards and isinstance(cards[0], dict) else {}
        if str(payload.get("code")) == "0" and card.get("contents"):
            break
    if not card.get("contents"):
        # 错误壳 / 空列表按上游故障抛错,不静默降级为空榜
        raise RuntimeError(
            f"iQiyi rank board '{board_key}' returned no list: "
            f"code={payload.get('code')} msg={payload.get('msg')!r} (page {_page_url(board_key)})"
        )
    items = _parse_items(card["contents"], board_key)
    if not items:
        raise RuntimeError(f"iQiyi rank board '{board_key}' parsed no items (page {_page_url(board_key)})")
    return {
        "type": f"{CHANNELS[channel][1]} · {name}",
        "data": items,
        "from_cache": result.from_cache,
        "update_time": result.update_time,
    }


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", DEFAULT_TYPE)
    if type_param not in BOARDS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    fetched = await _fetch_board(type_param, no_cache)
    logger.info(f"✅ [iqiyi-rank] {type_param}: {len(fetched['data'])} items")
    return RouterData(
        **ROUTE_META,
        type=fetched["type"],
        total=len(fetched["data"]),
        fromCache=fetched["from_cache"],
        updateTime=fetched["update_time"],
        data=fetched["data"],
    )

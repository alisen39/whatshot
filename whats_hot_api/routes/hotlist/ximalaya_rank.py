from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "ximalaya-rank"

# 喜马拉雅上一代(v2)排行榜接口,对应 tophub 喜马拉雅的 12 个"{分类}{榜型}"榜。
# 现行网页版 /top/ 与 m 站已改用 v4 榜单,页面上看不到这些榜,但 v2 接口仍可访问
# (board_api/ximalaya_rank 验证,2026-09-27)。
_API = "https://www.ximalaya.com/revision/rank/v2/element/code"
_IMAGE = "https://imagev2.xmcdn.com/"
_SITE = "https://www.ximalaya.com"
_MOBILE = "https://m.ximalaya.com"

# 子榜键 = {typeCode}-{分类};值依次:中文名、typeCode、clusterCode、返回里应有的 clusterId。
# typeCode 取自 /revision/rank/v2/cluster 的 rankClusterTypeCode,clusterCode 取自 categoryCode
# (没有分类的"热门""总榜""新品"用分类 ID 字符串)。clusterCode 写错时服务端不报错,
# 而是静默退回"热门"(clusterId=65,飙升榜退回总榜 155),因此必须核对返回的 clusterId。
_BOARDS: dict[str, tuple[str, str, str, int]] = {
    "free-hot": ("热门免费榜", "free", "65", 65),
    "free-toutiao": ("头条免费榜", "free", "toutiao", 66),
    "free-yule": ("娱乐免费榜", "free", "yule", 69),
    "free-yingshi": ("影视免费榜", "free", "yingshi", 88),
    "free-youshengshu": ("有声书免费榜", "free", "youshengshu", 68),
    "free-xiangsheng": ("相声评书免费榜", "free", "xiangsheng", 77),
    "free-yinyue": ("音乐免费榜", "free", "yinyue", 67),
    "rich-all": ("总榜飙升榜", "rich", "155", 155),
    "rich-new": ("新品飙升榜", "rich", "157", 157),
    "paid-hot": ("热门付费榜", "paid", "95", 95),
    "subscription-hot": ("热门订阅榜", "subscription", "217", 217),
    "reputation-hot": ("热门好评榜", "reputation", "248", 248),
}

type_map: dict[str, str] = {key: board[0] for key, board in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "喜马拉雅",
    "description": "喜马拉雅分类排行榜(免费、飙升、付费、订阅、好评)",
    "link": "https://www.ximalaya.com/top/",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

_HEADERS = {
    # UA 不区分大小写地含 "python" 时接口返回 200 空响应(httpx 默认 UA 就会被拦),
    # 必须显式带浏览器 UA(board_api 验证,param_matrix.log)。
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    # Referer 实测非必需,照带网页版排行页(board_api 验证,drop_referer 结果相同)。
    "Referer": "https://www.ximalaya.com/top/",
}


def _cover(path: object) -> str | None:
    """封面字段是相对 imagev2.xmcdn.com 的路径,或以 //、http(s):// 开头的路径。"""
    if not isinstance(path, str) or not path.strip():
        return None
    if path.startswith(("http://", "https://")):
        return path
    if path.startswith("//"):
        return f"https:{path}"
    return _IMAGE + path.lstrip("/")


def _album_item(album: dict) -> ListItem:
    album_id = str(album.get("id") or "").strip()
    # 接口没有专辑发布时间(lastUptrackAtStr 是"3天前"这类模糊文字),timestamp 留空
    return ListItem(
        id=album_id,
        title=str(album.get("albumTitle") or ""),
        url=f"{_SITE}/album/{album_id}",
        mobileUrl=f"{_MOBILE}/album/{album_id}",
        hot=album.get("playCount"),
        cover=_cover(album.get("cover")),
        author=str(album.get("anchorName") or "") or None,
        desc=str(album.get("description") or "") or None,
    )


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "free-hot")
    if type_param not in _BOARDS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    label, type_code, cluster_code, cluster_id = _BOARDS[type_param]
    result = await get(
        url=_API,
        params={"typeCode": type_code, "clusterCode": cluster_code},
        headers=_HEADERS,
        no_cache=no_cache,
        cache_key=f"{ROUTE_NAME}:{type_param}",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("ret") != 200:
        # 错误壳(ret=403/500 等);UA 被拦时的 200 空响应会在 http_client 解析 JSON 时报错
        raise RuntimeError(
            f"Ximalaya rank returned ret={payload.get('ret')} msg={payload.get('msg')!r}"
        )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    rank_list = data.get("rankList") if isinstance(data.get("rankList"), list) else []
    # clusterCode 写错/分类改名时静默退回"热门",必须核对 clusterId(board_api 验证)
    if not rank_list or data.get("clusterId") != cluster_id:
        raise RuntimeError(
            f"Ximalaya rank {type_param} (typeCode={type_code}, "
            f"clusterCode={cluster_code}) returned clusterId={data.get('clusterId')} "
            f"with {len(rank_list)} rank list(s), expected clusterId={cluster_id}; "
            "category code may have changed, check /revision/rank/v2/cluster"
        )
    rank = rank_list[0] if isinstance(rank_list[0], dict) else {}
    albums = rank.get("albums") if isinstance(rank.get("albums"), list) else []
    data_items: list[ListItem] = []
    for album in albums:
        if not isinstance(album, dict) or not str(album.get("id") or "").strip():
            continue
        data_items.append(_album_item(album))
    if not data_items:
        raise RuntimeError(f"Ximalaya rank {label} returned no items")
    # ids 是名次名单,albums 只含接口给出详情的条目;差值(已删除、下架、"围栏"专辑)
    # 是上游常态而非错误,写进 message 备查(board_api 全量核对,verify/full_count_check.log)
    rank_ids = rank.get("ids") if isinstance(rank.get("ids"), list) else []
    dropped = len(rank_ids) - len(data_items)
    message = (
        f"{rank.get('title') or label}:名次名单 {len(rank_ids)} 个,其中 {dropped} 个"
        "接口不给详情(已删除、下架等)"
        if dropped > 0
        else None
    )
    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(data_items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data_items,
        message=message,
    )

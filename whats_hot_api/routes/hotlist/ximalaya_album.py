from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "ximalaya-album"

# 喜马拉雅移动端"专辑最新节目"接口,对应 tophub "喜马拉雅 ‧ 雪球"节点(DOvny8qoEB):
# 条目是专辑 299146《雪球·财经有深度》的最新单集(/sound/{trackId}),不是排行榜
# (board_api/ximalaya_album 验证,2026-09-27)。网页接口 getTracksList 返回 407
# "webtk缺失",m 站节目接口 403,播客 RSS 整份 25.7MB,均不采用。
_API = "https://mobile.ximalaya.com/mobile/v1/album/track"
_SITE = "https://www.ximalaya.com"
_MOBILE = "https://m.ximalaya.com"
_PAGE_SIZE = 20

# 子榜键 -> (专辑 ID, 专辑名)。要加别的专辑,在这里加一行(board_api 同款设计)
_ALBUMS: dict[str, tuple[str, str]] = {
    "xueqiu": ("299146", "雪球·财经有深度"),
}

type_map: dict[str, str] = {key: album[1] for key, album in _ALBUMS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "喜马拉雅",
    "description": "喜马拉雅专辑的最新节目",
    "link": "https://www.ximalaya.com/",
    "params": {
        "type": {
            "name": "专辑",
            "type": type_map,
        },
    },
}

_HEADERS = {
    # UA 不限(不带 UA、python-httpx 都 200),统一带浏览器 UA
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
}


def _track_item(track: dict) -> ListItem:
    track_id = str(track.get("trackId") or "").strip()
    # coverLarge → coverMiddle 逐级回退;封面字段是 http://,升级成 https(board_api 做法)
    cover = track.get("coverLarge") or track.get("coverMiddle") or None
    if isinstance(cover, str):
        cover = cover.replace("http://", "https://", 1)
    else:
        cover = None
    return ListItem(
        id=track_id,
        title=str(track.get("title") or ""),
        url=f"{_SITE}/sound/{track_id}",
        mobileUrl=f"{_MOBILE}/sound/{track_id}",
        hot=track.get("playtimes"),
        author=str(track.get("nickname") or "") or None,
        cover=cover,
        desc=str(track.get("intro") or "").strip() or None,
        timestamp=get_time(track.get("createdAt")),
    )


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "xueqiu")
    if type_param not in _ALBUMS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    album_id, album_title = _ALBUMS[type_param]
    # 最新在前是缺省排序;显式写 isAsc=true 防缺省变化(false 会从现存最早的第 24 期开始,
    # board_api 推翻性验证)。不传 pageSize 时每页 15 条,固定传 20 取最新一页。
    result = await get(
        url=_API,
        params={"albumId": album_id, "pageId": 1, "pageSize": _PAGE_SIZE, "isAsc": "true"},
        headers=_HEADERS,
        no_cache=no_cache,
        cache_key=f"{ROUTE_NAME}:{type_param}",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    # 注意:该接口成功是 ret=0,与排行 v2 接口的 ret=200 不同(board_api 验证)
    if payload.get("ret") != 0:
        raise RuntimeError(
            f"Ximalaya album track returned ret={payload.get('ret')} msg={payload.get('msg')!r}"
        )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    tracks = data.get("list") if isinstance(data.get("list"), list) else []
    data_items: list[ListItem] = []
    for track in tracks:
        if not isinstance(track, dict) or not str(track.get("trackId") or "").strip():
            continue
        data_items.append(_track_item(track))
    if not data_items:
        raise RuntimeError(f"Ximalaya album {album_id} ({album_title}) returned no tracks")
    meta = {**ROUTE_META, "link": f"{_SITE}/album/{album_id}"}
    return RouterData(
        **meta,
        type=album_title,
        total=len(data_items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data_items,
    )

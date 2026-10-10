"""网易云音乐官方榜单。

网页版音乐云自己使用的公开 JSON 接口,不加密(不走 weapi)、不登录、不带 cookie
(board_api/netease_music 证据)。每个榜单对应一个官方歌单:

1. ``/api/v6/playlist/detail?id=<榜单 id>&n=1000``:``trackIds`` 是榜单全量曲目 id
   (原站顺序,与网页"N首歌"一致),``tracks`` 只给前 n 首详情;约 39 个受限榜匿名只给
   10 首详情。
2. 缺的详情用 ``/api/v3/song/detail?c=[{"id":..}]`` 补(一次 200 个);v3 偶发漏个别歌
   (verify/v3_missing_song.md),再由旧接口 ``/api/song/detail?ids=[..]`` 兜底。
   不存在的 id 两个接口都不返回,该曲跳过并写入 message,不让整个榜报错。
3. 旧接口 ``/api/playlist/detail`` 匿名只给 10 首且把 trackCount 改成 10,不能用。

榜单 id 写死在 ``_BOARDS``,取自 ``/api/toplist`` 目录;按 id 取数、不按名称匹配
("网易云ACG VOCALOID榜"名称含不换行空格,星云榜名称随期数变)。4 个停更榜
(KTV唛榜/LOOK直播歌曲榜/喜力星电音派对潮音榜/星云榜)不在列,见 board_api README
"不做的榜"。
"""
from __future__ import annotations

import json

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import RequestResult, get

ROUTE_NAME = "netease-music-toplist"

# 子榜 -> (榜单 id, 中文名)。id 取自 /api/toplist,声明序第一个是默认榜
_BOARDS: dict[str, tuple[int, str]] = {
    "soaring": (19723756, "飙升榜"),
    "new": (3779629, "新歌榜"),
    "original": (2884035, "原创榜"),
    "hot": (3778678, "热歌榜"),
    "classical": (71384707, "网易云古典榜"),
    "electronic": (1978921795, "网易云电音榜"),
    "chinese-rap": (991319590, "网易云中文说唱榜"),
    "global-rap": (14028249541, "网易云全球说唱榜"),
    "trend": (13372522766, "潮流风向榜"),
    "partner-recommend": (12911403728, "音乐合伙人推荐榜"),
    "partner-hot": (12911589513, "音乐合伙人热歌榜"),
    "partner-credited": (12911619970, "音乐合伙人留名榜"),
    "partner-top-rated-new": (12911379734, "音乐合伙人高分新歌榜"),
    "partner-top-rated": (12768855486, "音乐合伙人高分榜"),
    "vip-most-played": (5453912201, "黑胶VIP爱听榜"),
    "acg": (71385702, "网易云ACG榜"),
    "korean": (745956260, "网易云韩语榜"),
    "uk-weekly": (180106, "UK排行榜周榜"),
    "billboard": (60198, "美国Billboard榜"),
    "beatport": (3812895, "Beatport全球电子舞曲榜"),
    "oricon": (60131, "日本Oricon榜"),
    "western-hot": (2809513713, "网易云欧美热歌榜"),
    "western-new": (2809577409, "网易云欧美新歌榜"),
    "nrj-vos-hits": (27135204, "法国 NRJ Vos Hits 周榜"),
    "acg-anime": (3001835560, "网易云ACG动画榜"),
    "acg-game": (3001795926, "网易云ACG游戏榜"),
    "acg-vocaloid": (3001890046, "网易云ACG VOCALOID榜"),
    "japanese": (5059644681, "网易云日语榜"),
    "rock": (5059633707, "网易云摇滚榜"),
    "guofeng": (5059642708, "网易云国风榜"),
    "potential-hits": (5338990334, "潜力爆款榜"),
    "folk": (5059661515, "网易云民谣榜"),
    "song-recognition": (6688069460, "听歌识曲榜"),
    "internet-hot": (6723173524, "网络热歌榜"),
    "russian": (6732051320, "俄语榜"),
    "vietnamese": (6732014811, "越南语榜"),
    "chinese-dj": (6886768100, "中文慢摇DJ榜"),
    "russia-top-hit": (6939992364, "俄罗斯top hit流行音乐榜"),
    "thai": (7095271308, "泰语榜"),
    "beat": (7356827205, "BEAT排行榜"),
    "shangyin": (7775163417, "赏音榜"),
    "vip-new": (7785123708, "黑胶VIP新歌榜"),
    "vip-hot": (7785066739, "黑胶VIP热歌榜"),
    "vip-most-searched": (7785091694, "黑胶VIP爱搜榜"),
    "realtime-hot": (8246775932, "实时热度榜"),
    "lexia": (8661209031, "乐夏榜"),
    "car-tesla": (8703179781, "特斯拉车友爱听榜"),
    "car-li-auto": (8703052295, "理想车友爱听榜"),
    "car-byd": (8702582160, "比亚迪车友爱听榜"),
    "car-nio": (8703220480, "蔚来车友爱听榜"),
    "car-zeekr": (8702982391, "极氪车友爱听榜"),
    "eggy-party": (8532443277, "蛋仔派对听歌榜"),
    "ai": (9651277674, "AI歌曲榜"),
    "car-hyptec": (10131772880, "昊铂车友爱听榜"),
    "car-aion": (10162841534, "埃安车友爱听榜"),
    "western-rnb": (12225155968, "欧美R&B榜"),
    "vip-free": (12344472377, "黑胶VIP限免榜"),
    "car-geely": (12717025277, "吉利车友爱听榜"),
}

type_map: dict[str, str] = {key: label for key, (_, label) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "网易云音乐",
    "description": "网易云音乐官方榜单(飙升、新歌、原创、热歌及各曲风、语种、合作榜),输出榜单全量曲目",
    "link": "https://music.163.com/#/discover/toplist",
    "params": {"type": {"name": "榜单", "type": type_map}},
}

_PLAYLIST_API = "https://music.163.com/api/v6/playlist/detail"
_SONG_API_V3 = "https://music.163.com/api/v3/song/detail"  # 补详情首选
_SONG_API_LEGACY = "https://music.163.com/api/song/detail"  # v3 漏掉的歌用它兜底
_TRACKS_N = 1000  # v6 的 n 只影响 tracks 条数;trackIds 始终是全量(现有榜最多 200 首)
_SONG_CHUNK = 200  # song/detail 单次上限:v3 200 个全回、250 个也全回;旧接口 250 个只回 201 个
_HEADERS = {"Accept": "application/json, text/plain, */*"}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "soaring")
    if type_param not in _BOARDS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    board_id, label = _BOARDS[type_param]
    result = await _get_board(board_id, label, no_cache)
    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(result["data"]),
        fromCache=result["from_cache"],
        updateTime=result["update_time"],
        data=result["data"],
        message=result.get("message"),
    )


async def _get_board(board_id: int, label: str, no_cache: bool) -> dict:
    playlist_result = await _get_json(
        _PLAYLIST_API, {"id": str(board_id), "n": str(_TRACKS_N)}, label, no_cache=no_cache
    )
    playlist = playlist_result.data.get("playlist") or {}
    track_ids = [
        row["id"]
        for row in playlist.get("trackIds") or []
        if isinstance(row, dict) and row.get("id")
    ]
    if not track_ids:
        raise RuntimeError(f"Netease music {label} (id={board_id}) returned no playlist/trackIds")
    songs = {
        row["id"]: row
        for row in playlist.get("tracks") or []
        if isinstance(row, dict) and row.get("id")
    }
    await _backfill_details(label, no_cache, track_ids, songs)
    items = [_item(songs[track_id], position) for position, track_id in enumerate(track_ids, start=1) if track_id in songs]
    if not items:
        raise RuntimeError(f"Netease music {label} (id={board_id}) returned no resolvable songs")
    lost = len(track_ids) - len(items)
    message = (
        f"榜单 {len(track_ids)} 首里有 {lost} 首 song/detail 没有返回详情(下架或不存在),已跳过"
        if lost
        else None
    )
    # 响应级 fromCache/updateTime 取榜单主请求;补详情只是同一榜的关联请求
    return {
        "data": items,
        "message": message,
        "from_cache": playlist_result.from_cache,
        "update_time": playlist_result.update_time,
    }


async def _backfill_details(label: str, no_cache: bool, track_ids: list[int], songs: dict[int, dict]) -> None:
    """tracks 里没有的曲先用 v3 song/detail 补,v3 漏掉的再用旧 song/detail 补,结果写回 songs。"""
    for url, build_params in (
        (_SONG_API_V3, lambda chunk: {"c": json.dumps([{"id": i} for i in chunk])}),
        (_SONG_API_LEGACY, lambda chunk: {"ids": json.dumps(chunk)}),
    ):
        # v3 整批都查不到时会返回 code 404(不是错误),按空结果处理,交给旧接口兜底
        ok_codes: tuple[int, ...] = (200, 404) if url == _SONG_API_V3 else (200,)
        missing = [track_id for track_id in track_ids if track_id not in songs]
        for start in range(0, len(missing), _SONG_CHUNK):
            chunk = missing[start:start + _SONG_CHUNK]
            payload = await _get_json(url, build_params(chunk), label, no_cache=no_cache, ok_codes=ok_codes)
            songs.update({
                row["id"]: row
                for row in payload.data.get("songs") or []
                if isinstance(row, dict) and row.get("id")
            })


async def _get_json(
    url: str,
    params: dict[str, str],
    label: str,
    *,
    no_cache: bool,
    ok_codes: tuple[int, ...] = (200,),
) -> RequestResult:
    result = await get(url=url, params=params, headers=_HEADERS, no_cache=no_cache)
    payload = result.data if isinstance(result.data, dict) else {}
    code = payload.get("code")
    if code not in ok_codes:
        raise RuntimeError(f"Netease music {label}: {url} returned code={code}")
    result.data = payload
    return result


def _https(url: str | None) -> str | None:
    # v6 tracks 给 http://p1.music.126.net/...,song/detail 给 https://,同一图片 CDN,统一成 https
    return "https://" + url[len("http://"):] if url and url.startswith("http://") else url


def _text(value: object) -> str:
    # 连续空白(含全角空格、不换行空格)合成一个半角空格,显示效果与网页一致
    return " ".join(str(value or "").split())


def _item(song: dict, position: int) -> ListItem:
    """v6 tracks 与 v3 song/detail 用 ar/al,旧 song/detail 用 artists/album,两种都认。"""
    song_id = song["id"]
    album = song.get("al") or song.get("album") or {}
    artists = [
        _text(artist.get("name"))
        for artist in song.get("ar") or song.get("artists") or []
        if isinstance(artist, dict)
    ]
    # publishTime 是发行时间(毫秒);传秒让 models 校验器统一 ×1000——直接传毫秒会让
    # 2001-09 以前发行的歌(毫秒值 < 10^12)被当成秒再放大 1000 倍(board_api 推翻性验证 #12)
    publish_time = song.get("publishTime") or 0
    # dt 是时长(毫秒);pop 是站内热度 0-100
    duration = song.get("dt")
    pop = song.get("pop")
    return ListItem(
        id=song_id,
        title=_text(song.get("name")),
        url=f"https://music.163.com/song?id={song_id}",
        mobileUrl=f"https://y.music.163.com/m/song?id={song_id}",
        cover=_https(album.get("picUrl")),
        author="/".join(name for name in artists if name) or None,
        desc=_text(album.get("name")) or None,
        durationSeconds=duration // 1000 if isinstance(duration, int) and duration > 0 else None,
        metrics={"pop": pop} if isinstance(pop, int) and pop > 0 else None,
        sourceRank=position,  # trackIds 顺序即榜单名次
        timestamp=publish_time // 1000 if publish_time > 0 else None,
    )

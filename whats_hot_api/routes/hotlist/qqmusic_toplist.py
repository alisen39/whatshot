"""QQ 音乐巅峰榜(热歌榜、飙升榜、新歌榜、流行指数榜)。

数据源是公开 JSON 接口 ``u.y.qq.com/cgi-bin/musicu.fcg``,模块
``musicToplist.ToplistInfoServer``、方法 ``GetDetail``,不签名、不登录、不带 cookie
(board_api/qq_music 证据;网页在浏览器里把需要签名的请求改走 musics.fcg 并加 sign,
直接调 musicu.fcg 不校验签名)。

- ``num`` 必须带(不带返回 0 首),传 300 一次取全:热歌榜 300 首、其余 100 首,
  即接口 ``totalNum``;``period`` 传空串 = 最新一期,与网页
  ``y.qq.com/n/ryqq/toplist/<topId>`` 同一期。
- ``detail.data.data.song[]`` 是名次行,``detail.data.songInfoList[]`` 是按同一顺序的
  歌曲详情,两者按 ``song[i].songId == songInfoList[i].id`` 对齐;对不上的名次跳过并
  写入 message,不让整个榜报错。
- ``song[].cover`` 只有前 3 名有值,不能用;封面按网页脚本的取法从 ``songInfoList`` 拼。
- ``rankValue`` 是 "0" 或涨幅百分比,不是热度值,``hot`` 留空。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "qqmusic-toplist"

# 子榜 -> (topId, 中文名)。topId 取自 GetAll 目录"巅峰榜"组,与 tophub 节点域名前缀一致;声明序第一个是默认榜
_BOARDS: dict[str, tuple[int, str]] = {
    "hot": (26, "热歌榜"),
    "soaring": (62, "飙升榜"),
    "new": (27, "新歌榜"),
    "popular-index": (4, "流行指数榜"),
}

type_map: dict[str, str] = {key: label for key, (_, label) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "QQ音乐",
    "description": "QQ 音乐巅峰榜:热歌榜(300 首)、飙升榜、新歌榜、流行指数榜(各 100 首),最新一期全量",
    "link": "https://y.qq.com/n/ryqq/toplist/26",
    "params": {"type": {"name": "榜单", "type": type_map}},
}

_API = "https://u.y.qq.com/cgi-bin/musicu.fcg"
_NUM = 300  # 一次取多少首;大于 totalNum 时只回 totalNum 首(实测 num=500 仍是 300)
# 封面照网页脚本的取法(Page.chunk.js):歌曲单独封面 vs[1](T062)> 专辑封面 album.pmid(T002)
# > 只有一位歌手时的歌手照(T001)> 都没有时网页显示默认图(这里留空);mid 不足 14 位也用默认图
_PIC = "https://y.gtimg.cn/music/photo_new/{}R300x300M000{}.jpg"
_BEIJING = timezone(timedelta(hours=8))


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "hot")
    if type_param not in _BOARDS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    top_id, label = _BOARDS[type_param]
    result = await _get_board(top_id, label, no_cache)
    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(result["data"]),
        fromCache=result["from_cache"],
        updateTime=result["update_time"],
        data=result["data"],
        message=result.get("message"),
    )


async def _get_board(top_id: int, label: str, no_cache: bool) -> dict:
    data_param = json.dumps({
        "detail": {
            "module": "musicToplist.ToplistInfoServer",
            "method": "GetDetail",
            "param": {"topId": top_id, "offset": 0, "num": _NUM, "period": ""},
        }
    }, separators=(",", ":"))
    result = await get(url=_API, params={"format": "json", "data": data_param}, no_cache=no_cache)
    payload = result.data if isinstance(result.data, dict) else {}
    detail = payload.get("detail") or {}
    # 不存在的 topId 返回 detail.code=10000、0 首,按业务错误壳拒绝
    if payload.get("code") != 0 or detail.get("code") != 0:
        raise RuntimeError(
            f"QQ music {label} returned code={payload.get('code')} / detail.code={detail.get('code')}"
        )
    detail_data = detail.get("data") or {}
    board = detail_data.get("data") or {}
    ranks = board.get("song") or []
    infos = {
        info.get("id"): info
        for info in detail_data.get("songInfoList") or []
        if isinstance(info, dict) and info.get("id") is not None
    }
    items = [
        _item(infos[rank["songId"]])
        for rank in ranks
        if isinstance(rank, dict) and rank.get("songId") in infos and infos[rank["songId"]].get("mid")
    ]
    if not items:
        raise RuntimeError(f"QQ music {label} (topId={top_id}) returned no songs")
    notes = []
    if len(items) < len(ranks):
        notes.append(f"{len(ranks) - len(items)} 个名次在 songInfoList 里没有对应歌曲,已跳过")
    total = board.get("totalNum") or 0
    if len(ranks) < total:
        notes.append(f"接口只返回 {len(ranks)} 首,榜单共 {total} 首")
    return {
        "data": items,
        "message": "; ".join(notes) or None,
        "from_cache": result.from_cache,
        "update_time": result.update_time,
    }


def _pic(kind: str, mid: object) -> str | None:
    return _PIC.format(kind, mid) if isinstance(mid, str) and len(mid) >= 14 else None


def _cover(info: dict) -> str | None:
    vs = info.get("vs") or []
    if len(vs) > 1 and vs[1]:
        return _pic("T062", vs[1])
    pmid = (info.get("album") or {}).get("pmid")
    if pmid:
        return _pic("T002", pmid)
    singers = info.get("singer") or []
    if len(singers) == 1 and isinstance(singers[0], dict):
        return _pic("T001", singers[0].get("mid"))
    return None


def _timestamp(day: object) -> int | None:
    # time_public 是发行日期(YYYY-MM-DD),按北京时间 0 点;传秒让 models 校验器统一 ×1000
    # ——直接传毫秒会让 2001-09 以前发行的歌(毫秒值 < 10^12)被当成秒再放大 1000 倍
    # (board_api 推翻性验证 #9);1970 年以前(负值)留空
    if not isinstance(day, str):
        return None
    try:
        seconds = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=_BEIJING).timestamp())
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def _item(info: dict) -> ListItem:
    mid = info["mid"]
    album = info.get("album") or {}
    singers = [
        str(singer.get("title") or singer.get("name") or "").strip()
        for singer in info.get("singer") or []
        if isinstance(singer, dict)
    ]
    return ListItem(
        id=mid,
        # title 带版本后缀(如"出现又离开 (Live)"),与网页、tophub 一致;name 不带后缀,不用
        title=str(info.get("title") or info.get("name") or "").strip(),
        url=f"https://y.qq.com/n/ryqq/songDetail/{mid}",
        mobileUrl=f"https://i.y.qq.com/v8/playsong.html?songmid={mid}",
        cover=_cover(info),
        author="/".join(name for name in singers if name) or None,
        desc=str(album.get("title") or album.get("name") or "").strip() or None,
        timestamp=_timestamp(info.get("time_public")),
    )

from __future__ import annotations

import asyncio
import json

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import qqmusic_toplist
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/qqmusic-toplist",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _song_info(song_id: int, mid: str, title: str, singers: list[tuple[str, str, str]],
               album_title: str, album_pmid: str | None, vs: list[str],
               time_public: str) -> dict:
    return {
        "id": song_id,
        "mid": mid,
        "title": title,
        "subtitle": "",
        "singer": [
            {"mid": singer_mid, "name": plain, "title": display}
            for display, plain, singer_mid in singers
        ],
        "album": {"mid": "albumMid00001", "title": album_title, "pmid": album_pmid or ""},
        "vs": vs,
        "time_public": time_public,
    }


def _rank(song_id: int, title: str, singer_name: str, rank: int) -> dict:
    return {
        "rank": rank,
        "rankType": 3,
        "rankValue": "0",
        "songId": song_id,
        "title": title,
        "singerName": singer_name,
        "cover": "",
    }


# 依据 evidence/02_detail_26.response.body 净化内联(字段结构一致,截取 2 首)
def _detail_payload(ranks: list[dict], infos: list[dict], total_num: int) -> dict:
    return {
        "code": 0,
        "ts": 1790550000,
        "detail": {
            "code": 0,
            "data": {
                "data": {
                    "title": "热歌榜",
                    "period": "2026-09-27",
                    "updateTime": "2026-09-27",
                    "totalNum": total_num,
                    "song": ranks,
                },
                "songInfoList": infos,
                "extInfoList": [],
                "songTagInfoList": [],
                "indexInfoList": [],
            },
        },
    }


# 茶汤:album 封面(T002);第 2 首用歌曲单独封面(T062),双歌手
_INFOS = [
    _song_info(4936030, "0027rBks3lqPA3", "茶汤", [("郁可唯", "郁可唯", "000NUoMp2WAEpO")],
               "微加幸福-微笑幸福庆功版", "002iWKlh2DcjFL_2",
               ["061NBTxX1d8osm", "", ""], "2011-06-27"),
    _song_info(445406956, "003Haf8k2E6fYX", "出现又离开 (Live)",
               [("JOSHUA (조슈아)", "JOSHUA", "000JOSHUAmid001"), ("韦礼安", "韦礼安", "000WeiliAnmid2")],
               "TEAM SEVENTEEN", None,
               ["061vs0mid1234", "003SongSinglePic", ""], "1996-03-28"),
]
_RANKS = [
    _rank(4936030, "茶汤", "郁可唯", 1),
    _rank(445406956, "出现又离开 (Live)", "JOSHUA (조슈아)/韦礼安", 2),
]


def _install_get(monkeypatch, payload: dict) -> dict:
    captured = {}

    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "params": params, "headers": headers, "no_cache": no_cache})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", payload)

    monkeypatch.setattr(qqmusic_toplist, "get", fake_get)
    return captured


@pytest.mark.asyncio
async def test_request_payload_and_item_mapping(monkeypatch):
    captured = _install_get(monkeypatch, _detail_payload(_RANKS, _INFOS, total_num=2))
    result = await qqmusic_toplist.handle_route(_request("hot"), no_cache=True)

    assert captured["url"] == "https://u.y.qq.com/cgi-bin/musicu.fcg"
    assert captured["params"]["format"] == "json"
    data_param = json.loads(captured["params"]["data"])
    detail = data_param["detail"]
    assert detail["module"] == "musicToplist.ToplistInfoServer"
    assert detail["method"] == "GetDetail"
    assert detail["param"] == {"topId": 26, "offset": 0, "num": 300, "period": ""}
    assert captured["no_cache"] is True

    assert result.name == "qqmusic-toplist"
    assert result.type == "热歌榜"
    assert result.total == 2
    assert result.fromCache is False
    assert result.message is None

    first = result.data[0]
    assert first.id == "0027rBks3lqPA3"
    assert first.title == "茶汤"
    assert first.url == "https://y.qq.com/n/ryqq/songDetail/0027rBks3lqPA3"
    assert first.mobileUrl == "https://i.y.qq.com/v8/playsong.html?songmid=0027rBks3lqPA3"
    # vs[1] 为空,落到专辑封面 T002(pmid)
    assert first.cover == "https://y.gtimg.cn/music/photo_new/T002R300x300M000002iWKlh2DcjFL_2.jpg"
    assert first.author == "郁可唯"
    assert first.desc == "微加幸福-微笑幸福庆功版"
    assert first.hot is None  # rankValue 是 "0",不是热度值
    assert first.timestamp == 1309104000000  # 2011-06-27 北京时间 0 点

    second = result.data[1]
    # vs[1] 非空用歌曲单独封面 T062,优先于专辑封面
    assert second.cover == "https://y.gtimg.cn/music/photo_new/T062R300x300M000003SongSinglePic.jpg"
    # 歌手用 singer[].title(带别名括号),多个用 / 连接,与网页一致
    assert second.author == "JOSHUA (조슈아)/韦礼安"
    assert second.title == "出现又离开 (Live)"  # 带版本后缀,与网页、tophub 一致


@pytest.mark.asyncio
async def test_cover_fallback_chain(monkeypatch):
    infos = [
        # vs[1] 空、album 无 pmid、单歌手 -> 歌手照 T001
        _song_info(1, "a" * 14, "单歌手", [("歌手", "歌手", "b" * 14)], "专辑", None, ["x", "", ""], "2020-01-01"),
        # vs[1] 空、无 pmid、多歌手 -> 留空(网页显示默认图)
        _song_info(2, "c" * 14, "双歌手", [("A", "A", "d" * 14), ("B", "B", "e" * 14)], "专辑", None, [], "2020-01-01"),
        # pmid 不足 14 位 -> 留空
        _song_info(3, "f" * 14, "短pmid", [("歌手", "歌手", "g" * 14)], "专辑", "short", [], "2020-01-01"),
    ]
    ranks = [_rank(info["id"], info["title"], "x", i + 1) for i, info in enumerate(infos)]
    _install_get(monkeypatch, _detail_payload(ranks, infos, total_num=3))
    result = await qqmusic_toplist.handle_route(_request("hot"), no_cache=True)

    assert result.data[0].cover == "https://y.gtimg.cn/music/photo_new/T001R300x300M000" + "b" * 14 + ".jpg"
    assert result.data[1].cover is None
    assert result.data[2].cover is None


@pytest.mark.asyncio
async def test_pre2001_release_date_not_inflated(monkeypatch):
    # 推翻性验证 #9:1996-03-28(毫秒值 < 10^12)不得被当成秒再放大 1000 倍
    assert _INFOS[1]["time_public"] == "1996-03-28"
    ranks = [_RANKS[1]]
    _install_get(monkeypatch, _detail_payload(ranks, [_INFOS[1]], total_num=1))
    result = await qqmusic_toplist.handle_route(_request("hot"), no_cache=True)
    assert result.data[0].timestamp == 827942400000

    # 非法日期与 1970 年以前留空
    assert qqmusic_toplist._timestamp("0000-00-00") is None
    assert qqmusic_toplist._timestamp("1969-12-31") is None
    assert qqmusic_toplist._timestamp(None) is None


@pytest.mark.asyncio
async def test_rank_rows_without_song_info_are_skipped(monkeypatch):
    # 名次行与 songInfoList 按 songId == id 对齐,对不上的行跳过并写 message,顺序跟名次行
    infos = [_INFOS[1], _INFOS[0]]  # 故意乱序
    ranks = [_RANKS[0], _rank(999999, "不存在", "X", 2), _RANKS[1]]
    _install_get(monkeypatch, _detail_payload(ranks, infos, total_num=3))
    result = await qqmusic_toplist.handle_route(_request("hot"), no_cache=True)

    assert [item.id for item in result.data] == ["0027rBks3lqPA3", "003Haf8k2E6fYX"]
    assert result.total == 2
    assert result.message is not None
    assert "1 个名次在 songInfoList 里没有对应歌曲" in result.message


@pytest.mark.asyncio
async def test_short_return_reported_in_message(monkeypatch):
    # num=300 但榜单只回了一部分(totalNum 更大):不许静默截断
    _install_get(monkeypatch, _detail_payload(_RANKS, _INFOS, total_num=300))
    result = await qqmusic_toplist.handle_route(_request("hot"), no_cache=True)
    assert result.message is not None
    assert "接口只返回 2 首,榜单共 300 首" in result.message


@pytest.mark.asyncio
async def test_business_error_shell_is_rejected(monkeypatch):
    payload = _detail_payload(_RANKS, _INFOS, total_num=300)
    payload["detail"]["code"] = 10000  # 不存在的 topId 的表现
    _install_get(monkeypatch, payload)
    with pytest.raises(RuntimeError, match="detail.code=10000"):
        await qqmusic_toplist.handle_route(_request("soaring"), no_cache=True)

    outer_error = _detail_payload(_RANKS, _INFOS, total_num=300)
    outer_error["code"] = 2001
    _install_get(monkeypatch, outer_error)
    with pytest.raises(RuntimeError, match="code=2001"):
        await qqmusic_toplist.handle_route(_request("soaring"), no_cache=True)


@pytest.mark.asyncio
async def test_empty_song_list_is_rejected(monkeypatch):
    _install_get(monkeypatch, _detail_payload([], [], total_num=300))
    with pytest.raises(RuntimeError, match="no songs"):
        await qqmusic_toplist.handle_route(_request("hot"), no_cache=True)


def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        asyncio.run(qqmusic_toplist.handle_route(_request("not-exist"), no_cache=True))

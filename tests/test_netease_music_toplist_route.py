from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import netease_music_toplist
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/netease-music-toplist",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _song(song_id: int, name: str, artists: list[str], album: str,
          pic: str, publish_time: int) -> dict:
    return {
        "id": song_id,
        "name": name,
        "ar": [{"id": i, "name": artist} for i, artist in enumerate(artists, 1)],
        "al": {"name": album, "picUrl": pic},
        "publishTime": publish_time,
    }


# 依据 evidence/02_v6_detail_3778678.response.body 净化内联(字段结构一致,截取 2 首)
def _playlist_payload(track_ids: list[int], tracks: list[dict]) -> dict:
    return {
        "code": 200,
        "relatedVideos": [],
        "urls": [],
        "privileges": [],
        "playlist": {
            "id": 19723756,
            "name": "飙升榜",
            "updateTime": 1790538000000,
            "trackCount": len(track_ids),
            "trackIds": [{"id": i, "v": 12, "at": 1790538000000} for i in track_ids],
            "tracks": tracks,
        },
    }


def _install_get(monkeypatch, handler) -> list[dict]:
    calls = []

    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        calls.append({"url": url, "params": params, "headers": headers, "no_cache": no_cache})
        payload = handler(url, params)
        return RequestResult(False, "2026-10-01T00:00:00+00:00", payload)

    monkeypatch.setattr(netease_music_toplist, "get", fake_get)
    return calls


@pytest.mark.asyncio
async def test_v6_request_and_item_mapping(monkeypatch):
    tracks = [
        _song(1973665667, "海屿你", ["马也_Crabbit", "h3R3"], "海屿你",
              "http://p2.music.126.net/RfguLkQJ8aMVkiIaxdy70Q==/109951170483263672.jpg", 1660924800000),
        _song(307594, "泪海", ["许茹芸"], "泪海",
              "https://p1.music.126.net/abc/1.jpg", 827942400000),
    ]
    calls = _install_get(
        monkeypatch,
        lambda url, params: _playlist_payload([1973665667, 307594], tracks),
    )
    result = await netease_music_toplist.handle_route(_request("soaring"), no_cache=True)

    # 只发 v6 playlist/detail 一个请求;tracks 齐全时不补 song/detail
    assert [call["url"] for call in calls] == ["https://music.163.com/api/v6/playlist/detail"]
    assert calls[0]["params"] == {"id": "19723756", "n": "1000"}
    assert calls[0]["no_cache"] is True

    assert result.name == "netease-music-toplist"
    assert result.type == "飙升榜"
    assert result.total == 2
    assert result.fromCache is False
    assert result.updateTime == "2026-10-01T00:00:00+00:00"
    assert result.message is None

    first = result.data[0]
    assert first.id == "1973665667"
    assert first.title == "海屿你"
    assert first.url == "https://music.163.com/song?id=1973665667"
    assert first.mobileUrl == "https://y.music.163.com/m/song?id=1973665667"
    # v6 给 http:// 封面,统一成 https://(同一图片 CDN)
    assert first.cover == "https://p2.music.126.net/RfguLkQJ8aMVkiIaxdy70Q==/109951170483263672.jpg"
    assert first.author == "马也_Crabbit/h3R3"
    assert first.desc == "海屿你"
    assert first.hot is None  # 接口不给热度值
    assert first.timestamp == 1660924800000
    # 输出顺序跟 trackIds(原站名次)一致
    assert result.data[1].id == "307594"


@pytest.mark.asyncio
async def test_title_whitespace_normalized_and_pre2001_timestamp_kept(monkeypatch):
    # 推翻性验证 #12/#16:全角空格、不换行空格合成一个半角空格;2001-09 以前的发行时间
    # (毫秒值 < 10^12)不得被当成秒再放大 1000 倍(泪海 publishTime=827942400000)
    tracks = [
        _song(307594, "泪海", ["许茹芸"], "泪海", "https://p1.music.126.net/a/1.jpg", 827942400000),
        _song(1, " 海上　花 ", ["X"], "专辑", "https://p1.music.126.net/a/2.jpg", 0),
    ]
    _install_get(monkeypatch, lambda url, params: _playlist_payload([307594, 1], tracks))
    result = await netease_music_toplist.handle_route(_request("soaring"), no_cache=True)

    assert result.data[0].timestamp == 827942400000
    assert result.data[1].title == "海上 花"
    assert result.data[1].timestamp is None  # publishTime 为 0 留空


@pytest.mark.asyncio
async def test_tracks_shortfall_backfills_via_v3(monkeypatch):
    tracks = [
        _song(1973665667, "海屿你", ["马也_Crabbit", "h3R3"], "海屿你",
              "https://p2.music.126.net/x/1.jpg", 1660924800000),
    ]
    missing_song = _song(307594, "泪海", ["许茹芸"], "泪海", "https://p1.music.126.net/a/1.jpg", 827942400000)

    def handler(url, params):
        if url == netease_music_toplist._PLAYLIST_API:
            return _playlist_payload([1973665667, 307594], tracks)
        assert url == "https://music.163.com/api/v3/song/detail"
        assert json.loads(params["c"]) == [{"id": 307594}]
        return {"code": 200, "songs": [missing_song]}

    _install_get(monkeypatch, handler)
    result = await netease_music_toplist.handle_route(_request("soaring"), no_cache=True)

    assert result.total == 2
    assert result.message is None
    assert result.data[1].id == "307594"


@pytest.mark.asyncio
async def test_v3_miss_falls_back_to_legacy_api(monkeypatch):
    # v3 整批查不到时可能返回 code 404(或 code 200、songs 空),都按空结果交给旧接口兜底
    legacy_songs = [
        _song(1973665667, "海屿你", ["马也_Crabbit", "h3R3"], "海屿你", "https://p2.music.126.net/x/1.jpg", 1660924800000),
        _song(307594, "泪海", ["许茹芸"], "泪海", "https://p1.music.126.net/a/1.jpg", 827942400000),
    ]
    legacy_calls = []

    def handler(url, params):
        if url == netease_music_toplist._PLAYLIST_API:
            return _playlist_payload([1973665667, 307594], [])
        if url == netease_music_toplist._SONG_API_V3:
            return {"code": 404}
        legacy_calls.append(json.loads(params["ids"]))
        assert url == netease_music_toplist._SONG_API_LEGACY
        return {"code": 200, "songs": legacy_songs}

    _install_get(monkeypatch, handler)
    result = await netease_music_toplist.handle_route(_request("soaring"), no_cache=True)

    assert legacy_calls == [[1973665667, 307594]]
    assert result.total == 2
    assert result.message is None


@pytest.mark.asyncio
async def test_song_detail_requests_are_chunked(monkeypatch):
    monkeypatch.setattr(netease_music_toplist, "_SONG_CHUNK", 2)
    ids = [1, 2, 3]

    def handler(url, params):
        if url == netease_music_toplist._PLAYLIST_API:
            return _playlist_payload(ids, [])
        assert url == netease_music_toplist._SONG_API_V3
        chunk = [entry["id"] for entry in json.loads(params["c"])]
        return {"code": 200, "songs": [
            _song(i, f"歌{i}", ["A"], "专辑", f"https://p1.music.126.net/a/{i}.jpg", 1660924800000)
            for i in chunk
        ]}

    calls = _install_get(monkeypatch, handler)
    result = await netease_music_toplist.handle_route(_request("soaring"), no_cache=True)

    v3_chunks = [json.loads(call["params"]["c"]) for call in calls if call["url"] == netease_music_toplist._SONG_API_V3]
    assert v3_chunks == [[{"id": 1}, {"id": 2}], [{"id": 3}]]
    assert result.total == 3


@pytest.mark.asyncio
async def test_playlist_error_code_is_rejected(monkeypatch):
    _install_get(monkeypatch, lambda url, params: {"code": 404, "message": "不存在"})
    with pytest.raises(RuntimeError, match="code=404"):
        await netease_music_toplist.handle_route(_request("soaring"), no_cache=True)


@pytest.mark.asyncio
async def test_empty_track_ids_is_rejected(monkeypatch):
    _install_get(monkeypatch, lambda url, params: _playlist_payload([], []))
    with pytest.raises(RuntimeError, match="no playlist/trackIds"):
        await netease_music_toplist.handle_route(_request("soaring"), no_cache=True)

    # playlist 对象缺失(如 {"code":200} 空壳)同样拒绝
    _install_get(monkeypatch, lambda url, params: {"code": 200})
    with pytest.raises(RuntimeError, match="no playlist/trackIds"):
        await netease_music_toplist.handle_route(_request("soaring"), no_cache=True)


@pytest.mark.asyncio
async def test_all_details_missing_is_rejected(monkeypatch):
    # v6 tracks 空、v3 与旧接口都没返回详情:不能静默降级为空榜
    def handler(url, params):
        if url == netease_music_toplist._PLAYLIST_API:
            return _playlist_payload([1973665667], [])
        return {"code": 200, "songs": []}

    _install_get(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="no resolvable songs"):
        await netease_music_toplist.handle_route(_request("soaring"), no_cache=True)


def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        import asyncio

        asyncio.run(netease_music_toplist.handle_route(_request("not-exist"), no_cache=True))

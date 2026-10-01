from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import ximalaya_album
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/ximalaya-album",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


# 依据 evidence/01_album_track_newest.response.body 净化内联(截取前 2 条)
def _xueqiu_payload() -> dict:
    return {
        "ret": 0,
        "msg": "0",
        "data": {
            "list": [
                {
                    "trackId": 1016862626,
                    "title": "3358.为什么业绩大增而股价下跌？再论估值的本质逻辑",
                    "albumId": 299146,
                    "coverLarge": "http://imagev2.xmcdn.com/group81/M0B/73/B0/cover640.png!op_type=3&columns=640&rows=640",
                    "coverMiddle": "http://imagev2.xmcdn.com/group81/M0B/73/B0/cover180.png",
                    "playtimes": 4538,
                    "createdAt": 1790481420000,
                    "nickname": "雪球",
                    "intro": "欢迎收听雪球出品的财经有深度。",
                },
                {
                    "trackId": 1016859572,
                    "title": "3357.从切片到生命：论投资的动态本质",
                    "albumId": 299146,
                    "coverLarge": None,
                    "coverMiddle": "http://imagev2.xmcdn.com/group81/M0B/73/B0/cover180.png",
                    "playtimes": 12622,
                    "createdAt": 1790394360000,
                    "nickname": "雪球",
                    "intro": "   ",
                },
            ],
        },
    }


@pytest.mark.asyncio
async def test_xueqiu_request_params_and_item_mapping(monkeypatch):
    captured = {}

    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "params": params, "no_cache": no_cache})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _xueqiu_payload())

    monkeypatch.setattr(ximalaya_album, "get", fake_get)
    result = await ximalaya_album.handle_route(_request("xueqiu"), no_cache=True)

    assert captured["url"] == "https://mobile.ximalaya.com/mobile/v1/album/track"
    # 专辑 299146;isAsc=true 显式声明最新在前(false 会从 2017 年第 24 期开始)
    assert captured["params"] == {
        "albumId": "299146",
        "pageId": 1,
        "pageSize": 20,
        "isAsc": "true",
    }
    assert captured["no_cache"] is True

    assert result.name == "ximalaya-album"
    assert result.type == "雪球·财经有深度"
    assert result.total == 2
    # link 指向专辑页(board_api 的 meta 覆盖行为)
    assert result.link == "https://www.ximalaya.com/album/299146"
    item = result.data[0]
    assert item.id == "1016862626"
    assert item.title.startswith("3358.")
    assert item.url == "https://www.ximalaya.com/sound/1016862626"
    assert item.mobileUrl == "https://m.ximalaya.com/sound/1016862626"
    assert item.hot == 4538
    assert item.author == "雪球"
    # createdAt 已是毫秒;http 封面升级 https
    assert item.timestamp == 1790481420000
    assert item.cover == (
        "https://imagev2.xmcdn.com/group81/M0B/73/B0/cover640.png!op_type=3&columns=640&rows=640"
    )
    assert item.desc == "欢迎收听雪球出品的财经有深度。"


@pytest.mark.asyncio
async def test_cover_falls_back_to_middle_and_blank_intro_is_none(monkeypatch):
    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", _xueqiu_payload())

    monkeypatch.setattr(ximalaya_album, "get", fake_get)
    result = await ximalaya_album.handle_route(_request("xueqiu"), no_cache=True)
    second = result.data[1]
    assert second.timestamp == 1790394360000
    assert second.cover == "https://imagev2.xmcdn.com/group81/M0B/73/B0/cover180.png"
    assert second.desc is None  # 空白 intro 归一化为 None


@pytest.mark.asyncio
async def test_nonzero_ret_shell_is_rejected(monkeypatch):
    # 该接口成功是 ret=0;网页 getTracksList 的 407"webtk缺失"就是错误壳
    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"ret": 407, "msg": "webtk缺失"})

    monkeypatch.setattr(ximalaya_album, "get", fake_get)
    with pytest.raises(RuntimeError, match="ret=407"):
        await ximalaya_album.handle_route(_request("xueqiu"), no_cache=True)


@pytest.mark.asyncio
async def test_empty_track_list_is_rejected(monkeypatch):
    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"ret": 0, "data": {"list": []}})

    monkeypatch.setattr(ximalaya_album, "get", fake_get)
    with pytest.raises(RuntimeError, match="no tracks"):
        await ximalaya_album.handle_route(_request("xueqiu"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await ximalaya_album.handle_route(_request("not-exist"), no_cache=True)


def test_route_meta_declares_xueqiu_as_first_type():
    # 注册表按 params.type.type 的第一个键取 defaultType,必须是 xueqiu
    types = list(ximalaya_album.ROUTE_META["params"]["type"]["type"])
    assert types[0] == "xueqiu"
    assert ximalaya_album.ROUTE_NAME == "ximalaya-album"

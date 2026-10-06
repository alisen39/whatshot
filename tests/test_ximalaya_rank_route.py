from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import ximalaya_rank
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/ximalaya-rank",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


# 依据 evidence/03_v2_element_free_toutiao.response.body 净化内联(截取前 2 条)
def _toutiao_payload(cluster_id: int = 66) -> dict:
    return {
        "ret": 200,
        "data": {
            "typeId": 4,
            "clusterId": cluster_id,
            "rankList": [{
                "count": 50,
                "ids": [30140766, 12580785, 99999999],
                "title": "50个通晓天下事的资讯电台",
                "rankId": 67,
                "albums": [
                    {
                        "id": 30140766,
                        "albumTitle": "辽沈先声",
                        "albumUrl": "/album/30140766",
                        "cover": "group72/M08/1C/E4/wKgO0F4TGCaSaeIdAAFLb4P_X-4063.jpg",
                        "playCount": 682474656,
                        "description": "新鲜 | 热门 | 有料热点资讯实时发布",
                        "anchorName": "辽沈晚报",
                        "lastUptrackAtStr": "2021-03",
                    },
                    {
                        "id": 12580785,
                        "albumTitle": "今日封面",
                        "albumUrl": "/album/12580785",
                        "cover": "//imagev2.xmcdn.com/storages/66c2-audiofreehighqps/05/26/GMCoOR4IBEVZAAKazwILlsq2.jpeg",
                        "playCount": 932651981,
                        "description": "",
                        "anchorName": "封面新闻",
                    },
                ],
            }],
        },
    }


@pytest.mark.asyncio
async def test_toutiao_board_request_and_item_mapping(monkeypatch):
    captured = {}

    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "params": params, "headers": headers, "no_cache": no_cache})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _toutiao_payload())

    monkeypatch.setattr(ximalaya_rank, "get", fake_get)
    result = await ximalaya_rank.handle_route(_request("free-toutiao"), no_cache=True)

    assert captured["url"] == "https://www.ximalaya.com/revision/rank/v2/element/code"
    # 有分类的榜用拼音代码;无分类的"热门/总榜/新品"用分类 ID 字符串
    assert captured["params"] == {"typeCode": "free", "clusterCode": "toutiao"}
    assert captured["no_cache"] is True
    # UA 含 "python" 时接口返回 200 空响应,必须显式带浏览器 UA
    assert "python" not in captured["headers"]["User-Agent"].lower()
    assert captured["headers"]["Referer"] == "https://www.ximalaya.com/top/"

    assert result.name == "ximalaya-rank"
    assert result.type == "头条免费榜"
    assert result.total == 2
    assert result.fromCache is False
    item = result.data[0]
    assert item.id == "30140766"
    assert item.title == "辽沈先声"
    assert item.url == "https://www.ximalaya.com/album/30140766"
    assert item.mobileUrl == "https://m.ximalaya.com/album/30140766"
    assert item.hot == 682474656
    assert item.author == "辽沈晚报"
    assert item.desc == "新鲜 | 热门 | 有料热点资讯实时发布"
    # 接口没有发布时间,lastUptrackAtStr 是模糊文字,timestamp 留空
    assert item.timestamp is None


@pytest.mark.asyncio
async def test_default_board_and_cover_variants(monkeypatch):
    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        assert params == {"typeCode": "free", "clusterCode": "65"}
        return RequestResult(False, "t", _toutiao_payload(cluster_id=65))

    monkeypatch.setattr(ximalaya_rank, "get", fake_get)
    result = await ximalaya_rank.handle_route(_request("free-hot"), no_cache=False)
    assert result.type == "热门免费榜"
    # 相对路径补 imagev2 前缀,// 开头补 https:
    assert result.data[0].cover == (
        "https://imagev2.xmcdn.com/group72/M08/1C/E4/wKgO0F4TGCaSaeIdAAFLb4P_X-4063.jpg"
    )
    assert result.data[1].cover == (
        "https://imagev2.xmcdn.com/storages/66c2-audiofreehighqps/05/26/GMCoOR4IBEVZAAKazwILlsq2.jpeg"
    )


@pytest.mark.asyncio
async def test_dropped_ids_reported_in_message(monkeypatch):
    # 证据:free-toutiao 名次名单 50 个、albums 49 条(1 个已删除),差额写进 message
    payload = _toutiao_payload()
    payload["data"]["rankList"][0]["ids"] = list(range(30000001, 30000004))

    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", payload)

    monkeypatch.setattr(ximalaya_rank, "get", fake_get)
    result = await ximalaya_rank.handle_route(_request("free-toutiao"), no_cache=True)
    assert result.total == 2
    assert result.message is not None
    assert "名次名单 3 个" in result.message
    assert "1 个接口不给详情" in result.message


@pytest.mark.asyncio
async def test_matching_id_count_has_no_message(monkeypatch):
    payload = _toutiao_payload()
    payload["data"]["rankList"][0]["ids"] = [30140766, 12580785]

    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", payload)

    monkeypatch.setattr(ximalaya_rank, "get", fake_get)
    result = await ximalaya_rank.handle_route(_request("free-toutiao"), no_cache=True)
    assert result.message is None


@pytest.mark.asyncio
async def test_error_ret_shell_is_rejected(monkeypatch):
    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"ret": 403, "msg": "forbidden"})

    monkeypatch.setattr(ximalaya_rank, "get", fake_get)
    with pytest.raises(RuntimeError, match="ret=403"):
        await ximalaya_rank.handle_route(_request("free-toutiao"), no_cache=True)


@pytest.mark.asyncio
async def test_cluster_silent_fallback_is_rejected(monkeypatch):
    # clusterCode 写错/分类改名时服务端静默退回"热门"(clusterId=65),必须报错而不是输出错榜
    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", _toutiao_payload(cluster_id=65))

    monkeypatch.setattr(ximalaya_rank, "get", fake_get)
    with pytest.raises(RuntimeError, match="clusterId=65"):
        await ximalaya_rank.handle_route(_request("free-toutiao"), no_cache=True)


@pytest.mark.asyncio
async def test_empty_albums_is_rejected(monkeypatch):
    payload = _toutiao_payload()
    payload["data"]["rankList"][0]["albums"] = []

    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", payload)

    monkeypatch.setattr(ximalaya_rank, "get", fake_get)
    with pytest.raises(RuntimeError, match="no items"):
        await ximalaya_rank.handle_route(_request("free-toutiao"), no_cache=True)


def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        import asyncio

        asyncio.run(ximalaya_rank.handle_route(_request("not-exist"), no_cache=True))

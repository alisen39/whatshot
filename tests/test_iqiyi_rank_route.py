from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import iqiyi_rank
from whats_hot_api.utils.http_client import RequestResult

# fixtures 按证据 captured_data(02_api_all_hot.response.body 等)净化构造,只保留结构与字段
_CONTENT = {
    "title": "示例剧名",
    "img": "https://pic9.iqiyipic.com/image/20260920/28/fb/a_100801025_m_601_m10.jpg",
    "desc": "示例简介",
    "tags": "电视剧 / 2026 / 复仇 古装 / 甲 乙",
    "mainIndex": "7138",
    "indexType": "1",
    "pageUrl": "http://www.iqiyi.com/v_290syr52zds.html",
    "aid": "8582873758311901",
    "id": "8582873758311901",
    "tvid": "8249172768970700",
    "promptDesc": "双强联手 入局复仇",
}

_PAYLOAD_HOT = {
    "code": "0",
    "data": {"items": [{"subCardTitle": "按实时热度排行最近更新09-28 02:26", "name": "榜单名称",
                        "contents": [dict(_CONTENT), {"title": "示例片名二", "mainIndex": "7163",
                                                       "indexType": "5", "id": "8582873758311902",
                                                       "pageUrl": "//www.iqiyi.com/v_abc.html"}]}]},
}

_PAYLOAD_SCORE = {
    "code": "0",
    "data": {"items": [{"subCardTitle": "按推荐分排行", "name": "榜单名称",
                        "contents": [{"title": "高分片", "mainIndex": "9.7", "indexType": "3",
                                      "id": "9000000000000001", "pageUrl": "http://www.iqiyi.com/v_score.html"}]}]},
}

_PAYLOAD_EXPECT = {
    "code": "0",
    "data": {"items": [{"subCardTitle": "按预约人数排行", "name": "榜单名称",
                        "contents": [{"title": "未上线新片", "mainIndex": "12000", "indexType": "8",
                                      "id": "9100000000000001", "pageUrl": ""}]}]},
}


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": f"/iqiyi-rank/{board_type}",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _ok(payload, from_cache: bool = False, update_time: str = "2026-10-01T00:00:00+00:00"):
    return RequestResult(from_cache, update_time, payload)


def _capture_get(monkeypatch, payloads: list):
    captured: dict = {}
    calls = {"n": 0}

    async def fake_get(url, headers=None, params=None, no_cache=None, cache_key=None, **kwargs):
        captured.update({"url": url, "headers": headers, "params": params, "cache_key": cache_key})
        calls["n"] += 1
        return _ok(payloads[min(calls["n"], len(payloads)) - 1])

    monkeypatch.setattr(iqiyi_rank, "get", fake_get)
    return captured, calls


def _patch_sleep(monkeypatch) -> list[float]:
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(iqiyi_rank, "_sleep", fake_sleep)
    return waits


@pytest.mark.asyncio
async def test_hot_board_url_params_region_ip_and_mapping(monkeypatch):
    captured, _calls = _capture_get(monkeypatch, [_PAYLOAD_HOT])
    _patch_sleep(monkeypatch)
    result = await iqiyi_rank.handle_route(_request("tv-hot"), no_cache=True)

    assert captured["url"] == "https://mesh.if.iqiyi.com/portal/pcw/rankList/comSecRankList"
    # 地区口径:固定传大陆 REGION_IP,不依赖本机出口
    assert captured["params"]["ip"] == iqiyi_rank.REGION_IP == "202.106.0.20"
    assert captured["params"]["category_id"] == "2"  # 电视剧 cid=2
    assert captured["params"]["channelId"] == "2"
    assert captured["params"]["page_st"] == "0"  # 热播榜 id=0
    assert captured["params"]["tag"] == "0"
    assert captured["params"]["pg_num"] == "1"
    assert captured["cache_key"] == "iqiyi-rank:tv-hot"

    assert result.type == "电视剧 · 热播榜"
    first = result.data[0]
    assert first.id == "8582873758311901"
    assert first.title == "示例剧名"
    assert first.hot == 7138  # indexType=1 实时热度输出 mainIndex
    assert first.url == "https://www.iqiyi.com/v_290syr52zds.html"  # http 升 https
    assert first.mobileUrl == first.url
    assert first.cover == "https://pic9.iqiyipic.com/image/20260920/28/fb/a_100801025_m_601_m10.jpg"
    assert first.desc == "示例简介"
    assert first.author is None  # 主演只在 tags 字符串里,各频道格式不同,不拆
    assert first.timestamp is None  # 作品条目无发布时间
    second = result.data[1]
    assert second.url == "https://www.iqiyi.com/v_abc.html"  # // 前缀补 https
    assert second.hot == 7163  # indexType=5 最高热度也是热度


@pytest.mark.asyncio
async def test_default_board_is_all_hot_and_channel_params(monkeypatch):
    captured, _calls = _capture_get(monkeypatch, [_PAYLOAD_HOT])
    _patch_sleep(monkeypatch)
    request = Request({
        "type": "http", "method": "GET", "path": "/iqiyi-rank",
        "query_string": b"", "headers": [],
    })
    result = await iqiyi_rank.handle_route(request, no_cache=True)

    # 声明序第一个是默认榜:all-hot;总榜 cid=-1 但 channelId 传 0(照页面脚本)
    assert iqiyi_rank.DEFAULT_TYPE == "all-hot"
    assert next(iter(iqiyi_rank.BOARD_TYPES)) == "all-hot"
    assert captured["params"]["category_id"] == "-1"
    assert captured["params"]["channelId"] == "0"
    assert captured["params"]["page_st"] == "0"
    assert result.type == "总榜 · 热播榜"


@pytest.mark.asyncio
async def test_tag_board_page_st_uses_navigation_id(monkeypatch):
    captured, _calls = _capture_get(monkeypatch, [_PAYLOAD_HOT])
    _patch_sleep(monkeypatch)
    result = await iqiyi_rank.handle_route(_request("tv-police"), no_cache=True)

    # 标签榜 id 取自页面导航:警匪榜 7245663290192433,category_id 与 channelId 同值
    assert captured["params"]["category_id"] == "2"
    assert captured["params"]["channelId"] == "2"
    assert captured["params"]["page_st"] == "7245663290192433"
    assert captured["params"]["tag"] == "7245663290192433"
    assert result.type == "电视剧 · 警匪榜"


@pytest.mark.asyncio
async def test_score_board_hot_empty_for_recommend_score(monkeypatch):
    _capture_get(monkeypatch, [_PAYLOAD_SCORE])
    _patch_sleep(monkeypatch)
    result = await iqiyi_rank.handle_route(_request("movie-score"), no_cache=True)

    # indexType=3 是推荐分(9.7 这类),不是热度,hot 留空
    assert result.data[0].hot is None
    assert result.data[0].title == "高分片"


@pytest.mark.asyncio
async def test_expect_board_item_without_page_url_falls_back_to_board_page(monkeypatch):
    _capture_get(monkeypatch, [_PAYLOAD_EXPECT])
    _patch_sleep(monkeypatch)
    result = await iqiyi_rank.handle_route(_request("all-expect"), no_cache=True)

    # 期待榜未上线的片子没有 pageUrl,页面上是空 href(指回榜单页),这里同样指回榜单页
    assert result.data[0].hot is None  # indexType=8 预约人数不是热度
    assert result.data[0].url == "https://www.iqiyi.com/ranks1/-1/-8"


@pytest.mark.asyncio
async def test_transient_error_code_retries_then_succeeds(monkeypatch):
    # 偶发 code=-1 "error":隔 2 秒重试,第 2 次成功
    _captured, calls = _capture_get(monkeypatch, [{"code": "-1", "msg": "error"}, _PAYLOAD_HOT])
    waits = _patch_sleep(monkeypatch)
    result = await iqiyi_rank.handle_route(_request("all-hot"), no_cache=True)

    assert calls["n"] == 2
    assert waits == [2.0]
    assert result.total == 2


@pytest.mark.asyncio
async def test_persistent_error_shell_raises_after_retries(monkeypatch):
    # 错误壳重试到底仍失败:明确报错,不静默降级为空榜
    _capture_get(monkeypatch, [{"code": "-1", "msg": "error"}])
    _patch_sleep(monkeypatch)
    with pytest.raises(RuntimeError, match="code=-1"):
        await iqiyi_rank.handle_route(_request("all-hot"), no_cache=True)


@pytest.mark.asyncio
async def test_empty_contents_shell_raises(monkeypatch):
    # code=0 但 contents 为空也是错误壳
    _capture_get(monkeypatch, [{"code": "0", "data": {"items": []}}])
    _patch_sleep(monkeypatch)
    with pytest.raises(RuntimeError, match="returned no list"):
        await iqiyi_rank.handle_route(_request("all-hot"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_type_rejected(monkeypatch):
    _capture_get(monkeypatch, [_PAYLOAD_HOT])
    with pytest.raises(ValueError, match="Unknown board"):
        await iqiyi_rank.handle_route(_request("no-such-board"), no_cache=True)


def test_route_declares_all_57_boards():
    # 57 个子榜全部声明,声明序第一个是默认榜;id 不用名次
    assert len(iqiyi_rank.BOARD_TYPES) == 57
    assert iqiyi_rank.ROUTE_META["params"]["type"]["type"] == iqiyi_rank.BOARD_TYPES
    assert iqiyi_rank.DEFAULT_TYPE == "all-hot"
    assert "all-hot" in iqiyi_rank.BOARD_TYPES and "knowledge-rise" in iqiyi_rank.BOARD_TYPES

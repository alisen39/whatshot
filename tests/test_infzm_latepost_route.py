from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import infzm_latepost
from whats_hot_api.utils.http_client import RequestResult

_BEIJING = timezone(timedelta(hours=8))
_UPDATE_TIME = "2026-09-30T15:00:00+00:00"


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/infzm-latepost",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _ms(beijing_naive: str) -> int:
    moment = datetime.strptime(beijing_naive, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_BEIJING)
    return int(moment.timestamp() * 1000)


# ---------------------------------------------------------------- 南方周末


@pytest.mark.asyncio
async def test_infzm_contents_board_maps_fields(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "params": params, "headers": headers, "no_cache": no_cache})
        return RequestResult(False, _UPDATE_TIME, {
            "code": 200,
            "data": {
                "current_term": {"id": 998, "title": "推荐", "type": "module"},
                "contents": [
                    {
                        "id": 331624,
                        "subject": "李梅：现实版“忆秦娥”",
                        "author": "\u200b南方人物周刊记者 梁辰 ",  # 原站作者偶有零宽空格开头
                        "publish_time": "2026-09-27 23:00:00",
                        "introtext": "“秦腔不能总让老年人抹泪”",
                        "covers": [{"file_path": "http://images.infzm.com/cms/medias/image/26/09/24/a.jpg"}],
                    },
                    {"id": 331111, "short_subject": "只有 short_subject 的稿件", "publish_time": "", "list_desc": "列表摘要"},
                ],
            },
        })

    monkeypatch.setattr(infzm_latepost, "get", fake_get)
    result = await infzm_latepost.handle_route(_request("infzm-recommend"), no_cache=True)

    assert captured["url"] == "https://www.infzm.com/contents"
    assert captured["params"] == {"term_id": "998", "page": "1", "format": "json"}  # 今日推荐 = 998(PC 首页"推荐"区块)
    assert captured["no_cache"] is True
    assert result.type == "南方周末 · 今日推荐"
    assert result.message == "推荐（term_id=998）"
    first = result.data[0]
    assert first.id == "331624"
    assert first.title == "李梅：现实版“忆秦娥”"
    assert first.url == first.mobileUrl == "https://www.infzm.com/contents/331624"  # 不带 source 统计参数
    assert first.author == "南方人物周刊记者 梁辰"
    assert first.cover == "http://images.infzm.com/cms/medias/image/26/09/24/a.jpg"
    assert first.timestamp == _ms("2026-09-27 23:00:00")  # 毫秒
    second = result.data[1]
    assert second.title == "只有 short_subject 的稿件"
    assert second.desc == "列表摘要"  # introtext 缺失时退 list_desc
    assert second.timestamp is None


@pytest.mark.asyncio
async def test_infzm_hot_board_uses_hot_contents_endpoint(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(url, params=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return RequestResult(False, _UPDATE_TIME, {
            "code": 200,
            "data": {"hot_contents": [{"id": 331695, "subject": "逝者丨刘欢", "publish_time": "2026-09-26 13:42:44"}]},
        })

    monkeypatch.setattr(infzm_latepost, "get", fake_get)
    result = await infzm_latepost.handle_route(_request("infzm-hot"), no_cache=True)

    assert captured["url"] == "https://www.infzm.com/hot_contents"
    assert captured["params"] == {"format": "json"}
    assert result.message == "热门文章"
    assert result.data[0].id == "331695"
    assert result.data[0].timestamp == _ms("2026-09-26 13:42:44")


@pytest.mark.asyncio
async def test_infzm_error_shell_and_empty_parse_raise(monkeypatch):
    async def fake_get(url, params=None, **kwargs):
        if params.get("term_id") == "2":
            return RequestResult(False, _UPDATE_TIME, {"code": 401, "data": None, "msg": "unauthorized"})
        if params.get("term_id") == "3":
            return RequestResult(False, _UPDATE_TIME, {"code": 200, "data": {"contents": []}})
        return RequestResult(False, _UPDATE_TIME, {"code": 200, "data": {"current_term": {"title": "观点"}}})

    monkeypatch.setattr(infzm_latepost, "get", fake_get)
    # 业务错误壳不得静默降级为空榜
    with pytest.raises(RuntimeError, match="code=401"):
        await infzm_latepost.handle_route(_request("infzm-news"), no_cache=True)
    # 空解析同样报错
    with pytest.raises(RuntimeError, match="parsed no items"):
        await infzm_latepost.handle_route(_request("infzm-opinion"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_board_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await infzm_latepost.handle_route(_request("nosuch"), no_cache=True)


def test_removed_latepost_boards_are_gone():
    boards = infzm_latepost.ROUTE_META["params"]["type"]["type"]
    assert not any(key.startswith("latepost-") for key in boards)
    assert len(boards) == 9
    assert next(iter(boards)) == "infzm-recommend"

from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import nowcoder
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/nowcoder",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "payload", "expected_id", "expected_url"),
    [
        (
            "trending",
            {"data": {"result": [{"type": 0, "id": 101, "uuid": "post-u", "title": "热门帖子", "hotValueFromDolphin": 88}]}},
            "post-u",
            "https://www.nowcoder.com/discuss/101",
        ),
        (
            "hot-search",
            {"data": {"hotQuery": [{"query": "秋招 C++", "hotValue": 77, "ad": False}]}},
            "秋招 C++",
            "https://www.nowcoder.com/search/all?query=%E7%A7%8B%E6%8B%9B%20C%2B%2B",
        ),
        (
            "topics",
            {"data": {"result": [{"uuid": "topic-u", "content": "热门话题", "viewCount": 100, "momentCount": 5, "hotValue": 66}]}},
            "topic-u",
            "https://www.nowcoder.com/creation/subject/topic-u",
        ),
        (
            "recommend",
            {"data": {"records": [{"contentData": {"id": "202", "uuid": "recommend-u", "title": "首页推荐", "content": "正文", "showTime": 1784001658000}, "userBrief": {"nickname": "作者"}, "frequencyData": {"viewCnt": 55, "likeCnt": 2, "commentCnt": 3}}]}},
            "recommend-u",
            "https://www.nowcoder.com/discuss/202",
        ),
    ],
)
async def test_nowcoder_boards(monkeypatch, board_type, payload, expected_id, expected_url):
    async def fake_get(**kwargs):  # noqa: ANN003
        return RequestResult(False, "2026-07-16T00:00:00+00:00", payload)

    monkeypatch.setattr(nowcoder, "get", fake_get)
    route_data = await nowcoder.handle_route(_request(board_type))

    assert route_data.type == nowcoder.type_map[board_type]
    assert route_data.total == 1
    assert route_data.data[0].id == expected_id
    assert route_data.data[0].url == expected_url


@pytest.mark.asyncio
async def test_nowcoder_recommend_filters_ad_cards(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {"data": {"records": [{"contentType": 993, "recommendCreativity": {"title": "广告"}}]}},
        )

    monkeypatch.setattr(nowcoder, "get", fake_get)
    route_data = await nowcoder.handle_route(_request("recommend"))
    assert route_data.data == []

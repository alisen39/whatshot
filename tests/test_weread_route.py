from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import weread
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/weread",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _books_payload() -> dict:
    return {
        "books": [
            {
                "readingCount": 12345,
                "bookInfo": {
                    "bookId": "3300025478",
                    "title": "书名",
                    "author": "作者",
                    "intro": "简介",
                    "cover": "https://wfqqreader.3g.qq.com/cover/1/s.jpg",
                    "publishTime": "2026-01-01 00:00:00",
                },
            }
        ]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "expected_url"),
    [
        # 非数字榜单 id 必须带 rank=1(含既有 5 个分类,行为不变)
        ("newrating_publish", "https://weread.qq.com/web/bookListInCategory/newrating_publish?rank=1"),
        ("newrating_potential_publish", "https://weread.qq.com/web/bookListInCategory/newrating_potential_publish?rank=1"),
        ("rising", "https://weread.qq.com/web/bookListInCategory/rising?rank=1"),
        # 数字分类 id 带 rank=1 会返回 0 本,必须不带
        ("1900000", "https://weread.qq.com/web/bookListInCategory/1900000"),
        ("2000000", "https://weread.qq.com/web/bookListInCategory/2000000"),
    ],
)
async def test_rank_param_follows_category_id_kind(monkeypatch, board_type, expected_url):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured["url"] = url
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _books_payload())

    monkeypatch.setattr(weread, "get", fake_get)
    result = await weread.handle_route(_request(board_type), no_cache=True)

    assert captured["url"] == expected_url
    assert result.total == 1
    item = result.data[0]
    assert item.title == "书名"
    assert item.hot == 12345

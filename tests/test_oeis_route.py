from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import oeis
from whats_hot_api.utils.http_client import RequestResult


SEQUENCE_ROWS = [
    {
        "number": 45,
        "name": "Fibonacci numbers.",
        "data": "0,1,1,2,3,5,8,13,21,34,55,89,144",
        "keyword": "nonn,core,nice,easy",
        "author": "N. J. A. Sloane",
        "created": "1991-04-30T03:00:00-04:00",
        "revision": 2583,
    }
]


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/oeis",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "expected_query", "expected_sort"),
    [
        ("recent", "keyword:new", "created"),
        ("best", "keyword:nice", "relevance"),
        ("more", "keyword:more", "relevance"),
    ],
)
async def test_oeis_official_sequence_boards(
    monkeypatch,
    board_type,
    expected_query,
    expected_sort,
):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://oeis.org/search"
        assert kwargs["params"] == {
            "q": expected_query,
            "fmt": "json",
            "start": "0",
            "sort": expected_sort,
        }
        return RequestResult(
            False,
            "2026-07-17T00:00:00+00:00",
            SEQUENCE_ROWS,
        )

    monkeypatch.setattr(oeis, "get", fake_get)
    route_data = await oeis.handle_route(_request(board_type))
    item = route_data.data[0]

    assert route_data.type == oeis.type_map[board_type]
    assert item.id == "A000045"
    assert item.title == "Fibonacci numbers."
    assert item.author == "N. J. A. Sloane"
    assert item.timestamp == 672994800000
    assert item.url == "https://oeis.org/A000045"
    assert "编号：A000045" in item.desc
    assert "关键词：nonn, core, nice, easy" in item.desc
    assert "另有 1 项" in item.desc
    assert item.hot is None


def test_oeis_parser_deduplicates_and_skips_invalid_rows():
    rows = [
        SEQUENCE_ROWS[0],
        SEQUENCE_ROWS[0],
        {"number": "invalid", "name": "Bad"},
        {"number": 46, "name": ""},
    ]

    items = oeis._parse_sequences(rows, "recent")

    assert [item.id for item in items] == ["A000045"]

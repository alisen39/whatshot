from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import v2ex
from whats_hot_api.utils.http_client import RequestResult


def _request(query: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/v2ex/nodes",
        "query_string": query,
        "headers": [],
    })


def _node(
    node_id: int,
    name: str,
    title: str,
    topics: int,
    stars: int,
) -> dict:
    return {
        "id": node_id,
        "name": name,
        "title": title,
        "topics": topics,
        "stars": stars,
        "url": f"https://www.v2ex.com/go/{name}",
    }


def test_v2ex_nodes_parser_sorts_by_topic_count_and_preserves_identity() -> None:
    payload = [
        _node(300, "programmer", "程序员", 72_121, 9_729),
        _node(12, "qna", "问与答", 240_022, 4_499),
        _node(69, "all4all", "二手交易", 146_473, 8_345),
    ]
    rows = v2ex._parse_nodes(payload)

    assert [row.id for row in rows] == ["12", "69", "300"]
    assert rows[0].title == "问与答（qna）"
    assert rows[0].hot == 240_022
    assert rows[0].desc == "累计主题：240022 · 收藏：4499"
    assert rows[0].url == "https://www.v2ex.com/go/qna"


def test_v2ex_nodes_parser_preserves_upstream_order_for_ties() -> None:
    payload = [
        _node(2, "second", "Second", 100, 2),
        _node(1, "first", "First", 100, 1),
    ]
    assert [row.id for row in v2ex._parse_nodes(payload)] == ["2", "1"]


@pytest.mark.parametrize(
    "override",
    [
        {"id": 0},
        {"name": "bad/name"},
        {"title": ""},
        {"topics": -1},
        {"stars": True},
        {"url": "https://evil.example/go/qna"},
    ],
)
def test_v2ex_nodes_parser_skips_invalid_identity_or_metrics(override: dict) -> None:
    row = _node(12, "qna", "问与答", 240_022, 4_499)
    row.update(override)
    assert v2ex._parse_nodes([row]) == []


def test_v2ex_nodes_parser_rejects_duplicate_node_identity() -> None:
    first = _node(12, "qna", "问与答", 240_022, 4_499)
    duplicate = _node(12, "qna-copy", "问与答副本", 1, 0)
    assert v2ex._parse_nodes([first, duplicate]) == []


@pytest.mark.asyncio
async def test_v2ex_nodes_route_fetches_fixed_global_catalog(monkeypatch) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == v2ex._NODES_URL
        assert kwargs["cache_key"] == "v2ex:nodes:topics"
        return RequestResult(
            data=[_node(12, "qna", "问与答", 240_022, 4_499)],
            from_cache=False,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(v2ex, "get", fake_get)
    result = await v2ex.handle_route(_request(b"type=nodes"), True)

    assert result.name == "v2ex"
    assert result.type == "主题最多节点"
    assert result.total == 1

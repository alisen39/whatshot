from __future__ import annotations

from copy import deepcopy

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import yahoo
from whats_hot_api.utils.http_client import RequestResult


def _row(rank: int, **overrides: object) -> dict:
    row = {
        "id": f"{rank:08x}-1234-4123-8123-{rank:012x}",
        "rank": rank,
        "categoryGroup": "News",
        "overrideCategoryGroup": None,
        "topicLabel": f"Yahoo topic {rank}",
        "overrideLabel": None,
        "longLabel": f"Long Yahoo topic {rank}",
        "overrideLongLabel": None,
        "topicDescription": f"Description for Yahoo topic {rank}.",
        "overrideDescription": None,
        "badges": ["New"] if rank == 1 else [],
        "topHashtag": "breaking" if rank == 1 else None,
        "topHashtagUrl": None,
        "topPlatform": None,
    }
    row.update(overrides)
    return row


def _payload(rows: list[dict], token: str | None = None) -> dict:
    return {
        "data": {
            "listY100Topics": {
                "nextToken": token,
                "items": rows,
            }
        }
    }


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/yahoo/default",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_yahoo_fetches_two_pages_of_official_yahoo_100(monkeypatch):
    calls: list[dict] = []

    async def fake_post(**kwargs):  # noqa: ANN003
        calls.append(kwargs)
        assert kwargs["url"] == "https://nexus-gateway-prod.media.yahoo.com"
        assert kwargs["headers"]["x-yahoo-cg-client-name"] == "news"
        assert kwargs["ttl"] == 600
        token = kwargs["body"]["variables"]["nextToken"]
        if token is None:
            return RequestResult(
                False,
                "2026-07-18T00:00:00+00:00",
                _payload([_row(rank) for rank in range(1, 61)], "page-2"),
            )
        assert token == "page-2"
        return RequestResult(
            False,
            "2026-07-18T00:00:01+00:00",
            _payload([_row(rank) for rank in range(61, 101)], "page-3"),
        )

    monkeypatch.setattr(yahoo, "post", fake_post)
    result = await yahoo.handle_route(_request(), True)

    assert result.name == "yahoo"
    assert result.type == "Yahoo 100"
    assert result.total == 100
    assert len(calls) == 2
    assert [item.id for item in result.data[:2]] == [
        "00000001-1234-4123-8123-000000000001",
        "00000002-1234-4123-8123-000000000002",
    ]
    assert result.data[0].author == "News"
    assert result.data[0].url.endswith(
        "#00000001-1234-4123-8123-000000000001"
    )
    assert "标记：New" in (result.data[0].desc or "")
    assert "热门标签：#breaking" in (result.data[0].desc or "")
    assert result.updateTime == "2026-07-18T00:00:01+00:00"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "bad-id"),
        ("rank", 0),
        ("topicLabel", ""),
        ("topicDescription", ""),
        ("categoryGroup", "Unknown"),
    ],
)
def test_yahoo_parser_rejects_invalid_topic_contract(field, value):
    rows = [_row(rank) for rank in range(1, 101)]
    rows[0][field] = value
    assert yahoo._parse_topics(rows) == []


def test_yahoo_parser_rejects_rank_gaps_duplicate_ids_and_titles():
    rows = [_row(rank) for rank in range(1, 101)]
    assert yahoo._parse_topics(rows[:-1]) == []

    duplicate_id = deepcopy(rows)
    duplicate_id[1]["id"] = duplicate_id[0]["id"]
    assert yahoo._parse_topics(duplicate_id) == []

    duplicate_title = deepcopy(rows)
    duplicate_title[1]["topicLabel"] = "Yahoo---topic 1"
    assert yahoo._parse_topics(duplicate_title) == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"errors": [{"message": "blocked"}]},
        {"data": {}},
        _payload([]),
        _payload([_row(1)], ""),
        _payload(["not-a-row"]),
    ],
)
def test_yahoo_page_contract_rejects_malformed_payload(payload):
    assert yahoo._page_contract(payload) is None

from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.models import ListItem, NewsFlashItem
from whats_hot_api.routes.newsflash import anthropic_engineering


def _request(query_string: bytes = b"type=engineering") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/anthropic-engineering/engineering",
            "query_string": query_string,
            "headers": [],
        }
    )


def _item() -> ListItem:
    return ListItem(
        id="https://www.anthropic.com/engineering/example",
        title="Engineering example",
        desc="A verified feed excerpt.",
        cover="https://www.anthropic.com/example.png",
        timestamp=1787702400000,
        url="https://www.anthropic.com/engineering/example",
    )


def test_normalizes_engineering_publication_as_newsflash() -> None:
    assert anthropic_engineering._as_newsflash(_item()) == NewsFlashItem(
        id="https://www.anthropic.com/engineering/example",
        title="Engineering example",
        content="A verified feed excerpt.",
        summary="A verified feed excerpt.",
        contentStatus="summary",
        source="Anthropic",
        tags=["Engineering"],
        images=["https://www.anthropic.com/example.png"],
        timestamp=1787702400000,
        url="https://www.anthropic.com/engineering/example",
        mobileUrl="https://www.anthropic.com/engineering/example",
    )


async def test_route_accepts_grouped_engineering_type(monkeypatch) -> None:
    async def fake_fetch(**kwargs):
        assert kwargs == {
            "route_name": "anthropic-engineering",
            "route_path": "/anthropic/engineering",
            "params": {},
            "no_cache": True,
        }
        return {
            "from_cache": False,
            "update_time": "2026-08-27T00:00:00+00:00",
            "data": [_item()],
        }

    monkeypatch.setattr(anthropic_engineering, "fetch_rsshub_feed", fake_fetch)

    result = await anthropic_engineering.handle_route(_request(), no_cache=True)

    assert result.kind == "newsflash"
    assert result.type == "Engineering"
    assert result.total == 1


async def test_route_rejects_empty_feed(monkeypatch) -> None:
    async def fake_fetch(**kwargs):
        return {
            "from_cache": False,
            "update_time": "2026-08-27T00:00:00+00:00",
            "data": [],
        }

    monkeypatch.setattr(anthropic_engineering, "fetch_rsshub_feed", fake_fetch)

    with pytest.raises(RuntimeError, match="no usable items"):
        await anthropic_engineering.handle_route(_request())


def test_route_declares_only_grouped_engineering_type() -> None:
    assert anthropic_engineering.ROUTE_META["params"]["type"]["type"] == {
        "engineering": "Engineering"
    }

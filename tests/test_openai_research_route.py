from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.models import ListItem, NewsFlashItem
from whats_hot_api.routes.newsflash import openai_research


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/openai-research/research",
            "query_string": b"type=research",
            "headers": [],
        }
    )


def _item() -> ListItem:
    return ListItem(
        id="https://openai.com/index/example",
        title="Research example",
        desc="A verified feed excerpt.",
        cover="https://images.ctfassets.net/example.png",
        timestamp=1787702400000,
        url="https://openai.com/index/example/",
    )


def test_normalizes_research_publication_as_newsflash() -> None:
    assert openai_research._as_newsflash(_item()) == NewsFlashItem(
        id="https://openai.com/index/example",
        title="Research example",
        content="A verified feed excerpt.",
        summary="A verified feed excerpt.",
        contentStatus="summary",
        source="OpenAI",
        tags=["Research"],
        images=["https://images.ctfassets.net/example.png"],
        timestamp=1787702400000,
        url="https://openai.com/index/example/",
        mobileUrl="https://openai.com/index/example/",
    )


async def test_route_accepts_grouped_research_type(monkeypatch) -> None:
    async def fake_fetch(**kwargs):
        assert kwargs == {
            "route_name": "openai-research",
            "route_path": "/openai/research",
            "params": {},
            "no_cache": True,
        }
        return {
            "from_cache": False,
            "update_time": "2026-08-27T00:00:00+00:00",
            "data": [_item()],
        }

    monkeypatch.setattr(openai_research, "fetch_rsshub_feed", fake_fetch)

    result = await openai_research.handle_route(_request(), no_cache=True)

    assert result.kind == "newsflash"
    assert result.type == "Research"
    assert result.total == 1


async def test_route_rejects_empty_feed(monkeypatch) -> None:
    async def fake_fetch(**kwargs):
        return {
            "from_cache": False,
            "update_time": "2026-08-27T00:00:00+00:00",
            "data": [],
        }

    monkeypatch.setattr(openai_research, "fetch_rsshub_feed", fake_fetch)

    with pytest.raises(RuntimeError, match="no usable items"):
        await openai_research.handle_route(_request())


def test_route_declares_only_grouped_research_type() -> None:
    assert openai_research.ROUTE_META["params"]["type"]["type"] == {
        "research": "Research"
    }


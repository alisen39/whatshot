from __future__ import annotations

import pytest

from whats_hot_api.utils import rsshub
from whats_hot_api.utils.http_client import CacheOnlyMiss, RequestResult


@pytest.mark.asyncio
async def test_fetch_rsshub_feed_falls_back_and_maps_items(monkeypatch):
    calls: list[str] = []

    async def fake_get(**kwargs):  # noqa: ANN003
        calls.append(kwargs["url"])
        if len(calls) == 1:
            raise RuntimeError("instance down")
        return RequestResult(
            False,
            "rsshub-update",
            {
                "items": [
                    {
                        "id": "item-1",
                        "title": "RSSHub article",
                        "url": "https://example.com/article",
                        "content_text": "Useful summary",
                        "date_published": "2026-07-06T09:30:00Z",
                    }
                ]
            },
        )

    monkeypatch.setattr(rsshub, "get", fake_get)
    monkeypatch.setattr(rsshub, "_base_urls", lambda: ["https://one.test", "https://two.test"])

    result = await rsshub.fetch_rsshub_feed(
        route_name="example",
        route_path="/example/feed",
        params={"lang": "en"},
        no_cache=False,
    )

    assert calls == ["https://one.test/example/feed", "https://two.test/example/feed"]
    assert result["from_cache"] is False
    assert result["update_time"] == "rsshub-update"
    assert result["data"][0].id == "item-1"
    assert result["data"][0].desc == "Useful summary"


@pytest.mark.asyncio
async def test_fetch_rsshub_feed_preserves_cache_only_miss(monkeypatch):
    calls = 0

    async def cache_miss(**kwargs):  # noqa: ANN003, ARG001
        nonlocal calls
        calls += 1
        raise CacheOnlyMiss("rsshub-cache-key")

    monkeypatch.setattr(rsshub, "get", cache_miss)
    monkeypatch.setattr(rsshub, "_base_urls", lambda: ["https://one.test", "https://two.test"])

    with pytest.raises(CacheOnlyMiss):
        await rsshub.fetch_rsshub_feed(
            route_name="example",
            route_path="/example/feed",
            params={},
            no_cache=True,
        )

    assert calls == 2

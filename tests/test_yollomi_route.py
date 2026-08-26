from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import yollomi
from whats_hot_api.utils.http_client import RequestResult


def _request(query: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/yollomi/all",
            "query_string": query,
            "headers": [],
        }
    )


def _item(
    *,
    item_id: str = "item-1",
    kind: str = "image",
    title: str = "A black cat taking a bubble bath",
    author: str = "moon mouth",
    likes: object = 12,
) -> dict:
    suffix = "png" if kind == "image" else "mp4"
    media_url = (
        "https://pub-f11e69dd929f418fb2fd4811764d8285.r2.dev/"
        f"explore/{item_id}.{suffix}"
    )
    return {
        "id": item_id,
        "title": title,
        "author": author,
        "likes": likes,
        "image": media_url,
        "type": kind,
        "previewData": {
            "media_url": media_url,
            "media_type": "TEXT_TO_IMAGE" if kind == "image" else "TEXT_TO_VIDEO",
            "created_time": "2026-03-05T17:02:00+08:00",
            "model": "google/nano-banana-pro",
            "username": "fallback user",
        },
    }


def test_yollomi_parser_maps_verified_explore_fields_in_order() -> None:
    long_title = "A cinematic ocean scene " + "with warm light " * 20
    rows = yollomi._parse_items(
        {"items": [_item(), _item(item_id="item-2", kind="video", title=long_title)]},
        "all",
    )

    assert len(rows) == 2
    assert rows[0].id == "item-1"
    assert rows[0].title == "A black cat taking a bubble bath"
    assert rows[0].author == "moon mouth"
    assert rows[0].hot == 12
    assert rows[0].cover.endswith("/explore/item-1.png")
    assert rows[0].timestamp == 1772701320000
    assert rows[0].url.endswith("/explore/item-1.png")
    assert rows[0].desc.startswith("类型：图片 · 模型：google/nano-banana-pro")
    assert rows[1].cover is None
    assert rows[1].title.endswith("…")


def test_yollomi_parser_filters_board_and_skips_invalid_rows() -> None:
    image = _item()
    bad_host = _item(item_id="bad-host")
    bad_host["previewData"]["media_url"] = "https://example.com/file.png"
    duplicate = _item()
    missing_title = _item(item_id="missing-title", title="")

    rows = yollomi._parse_items(
        {
            "items": [
                image,
                _item(item_id="video", kind="video"),
                bad_host,
                duplicate,
                missing_title,
            ]
        },
        "images",
    )

    assert [row.id for row in rows] == ["item-1"]


@pytest.mark.asyncio
async def test_yollomi_route_uses_verified_explore_api_contract(monkeypatch) -> None:
    async def fake_get(**kwargs):
        assert kwargs == {
            "url": "https://yollomi.com/api/explore",
            "params": {"type": "videos", "limit": "50", "offset": "0"},
            "no_cache": True,
            "cache_key": "yollomi:explore:videos",
            "response_type": "json",
        }
        return RequestResult(
            data={"items": [_item(item_id="video", kind="video")]},
            from_cache=False,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(yollomi, "get", fake_get)
    result = await yollomi.handle_route(_request(b"type=videos"), True)

    assert result.name == "yollomi"
    assert result.type == "视频作品"
    assert result.total == 1
    assert result.data[0].cover is None


@pytest.mark.asyncio
async def test_yollomi_route_falls_back_to_all(monkeypatch) -> None:
    async def fake_get(**kwargs):
        assert kwargs["params"] == {"type": "all", "limit": "50", "offset": "0"}
        return RequestResult(
            data={"items": [_item()]},
            from_cache=True,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(yollomi, "get", fake_get)
    result = await yollomi.handle_route(_request(b"type=latest"))

    assert result.type == "综合公开作品"
    assert result.fromCache is True

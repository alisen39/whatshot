from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import yollomi
from whats_hot_api.utils.http_client import RequestResult


def _request(query: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/yollomi/all",
        "query_string": query,
        "headers": [],
    })


def _token(media_url: str, created_time: str = "2026-03-05T17:02:00+08:00") -> str:
    raw = json.dumps(
        {"mediaUrl": media_url, "createdTime": created_time},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _card(
    kind: str = "Image",
    media_url: str = (
        "https://pub-f11e69dd929f418fb2fd4811764d8285.r2.dev/explore/sample.png"
    ),
    prompt: str = "A black cat taking a bubble bath",
    model: str = "google/nano-banana-pro",
) -> str:
    token = _token(media_url)
    return f"""
    <a href="/creation/{token}">
      <span>{kind}</span>
      <p class="line-clamp-3">{prompt}</p>
      <span class="inline-flex min-w-0">{model}</span>
    </a>
    """


def test_yollomi_parser_preserves_public_gallery_order_and_identity() -> None:
    video_url = (
        "https://pub-f11e69dd929f418fb2fd4811764d8285.r2.dev/videos/sample.mp4"
    )
    html = _card() + _card(
        "Video",
        video_url,
        "A cinematic ocean scene " + "with warm light " * 20,
        "pixverse/pixverse-v5",
    )

    rows = yollomi._parse_gallery(html, "all")

    assert len(rows) == 2
    assert rows[0].title == "A black cat taking a bubble bath"
    assert rows[0].author == "google/nano-banana-pro"
    assert rows[0].cover.endswith("/explore/sample.png")
    assert rows[0].timestamp == 1772701320000
    assert rows[0].url.startswith("https://yollomi.com/creation/")
    assert len(rows[0].id) == 64
    assert rows[1].author == "pixverse/pixverse-v5"
    assert rows[1].cover is None
    assert rows[1].title.endswith("…")


def test_yollomi_filtered_board_rejects_wrong_content_kind() -> None:
    assert yollomi._parse_gallery(_card("Image"), "videos") == []


@pytest.mark.parametrize(
    "html",
    [
        _card(media_url="https://example.com/sample.png"),
        _card(kind="Video"),
        _card(prompt=""),
        _card(model=""),
    ],
)
def test_yollomi_parser_rejects_invalid_public_card_contract(html: str) -> None:
    assert yollomi._parse_gallery(html, "all") == []


def test_yollomi_parser_rejects_duplicate_creation_identity() -> None:
    card = _card()
    assert yollomi._parse_gallery(card + card, "all") == []


@pytest.mark.asyncio
async def test_yollomi_route_fetches_only_selected_public_gallery(monkeypatch) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://yollomi.com/gallery?type=videos"
        assert kwargs["cache_key"] == "yollomi:gallery:videos"
        assert kwargs["response_type"] == "text"
        return RequestResult(
            data=_card(
                "Video",
                "https://pub-f11e69dd929f418fb2fd4811764d8285.r2.dev/videos/sample.mp4",
            ),
            from_cache=False,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(yollomi, "get", fake_get)
    result = await yollomi.handle_route(_request(b"type=videos"), True)

    assert result.name == "yollomi"
    assert result.type == "视频作品"
    assert result.total == 1


@pytest.mark.asyncio
async def test_yollomi_route_falls_back_to_all(monkeypatch) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://yollomi.com/gallery"
        return RequestResult(
            data=_card(),
            from_cache=True,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(yollomi, "get", fake_get)
    result = await yollomi.handle_route(_request(b"type=latest"))
    assert result.type == "综合公开作品"

from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import telegram_osint
from whats_hot_api.utils.http_client import RequestResult


def _request(query_string: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/telegram-osint",
        "query_string": query_string,
        "headers": [],
    })


@pytest.mark.asyncio
async def test_telegram_osint_maps_public_channel_posts(monkeypatch):
    html = """
    <div class="tgme_widget_message" data-post="wartranslated/17384">
      <div class="tgme_widget_message_text">First line<br>Additional context &amp; source</div>
      <span class="tgme_widget_message_views">12.3K</span>
      <time datetime="2026-07-15T17:33:51+00:00"></time>
    </div>
    <div class="tgme_widget_message" data-post="wartranslated/17385">
      <a class="tgme_widget_message_photo"></a>
      <time datetime="2026-07-15T17:34:51+00:00"></time>
    </div>
    <div class="tgme_widget_message" data-post="another/1">
      <div class="tgme_widget_message_text">Wrong channel</div>
    </div>
    """

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://t.me/s/wartranslated"
        assert kwargs["response_type"] == "text"
        return RequestResult(False, "2026-07-16T00:00:00+00:00", html)

    monkeypatch.setattr(telegram_osint, "get", fake_get)
    route_data = await telegram_osint.handle_route(_request(b"type=wartranslated"))
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.type == "War Translated"
    assert route_data.total == 1
    assert item.id == "wartranslated/17384"
    assert item.title == "First line"
    assert item.content == "First line\nAdditional context & source"
    assert item.source == "War Translated"
    assert item.metrics == {
        "views": 12300,
        "channel": "wartranslated",
        "hasMedia": False,
    }
    assert item.timestamp == 1784136831000
    assert item.url == "https://t.me/wartranslated/17384"


@pytest.mark.asyncio
async def test_telegram_osint_unknown_type_uses_default(monkeypatch):
    async def fake_channel(selected_type, no_cache):  # noqa: ANN001, ARG001
        assert selected_type == "intelslava"
        return {"from_cache": False, "update_time": "2026-07-16T00:00:00+00:00", "data": []}

    monkeypatch.setattr(telegram_osint, "_get_channel", fake_channel)
    route_data = await telegram_osint.handle_route(_request(b"type=unknown"))
    assert route_data.type == "Intel Slava Z"

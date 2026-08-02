from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import spotify
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/spotify/default",
        "query_string": b"",
        "headers": [],
    })


def _html(*tracks: dict, **entity_overrides: object) -> str:
    entity = {
        "id": "37i9dQZEVXbMDoHDwVN2tF",
        "uri": "spotify:playlist:37i9dQZEVXbMDoHDwVN2tF",
        "name": "Top 50 - Global",
        "subtitle": "Spotify",
        "format": "chart",
        "attributes": [
            {"key": "last_updated", "value": "2026-07-17T15:46:48Z"},
            {"key": "rank_type", "value": "plays"},
            {"key": "chart_entity_type", "value": "track"},
        ],
        "trackList": list(tracks),
    }
    entity.update(entity_overrides)
    payload = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}"
        "</script></html>"
    )


def _track(
    track_id: str = "5qqabIl2vWzo9ApSC317sa",
    title: str = "Wonderwall - Remastered",
    artist: str = "Oasis",
    **overrides: object,
) -> dict:
    row = {
        "uri": f"spotify:track:{track_id}",
        "title": title,
        "subtitle": artist,
        "duration": 258773,
        "isExplicit": False,
        "entityType": "track",
    }
    row.update(overrides)
    return row


def test_spotify_parser_preserves_rank_and_uses_track_identity() -> None:
    duplicate = _track(title="Duplicate title")
    explicit = _track(
        "0kosUz0jePvjiz4ctmR6wL",
        "Dai Dai",
        "Shakira,\xa0Burna Boy",
        duration=223448,
        isExplicit=True,
    )
    invalid = _track("not-a-track-id", "Invalid", "Nobody")

    rows = spotify._parse_playlist(_html(_track(), duplicate, explicit, invalid))

    assert [row.id for row in rows] == [
        "5qqabIl2vWzo9ApSC317sa",
        "0kosUz0jePvjiz4ctmR6wL",
    ]
    assert rows[0].url == (
        "https://open.spotify.com/track/5qqabIl2vWzo9ApSC317sa"
    )
    assert rows[0].desc == "时长：4:18"
    assert rows[1].author == "Shakira, Burna Boy"
    assert rows[1].desc == "时长：3:43 · Explicit"


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("id", "another-playlist"),
        ("subtitle", "Unofficial curator"),
        ("format", "playlist"),
        ("attributes", [{"key": "rank_type", "value": "editorial"}]),
    ],
)
def test_spotify_parser_rejects_non_chart_or_spoofed_playlist(
    override: str,
    value: object,
) -> None:
    assert spotify._parse_playlist(_html(_track(), **{override: value})) == []


@pytest.mark.asyncio
async def test_spotify_route_fetches_anonymous_global_chart(monkeypatch) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == (
            "https://open.spotify.com/embed/playlist/37i9dQZEVXbMDoHDwVN2tF"
        )
        assert kwargs["cache_key"] == "spotify:global-top-50"
        assert kwargs["response_type"] == "text"
        return RequestResult(
            data=_html(_track()),
            from_cache=False,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(spotify, "get", fake_get)
    result = await spotify.handle_route(_request(), True)

    assert result.name == "spotify"
    assert result.type == "全球 Top 50"
    assert result.total == 1
    assert result.data[0].author == "Oasis"

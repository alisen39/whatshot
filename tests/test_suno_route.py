from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import suno
from whats_hot_api.utils.http_client import RequestResult


PLAYLIST_ID = "23a0d3b1-52b0-4a49-a0b0-9be7fb08d199"
CLIP_ID = "f8959afc-5ad7-46f4-8607-c3f844c342cc"


def _request(query: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/suno/trending",
        "query_string": query,
        "headers": [],
    })


def _clip(clip_id: str = CLIP_ID, **overrides: object) -> dict:
    clip = {
        "id": clip_id,
        "entity_type": "song_schema",
        "title": "Raise the Banner",
        "display_name": "RΛ$HTΞK",
        "play_count": 20998,
        "upvote_count": 462,
        "created_at": "2026-07-03T13:14:23.513Z",
        "is_public": True,
        "status": "complete",
        "model_name": "chirp-auk",
        "image_url": f"https://cdn2.suno.ai/image_{clip_id}.jpeg",
        "metadata": {"duration": 194.96, "tags": "phonk, trap\n140 BPM"},
    }
    clip.update(overrides)
    return clip


def _feed(
    title: str = "Trending: Sports Anthems",
    playlist_id: str = PLAYLIST_ID,
    *clips: dict,
    **overrides: object,
) -> dict:
    feed = {
        "feed_id": f"generic_playlist:{playlist_id}",
        "feed_title": title,
        "feed_container_type": "playlist",
        "feed_container_id": playlist_id,
        "feed_direct_link": f"/playlist/{playlist_id}",
        "items": [
            {
                "content_id": clip["id"],
                "content_type": "clip",
                "content_item": clip,
            }
            for clip in clips
        ],
    }
    feed.update(overrides)
    return feed


def _payload(*feeds: dict) -> dict:
    return {
        "feeds": [
            {"feed_id": "new_songs", "feed_title": "New Songs", "items": []},
            *feeds,
        ],
    }


def test_suno_parser_preserves_editorial_order_and_song_identity() -> None:
    duplicate = _clip(title="Duplicate")
    second = _clip(
        "7b2a16b5-e38c-43e8-9ce0-e0eacbc49a05",
        title="LET'S GO USA!",
        display_name="Silas Thompson\xa0",
        metadata={"duration": 117.04, "tags": "stadium anthem"},
    )
    invalid = _clip("not-a-uuid")
    payload = _payload(_feed("Trending: Sports Anthems", PLAYLIST_ID, _clip(), duplicate, second, invalid))

    parsed = suno._parse_board(payload, "trending")
    rows = parsed["data"]

    assert parsed["link"] == f"https://suno.com/playlist/{PLAYLIST_ID}"
    assert [row.id for row in rows] == [CLIP_ID, second["id"]]
    assert rows[0].url == f"https://suno.com/song/{CLIP_ID}"
    assert rows[0].hot == 20998
    assert rows[0].timestamp == 1783084463513
    assert rows[0].desc == "模型：chirp-auk · 时长：3:15 · phonk, trap 140 BPM · 点赞：462"
    assert rows[1].author == "Silas Thompson"


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("feed_container_type", "synthetic_playlist"),
        ("feed_container_id", "990fd5fe-70d2-449b-8a4d-3cb0a7d3e805"),
        ("feed_direct_link", "/explore"),
    ],
)
def test_suno_parser_rejects_spoofed_playlist_identity(
    override: str,
    value: object,
) -> None:
    payload = _payload(_feed("Staff Picks", PLAYLIST_ID, _clip(), **{override: value}))
    assert suno._parse_board(payload, "staff-picks")["data"] == []


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("entity_type", "video_schema"),
        ("is_public", False),
        ("status", "streaming"),
        ("title", ""),
    ],
)
def test_suno_parser_rejects_non_public_or_incomplete_song(
    override: str,
    value: object,
) -> None:
    payload = _payload(_feed("Best of v5.5", PLAYLIST_ID, _clip(**{override: value})))
    assert suno._parse_board(payload, "best-model")["data"] == []


def test_suno_parser_rejects_ambiguous_matching_feeds() -> None:
    payload = _payload(
        _feed("Staff Picks", PLAYLIST_ID, _clip()),
        _feed(
            "Staff Picks",
            "990fd5fe-70d2-449b-8a4d-3cb0a7d3e805",
            _clip(),
        ),
    )
    assert suno._parse_board(payload, "staff-picks")["data"] == []


@pytest.mark.asyncio
async def test_suno_route_fetches_public_explore_collection(monkeypatch) -> None:
    async def fake_post(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == (
            "https://studio-api-prod.suno.com/api/unified/homepage/explore"
        )
        assert kwargs["body"] == {"cursor": None, "page_size": 20}
        assert kwargs["cache_key"] == "suno:explore"
        return RequestResult(
            data=_payload(_feed("Staff Picks", PLAYLIST_ID, _clip())),
            from_cache=False,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(suno, "post", fake_post)
    result = await suno.handle_route(_request(b"type=staff-picks"), True)

    assert result.name == "suno"
    assert result.type == "编辑精选"
    assert result.total == 1
    assert result.link == f"https://suno.com/playlist/{PLAYLIST_ID}"


@pytest.mark.asyncio
async def test_suno_route_falls_back_to_trending(monkeypatch) -> None:
    async def fake_post(**kwargs):  # noqa: ANN003
        return RequestResult(
            data=_payload(_feed("Trending: Sports Anthems", PLAYLIST_ID, _clip())),
            from_cache=True,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(suno, "post", fake_post)
    result = await suno.handle_route(_request(b"type=unknown"))
    assert result.type == "主题趋势"

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import tvmaze
from whats_hot_api.utils.http_client import RequestResult


def _request(query: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/tvmaze/us",
        "query_string": query,
        "headers": [],
    })


def _show(show_id: int = 55087, name: str = "Wan Jie Du Zun") -> dict:
    return {
        "id": show_id,
        "name": name,
        "network": {"name": "MS NOW"},
        "webChannel": {"name": "Tencent QQ"},
        "image": {"medium": "https://static.tvmaze.com/show.jpg"},
    }


def _episode(
    episode_id: int = 3551514,
    *,
    board_type: str = "web",
    airstamp: str = "2026-07-18T02:00:00+00:00",
    **overrides: object,
) -> dict:
    show = _show()
    row = {
        "id": episode_id,
        "url": f"https://www.tvmaze.com/episodes/{episode_id}/wan-jie-du-zun-3x192-episode-466",
        "name": "Episode 466",
        "season": 3,
        "number": 192,
        "airstamp": airstamp,
        "runtime": 8,
        "summary": "<p>Lin Feng &amp; friends.</p>",
        "image": {"original": "https://static.tvmaze.com/episode.jpg"},
        "_links": {
            "self": {"href": f"https://api.tvmaze.com/episodes/{episode_id}"},
            "show": {"href": "https://api.tvmaze.com/shows/55087", "name": "Wan Jie Du Zun"},
        },
    }
    if board_type == "web":
        row["_embedded"] = {"show": show}
    else:
        row["show"] = show
    row.update(overrides)
    return row


def test_tvmaze_parser_preserves_episode_identity_and_air_order() -> None:
    second = _episode(3551515, airstamp="2026-07-18T03:00:00+00:00")
    rows = tvmaze._parse_schedule([_episode(), _episode(), second], "web")

    assert [row.id for row in rows] == ["3551514", "3551515"]
    assert rows[0].title == "Wan Jie Du Zun：Episode 466"
    assert rows[0].author == "Tencent QQ"
    assert rows[0].timestamp == 1784340000000
    assert rows[0].desc == "S03E192 · Tencent QQ · 8 分钟 · Lin Feng & friends."
    assert rows[0].cover == "https://static.tvmaze.com/episode.jpg"


def test_tvmaze_parser_supports_network_schedule_shape() -> None:
    rows = tvmaze._parse_schedule([_episode(board_type="us")], "us")
    assert len(rows) == 1
    assert rows[0].author == "MS NOW"


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("id", "bad"),
        ("name", ""),
        ("url", "https://www.tvmaze.com/episodes/999/wrong"),
        ("airstamp", "not-a-date"),
        ("_links", {}),
    ],
)
def test_tvmaze_parser_rejects_inconsistent_episode_identity(
    override: str,
    value: object,
) -> None:
    assert tvmaze._parse_schedule([_episode(**{override: value})], "web") == []


def test_tvmaze_parser_rejects_non_chronological_payload() -> None:
    later = _episode(airstamp="2026-07-18T04:00:00+00:00")
    earlier = _episode(3551515, airstamp="2026-07-18T03:00:00+00:00")
    assert tvmaze._parse_schedule([later, earlier], "web") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "url", "label"),
    [
        ("us", "https://api.tvmaze.com/schedule", "美国电视今日播出"),
        ("web", "https://api.tvmaze.com/schedule/web", "全球流媒体今日播出"),
    ],
)
async def test_tvmaze_route_fetches_official_schedule(
    monkeypatch,
    board_type: str,
    url: str,
    label: str,
) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == url
        assert kwargs["cache_key"] == f"tvmaze:schedule:{board_type}"
        return RequestResult(
            data=[_episode(board_type=board_type)],
            from_cache=False,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(tvmaze, "get", fake_get)
    result = await tvmaze.handle_route(_request(f"type={board_type}".encode()), True)

    assert result.name == "tvmaze"
    assert result.type == label
    assert result.total == 1

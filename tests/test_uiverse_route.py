from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import uiverse
from whats_hot_api.utils.http_client import RequestResult


def _request(query: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/uiverse/default",
        "query_string": query,
        "headers": [],
    })


def _payload(board_type: str, *rows: tuple[str, str, str, str]) -> str:
    label = {"favorites": "Favorites", "views": "Views", "recent": "Recent"}[board_type]
    blocks = []
    for username, slug, views, favorites in rows:
        blocks.append(
            f"""[Get code](http://uiverse.io/{username}/{slug})

[Link to post](http://uiverse.io/{username}/{slug})

[{username}](http://uiverse.io/profile/{username})

{views} views {favorites}
"""
        )
    return (
        "Title: 4417 UI elements: CSS & Tailwind\n\n"
        f"URL Source: http://uiverse.io/elements?orderBy={board_type}\n\n"
        f"Sort: {label} Any theme\n\n"
        + "\n".join(blocks)
    )


def test_uiverse_favorites_parser_preserves_identity_and_metrics() -> None:
    payload = _payload(
        "favorites",
        ("ElSombrero2", "tricky-robin-67", "121K", "7.4K"),
        ("Praashoo7", "smooth-crab-52", "70K", "6.2K"),
    )
    rows = uiverse._parse_elements(payload, "favorites")

    assert [row.id for row in rows] == [
        "ElSombrero2/tricky-robin-67",
        "Praashoo7/smooth-crab-52",
    ]
    assert rows[0].title == "Tricky robin 67"
    assert rows[0].author == "ElSombrero2"
    assert rows[0].hot == 7_400
    assert rows[0].desc == "121000 次浏览 · 7400 次收藏"
    assert rows[0].url == "https://uiverse.io/ElSombrero2/tricky-robin-67"


def test_uiverse_views_parser_requires_non_increasing_view_order() -> None:
    valid = _payload(
        "views",
        ("one", "first-1", "121K", "7K"),
        ("two", "second-2", "120K", "9K"),
    )
    assert [row.hot for row in uiverse._parse_elements(valid, "views")] == [121_000, 120_000]

    reversed_payload = _payload(
        "views",
        ("one", "first-1", "120K", "7K"),
        ("two", "second-2", "121K", "9K"),
    )
    assert uiverse._parse_elements(reversed_payload, "views") == []


def test_uiverse_recent_parser_keeps_upstream_order_not_view_order() -> None:
    payload = _payload(
        "recent",
        ("new", "fresh-post-1", "14", "1"),
        ("older", "earlier-post-2", "47", "2"),
    )
    rows = uiverse._parse_elements(payload, "recent")

    assert [row.id for row in rows] == ["new/fresh-post-1", "older/earlier-post-2"]
    assert [row.hot for row in rows] == [14, 47]


def test_uiverse_parser_keeps_lazy_rows_without_metrics() -> None:
    payload = _payload("recent", ("new", "fresh-post-1", "14", "1"))
    payload += """
[Get code](http://uiverse.io/lazy/lazy-post-2)

[Link to post](http://uiverse.io/lazy/lazy-post-2)

[lazy](http://uiverse.io/profile/lazy)
"""
    rows = uiverse._parse_elements(payload, "recent")

    assert [row.id for row in rows] == ["new/fresh-post-1", "lazy/lazy-post-2"]
    assert rows[1].hot is None
    assert rows[1].desc is None


@pytest.mark.parametrize("value, expected", [("47", 47), ("7.4K", 7400), ("1.2M", 1_200_000)])
def test_uiverse_compact_count(value: str, expected: int) -> None:
    assert uiverse._compact_count(value) == expected


def test_uiverse_parser_rejects_wrong_board_marker() -> None:
    payload = _payload("recent", ("new", "fresh-post-1", "14", "1"))
    assert uiverse._parse_elements(payload, "views") == []


def test_uiverse_parser_rejects_spoofed_identity_links() -> None:
    payload = _payload("favorites", ("author", "stable-post-1", "20", "10"))
    payload = payload.replace("[author](http://uiverse.io/profile/author)", "[other](http://uiverse.io/profile/other)")
    assert uiverse._parse_elements(payload, "favorites") == []


def test_uiverse_parser_deduplicates_component_identity() -> None:
    row = ("author", "stable-post-1", "20", "10")
    assert len(uiverse._parse_elements(_payload("favorites", row, row), "favorites")) == 1


@pytest.mark.asyncio
async def test_uiverse_route_fetches_fixed_reader_board(monkeypatch) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == f"{uiverse._READER_BASE}?orderBy=views"
        assert kwargs["response_type"] == "text"
        assert kwargs["cache_key"] == "uiverse:elements:views:page-1"
        return RequestResult(
            data=_payload("views", ("author", "stable-post-1", "20", "10")),
            from_cache=False,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(uiverse, "get", fake_get)
    result = await uiverse.handle_route(_request(b"type=views"), True)

    assert result.name == "uiverse"
    assert result.type == "浏览最多"
    assert result.total == 1


@pytest.mark.asyncio
async def test_uiverse_route_falls_back_to_favorites(monkeypatch) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("orderBy=favorites")
        return RequestResult(
            data=_payload("favorites", ("author", "stable-post-1", "20", "10")),
            from_cache=True,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(uiverse, "get", fake_get)
    result = await uiverse.handle_route(_request(b"type=randomized"))

    assert result.type == "收藏最多"
    assert result.fromCache is True

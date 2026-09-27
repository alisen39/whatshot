from __future__ import annotations

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


def _post(uuid: str, username: str, slug: str) -> dict:
    return {
        "id": uuid,
        "friendlyId": slug,
        "isTailwind": False,
        "theme": "dark",
        "type": "card",
        "version": 1,
        "user": {"username": username, "subscription": None},
    }


def test_parse_elements_preserves_upstream_rank_order() -> None:
    payload = {
        "posts": [
            _post("u1", "ElSombrero2", "tricky-robin-67"),
            _post("u2", "Praashoo7", "smooth-crab-52"),
        ],
        "postsCount": 4478,
    }
    rows = uiverse._parse_elements(payload, "favorites")

    assert [row.id for row in rows] == [
        "ElSombrero2/tricky-robin-67",
        "Praashoo7/smooth-crab-52",
    ]
    assert rows[0].title == "Tricky robin 67"
    assert rows[0].author == "ElSombrero2"
    assert rows[0].url == "https://uiverse.io/ElSombrero2/tricky-robin-67"
    assert rows[0].mobileUrl == rows[0].url
    # View/favorite counts are no longer part of the SSR data payload.
    assert rows[0].hot is None
    assert rows[0].desc is None


def test_parse_elements_dedupes_and_caps_at_max_items() -> None:
    posts = [_post(f"u{i}", f"user{i}", f"element-{i}") for i in range(60)]
    posts.append(posts[0])
    rows = uiverse._parse_elements({"posts": posts}, "views")

    assert len(rows) == uiverse._MAX_ITEMS
    assert len({row.id for row in rows}) == uiverse._MAX_ITEMS


def test_parse_elements_rejects_mostly_incomplete_posts() -> None:
    payload = {
        "posts": [
            {"id": "u1", "friendlyId": "no-user-1"},
            {"id": "u2", "user": {"username": "lonely"}},
            _post("u3", "ok-author", "good-post-3"),
        ],
    }
    with pytest.raises(RuntimeError, match="too few usable posts"):
        uiverse._parse_elements(payload, "recent")


def test_parse_elements_accepts_one_placeholder_in_evidenced_page_shape() -> None:
    posts = [_post(f"u{i}", f"user{i}", f"element-{i}") for i in range(34)]
    posts.insert(13, {"id": "uiverse-design-3"})

    rows = uiverse._parse_elements({"posts": posts}, "recent")
    assert len(rows) == 34


@pytest.mark.parametrize(
    ("username", "slug"),
    [("bad/user", "valid-slug"), ("valid-user", "bad?slug")],
)
def test_parse_elements_rejects_unsafe_identity_segments(username: str, slug: str) -> None:
    with pytest.raises(RuntimeError, match="too few usable posts"):
        uiverse._parse_elements({"posts": [_post("u1", username, slug)]}, "recent")


@pytest.mark.parametrize(
    "payload",
    [
        "challenge-page-html",
        {"posts": []},
        {"posts": [{"id": "u1"}]},
        {"unexpected": True},
    ],
)
def test_parse_elements_rejects_incompatible_envelopes(payload) -> None:
    with pytest.raises(RuntimeError):
        uiverse._parse_elements(payload, "favorites")


@pytest.mark.asyncio
async def test_get_list_requests_single_fetch_data_endpoint(monkeypatch) -> None:
    observed: dict = {}

    async def fake_get(**kwargs):
        observed.update(kwargs)
        return RequestResult(
            False,
            "2026-09-14T00:00:00+00:00",
            {"posts": [_post("u1", "author-x", "stable-post-1")]},
        )

    monkeypatch.setattr(uiverse, "get", fake_get)
    result = await uiverse._get_list("favorites", no_cache=True)

    assert observed["url"] == "https://uiverse.io/elements"
    assert observed["params"] == {"orderBy": "favorites", "_data": "routes/$category"}
    assert observed["response_type"] == "json"
    assert observed["no_cache"] is True
    assert observed["cache_key"] == "uiverse:elements:favorites:page-1"
    assert [row.id for row in result["data"]] == ["author-x/stable-post-1"]

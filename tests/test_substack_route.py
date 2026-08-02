from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import substack
from whats_hot_api.utils.http_client import RequestResult


def _request(query: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/substack/technology",
        "query_string": query,
        "headers": [],
    })


def _publication(
    publication_id: int = 6349492,
    name: str = "SemiAnalysis",
    **overrides: object,
) -> dict:
    publication = {
        "id": publication_id,
        "name": name,
        "base_url": "https://newsletter.semianalysis.com",
        "subdomain": "semianalysis",
        "author_name": "Dylan Patel",
        "hero_text": "Semiconductors and business.\n Deep analysis.",
        "logo_url": "https://substackcdn.com/logo.png",
    }
    publication.update(overrides)
    return publication


def _payload(*items: dict, **category_overrides: object) -> dict:
    category = {
        "id": 4,
        "slug": "technology",
        "active": True,
        "deprecated": False,
    }
    category.update(category_overrides)
    return {
        "trackingParameters": {"tab_id": str(category["id"])},
        "items": [
            {"type": "postFeed", "items": [{"publication": _publication(1)}]},
            {
                "type": "categoryLeaderboard",
                "category": category,
                "items": list(items),
            },
        ],
    }


def test_substack_parser_uses_only_category_leaderboard_and_publication_ids() -> None:
    duplicate = {"publication": _publication(name="Duplicate")}
    fallback = {
        "user": {
            "primary_publication": _publication(
                1638029,
                "Level Up Newsletter",
                base_url="",
                subdomain="levelup",
            ),
        },
    }
    invalid = {"publication": _publication(0, "Invalid")}

    rows = substack._parse_leaderboard(
        _payload({"publication": _publication()}, duplicate, fallback, invalid),
        "technology",
    )

    assert [row.id for row in rows] == ["6349492", "1638029"]
    assert rows[0].title == "SemiAnalysis"
    assert rows[0].author == "Dylan Patel"
    assert rows[0].desc == "Semiconductors and business. Deep analysis."
    assert rows[0].cover == "https://substackcdn.com/logo.png"
    assert rows[1].url == "https://levelup.substack.com"


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("id", 999),
        ("slug", "science"),
        ("active", False),
        ("deprecated", True),
    ],
)
def test_substack_parser_rejects_wrong_or_inactive_category(
    override: str,
    value: object,
) -> None:
    payload = _payload(
        {"publication": _publication()},
        **{override: value},
    )
    assert substack._parse_leaderboard(payload, "technology") == []


def test_substack_parser_rejects_ambiguous_duplicate_modules() -> None:
    payload = _payload({"publication": _publication()})
    payload["items"].append(payload["items"][-1].copy())
    assert substack._parse_leaderboard(payload, "technology") == []


def test_substack_parser_rejects_mismatched_tracking_tab() -> None:
    payload = _payload({"publication": _publication()})
    payload["trackingParameters"]["tab_id"] = "62"
    assert substack._parse_leaderboard(payload, "technology") == []


@pytest.mark.asyncio
async def test_substack_route_fetches_selected_official_category(monkeypatch) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == (
            "https://substack.com/api/v1/search/explore/web"
            "?tab=134&type=category"
        )
        assert kwargs["cache_key"] == "substack:rising:science"
        return RequestResult(
            data=_payload(
                {"publication": _publication()},
                id=134,
                slug="science",
            ),
            from_cache=False,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(substack, "get", fake_get)
    result = await substack.handle_route(_request(b"type=science"), True)

    assert result.name == "substack"
    assert result.type == "科学上升榜"
    assert result.total == 1


@pytest.mark.asyncio
async def test_substack_route_falls_back_to_technology(monkeypatch) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        assert "tab=4&type=category" in kwargs["url"]
        return RequestResult(
            data=_payload({"publication": _publication()}),
            from_cache=True,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(substack, "get", fake_get)
    result = await substack.handle_route(_request(b"type=unknown"))
    assert result.type == "科技上升榜"

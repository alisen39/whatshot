from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import qoder
from whats_hot_api.utils.http_client import RequestResult


def _flight_script(*records: dict) -> str:
    payload = "\n".join(
        f"{index + 20:x}:{json.dumps(record)}"
        for index, record in enumerate(records)
    )
    frame = json.dumps([1, payload])
    return f"<html><script>self.__next_f.push({frame})</script></html>"


BLOG_HTML = _flight_script(
    {
        "title": 'Farewell to "Vibe Coding"',
        "desc": "<p>Team-level AI development.</p>",
        "img": "https://img.example/qoder.jpg",
        "category": "Case",
        "url": "qoder-case-amap",
        "published_at": "2026-07-16T09:28:03Z",
    },
    {
        "title": "Qoder Harness",
        "desc": "Task execution environment",
        "category": "Technology",
        "url": "qoder-harness",
        "published_at": "2026-05-19T09:19:11Z",
    },
)

CHANGELOG_HTML = _flight_script(
    {
        "id": 355006812,
        "title": "Command Execution and Hook Fixes",
        "body": "<p>Improved shell experience.</p>",
        "tag_name": "1.0.47",
        "published_at": "2026-07-16T10:12:30Z",
        "type": "cli",
    },
    {
        "id": 354847688,
        "title": "Improvements",
        "body": "<ul><li>Fixed an IDE issue.</li></ul>",
        "tag_name": "1.14.1",
        "published_at": "2026-07-16T03:21:02Z",
        "type": "ide",
    },
)


def _request(query: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/qoder/blog",
        "query_string": query,
        "headers": [],
    })


@pytest.mark.asyncio
async def test_qoder_fetches_official_blog(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://qoder.com/blog"
        assert kwargs["cache_key"] == "qoder:blog:latest:50"
        return RequestResult(False, "2026-07-17T00:00:00+00:00", BLOG_HTML)

    monkeypatch.setattr(qoder, "get", fake_get)
    route_data = await qoder.handle_route(_request())

    assert route_data.type == "官方博客"
    assert [item.id for item in route_data.data] == [
        "qoder-case-amap",
        "qoder-harness",
    ]
    assert route_data.data[0].author == "Case"
    assert route_data.data[0].desc == "Team-level AI development."
    assert route_data.data[0].cover == "https://img.example/qoder.jpg"
    assert route_data.data[0].timestamp == 1784194083000
    assert route_data.data[0].url == "https://qoder.com/blog/qoder-case-amap"


@pytest.mark.asyncio
async def test_qoder_fetches_official_changelog(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://qoder.com/en/changelog"
        assert kwargs["cache_key"] == "qoder:changelog:latest:50"
        return RequestResult(False, "2026-07-17T00:00:00+00:00", CHANGELOG_HTML)

    monkeypatch.setattr(qoder, "get", fake_get)
    route_data = await qoder.handle_route(_request(b"type=changelog"))

    assert route_data.type == "更新日志"
    assert [item.id for item in route_data.data] == ["355006812", "354847688"]
    assert route_data.data[0].author == "Qoder CLI"
    assert route_data.data[0].desc == "版本：1.0.47 · Improved shell experience."
    assert route_data.data[0].url == (
        "https://qoder.com/en/changelog?version=1.0.47"
    )


def test_qoder_blog_parser_rejects_invalid_rows_and_deduplicates_slugs():
    duplicate = {
        "title": "Duplicate",
        "url": "qoder-case-amap",
        "published_at": "2026-07-18T00:00:00Z",
    }
    invalid = {
        "title": "Invalid",
        "url": "../private",
        "published_at": "2026-07-18T00:00:00Z",
    }

    items = qoder._parse_blog(_flight_script(duplicate, invalid) + BLOG_HTML)

    assert [item.id for item in items].count("qoder-case-amap") == 1
    assert all(item.id != "../private" for item in items)


def test_qoder_changelog_parser_uses_stable_ids_not_version_labels():
    same_version_other_product = {
        "id": 999,
        "title": "Plugin Improvements",
        "body": "Fixes",
        "tag_name": "1.0.47",
        "published_at": "2026-07-17T00:00:00Z",
        "type": "jetbrains",
    }

    items = qoder._parse_changelog(
        _flight_script(same_version_other_product) + CHANGELOG_HTML
    )

    assert [item.id for item in items] == ["999", "355006812", "354847688"]
    assert items[0].author == "JetBrains Plugin"

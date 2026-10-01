from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import github_weekly_repos
from whats_hot_api.utils.http_client import RequestResult

UPDATE_TIME = "2026-10-01T00:00:00+00:00"

# fixtures 按 board_api 证据(captured_data/raw/releases_fe_weekly.atom、hn_issues.html)净化内联。
_RELEASES_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/" xml:lang="en-US">
  <id>tag:github.com,2008:https://github.com/ascoders/weekly/releases</id>
  <title>Release notes from weekly</title>
  <updated>2024-06-13T11:49:05Z</updated>
  <entry>
    <id>tag:github.com,2008:Repository/85541218/295</id>
    <updated>2024-06-13T11:50:44Z</updated>
    <link rel="alternate" type="text/html" href="https://github.com/ascoders/weekly/releases/tag/295"/>
    <title>完整实现神经网络: 实战演练</title>
    <content type="html">&lt;p&gt;&lt;a href=&quot;https://github.com/ascoders/weekly/blob/master/295.md&quot;&gt;点击阅读&lt;/a&gt;&lt;/p&gt;</content>
    <author><name>ascoders</name></author>
    <media:thumbnail height="30" width="30" url="https://avatars.githubusercontent.com/u/7970947?s=60&amp;v=4"/>
  </entry>
  <entry>
    <id>tag:github.com,2008:Repository/85541218/294</id>
    <updated>2024-04-15T01:07:58Z</updated>
    <link rel="alternate" type="text/html" href="https://github.com/ascoders/weekly/releases/tag/294"/>
    <title>反向传播: 揭秘神经网络的学习机制</title>
    <author><name>ascoders</name></author>
  </entry>
</feed>
"""


def _issues_page(nodes: list[dict]) -> str:
    embedded = {
        "payload": {
            "preloadedQueries": [
                {
                    "result": {
                        "data": {
                            "repository": {"search": {"edges": [{"node": node} for node in nodes]}}
                        }
                    }
                }
            ]
        }
    }
    return (
        "<html><body><script type=\"application/json\" data-target=\"react-app.embeddedData\">"
        + json.dumps(embedded, ensure_ascii=False)
        + "</script></body></html>"
    )


_ISSUE_NODES = [
    {
        "number": 355,
        "titleHtml": "Hacker News Weekly Top 10 @2026-09-21",
        "createdAt": "2026-09-21T04:41:35Z",
        "author": {"login": "headllines"},
    },
    {
        "number": 354,
        # titleHtml 可能带标签与实体
        "titleHtml": "Top 10 &amp; <b>notes</b>",
        "createdAt": "2026-09-14T03:00:00Z",
        "author": {"login": "headllines"},
    },
    # 缺 number 的脏行应被跳过
    {"titleHtml": "no number", "createdAt": "2026-09-01T00:00:00Z", "author": {"login": "x"}},
]


def _request(board: str | None = None) -> Request:
    query = f"type={board}" if board else ""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/github-weekly-repos",
            "query_string": query.encode(),
            "headers": [],
        }
    )


@pytest.mark.asyncio
async def test_default_board_is_fe_weekly_releases(monkeypatch):
    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, UPDATE_TIME, _RELEASES_ATOM)

    monkeypatch.setattr(github_weekly_repos, "get", fake_get)

    result = await github_weekly_repos.handle_route(_request(), no_cache=True)

    assert github_weekly_repos.DEFAULT_TYPE == "fe-weekly"
    assert captured["url"] == "https://github.com/ascoders/weekly/releases.atom"
    assert captured["response_type"] == "text"
    assert result.name == "github-weekly-repos"
    assert result.type == "前端精读周刊 · Releases"
    assert result.link == "https://github.com/ascoders/weekly/releases"
    assert result.total == 2
    item = result.data[0]
    assert item.id == "tag:github.com,2008:Repository/85541218/295"  # Atom entry id,不是名次
    assert item.title == "完整实现神经网络: 实战演练"
    assert item.url == "https://github.com/ascoders/weekly/releases/tag/295"
    assert item.author == "ascoders"
    assert item.cover == "https://avatars.githubusercontent.com/u/7970947?s=60&v=4"
    assert item.timestamp == 1718279444000  # entry updated → 毫秒


@pytest.mark.asyncio
async def test_non_atom_releases_page_is_an_error(monkeypatch):
    async def fake_get(**kwargs):
        # github.com 偶发拿到登录页 / 错误页 HTML
        return RequestResult(False, UPDATE_TIME, "<html><body>Sign in to GitHub</body></html>")

    monkeypatch.setattr(github_weekly_repos, "get", fake_get)

    with pytest.raises(RuntimeError, match="not an Atom document"):
        await github_weekly_repos.handle_route(_request("ios-weekly"), no_cache=True)


@pytest.mark.asyncio
async def test_issues_page_requests_first_page_and_maps_nodes(monkeypatch):
    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, UPDATE_TIME, _issues_page(_ISSUE_NODES))

    monkeypatch.setattr(github_weekly_repos, "get", fake_get)

    result = await github_weekly_repos.handle_route(_request("hackernews-weekly"), no_cache=True)

    assert captured["url"] == "https://github.com/headllines/hackernews-weekly/issues"
    assert captured["params"] == {"page": 1}  # 照原站取第 1 页 25 条
    assert result.type == "Headllines/hackernews Weekly Issues · Issues"
    assert result.link == "https://github.com/headllines/hackernews-weekly/issues"
    assert result.total == 2  # 缺 number 的脏行被跳过
    first = result.data[0]
    assert first.id == "355"  # Issue 编号
    assert first.title == "Hacker News Weekly Top 10 @2026-09-21"
    assert first.url == "https://github.com/headllines/hackernews-weekly/issues/355"
    assert first.author == "headllines"
    assert first.timestamp == 1789965695000  # createdAt ISO → 毫秒
    # titleHtml 去标签、反转义
    assert result.data[1].title == "Top 10 & notes"


@pytest.mark.asyncio
async def test_issues_page_without_embedded_json_is_an_error(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, UPDATE_TIME, "<html><body>loading…</body></html>")

    monkeypatch.setattr(github_weekly_repos, "get", fake_get)

    with pytest.raises(RuntimeError, match="react-app.embeddedData"):
        await github_weekly_repos.handle_route(_request("hackernews-weekly"), no_cache=True)


@pytest.mark.asyncio
async def test_issues_embedded_json_without_search_is_an_error(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, UPDATE_TIME, _issues_page([])[:0] or "<html><body>"
            "<script type=\"application/json\" data-target=\"react-app.embeddedData\">"
            + json.dumps({"payload": {"preloadedQueries": [{"result": {"data": {}}}]}})
            + "</script></body></html>")

    monkeypatch.setattr(github_weekly_repos, "get", fake_get)

    with pytest.raises(RuntimeError, match="repository.search"):
        await github_weekly_repos.handle_route(_request("hackernews-weekly"), no_cache=True)


@pytest.mark.asyncio
async def test_empty_release_list_is_an_error(monkeypatch):
    atom = _RELEASES_ATOM.replace(_RELEASES_ATOM[_RELEASES_ATOM.index("  <entry>"):], "</feed>")

    async def fake_get(**kwargs):
        return RequestResult(False, UPDATE_TIME, atom)

    monkeypatch.setattr(github_weekly_repos, "get", fake_get)

    with pytest.raises(RuntimeError, match="returned no items"):
        await github_weekly_repos.handle_route(_request("d2-daily"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board 'rust-weekly'"):
        await github_weekly_repos.handle_route(_request("rust-weekly"), no_cache=True)

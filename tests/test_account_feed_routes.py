"""substack-newsletters、personal-blogs：按作者的 RSS/Atom，作为快讯条目返回。"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.backfill import BackfillStrategy
from whats_hot_api.routes.newsflash import personal_blogs, substack_newsletters
from whats_hot_api.utils import feed
from whats_hot_api.utils.http_client import RequestResult

RSS = """<?xml version="1.0"?><rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<item><guid>https://www.interconnects.ai/p/older</guid><title>Older</title><link>https://www.interconnects.ai/p/older</link>
  <pubDate>Mon, 09 Nov 2026 12:00:00 GMT</pubDate><description><![CDATA[<p>Old <b>post</b>.</p>]]></description></item>
<item><guid>https://www.interconnects.ai/p/newer</guid><title>Newer</title><link>https://www.interconnects.ai/p/newer</link>
  <pubDate>Tue, 10 Nov 2026 12:00:00 GMT</pubDate><enclosure url="https://cdn.example.com/a.png" type="image/png"/></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>tag:blog.samaltman.com,2013:Post/123</id><title>Reflections</title>
  <link href="https://blog.samaltman.com/reflections"/><published>2026-11-01T08:00:00Z</published>
  <summary>Some thoughts.</summary></entry>
</feed>"""


def _request(query_string: bytes = b"") -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": query_string, "headers": []})


def _fake_get(body: str, captured: dict):
    async def handler(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-11-12T00:00:00+00:00", body)

    return handler


@pytest.mark.asyncio
async def test_substack_newsletter_is_a_type(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(feed, "get", _fake_get(RSS, captured))
    result = await substack_newsletters.handle_route(_request(b"type=interconnects"), no_cache=True)

    assert captured["url"] == "https://www.interconnects.ai/feed" and captured["no_cache"] is True
    assert captured["headers"]["Referer"] == "https://www.interconnects.ai/"
    assert (result.kind, result.name, result.title, result.type) == (
        "newsflash", "substack-newsletters", "Substack Newsletter", "Interconnects")
    newer, older = result.data
    assert newer.id == "https://www.interconnects.ai/p/newer"  # guid, as the hot-list snapshots stored it
    assert (newer.content, newer.images, newer.source) == ("Newer", ["https://cdn.example.com/a.png"], "Interconnects")
    assert (older.content, older.contentStatus) == ("Old post .", "summary")
    assert newer.timestamp > older.timestamp


@pytest.mark.asyncio
async def test_personal_blog_reads_atom_and_defaults_to_first_author(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(feed, "get", _fake_get(ATOM, captured))
    result = await personal_blogs.handle_route(_request(), no_cache=False)

    assert captured["url"] == "https://blog.samaltman.com/posts.atom"
    assert (result.name, result.type, result.total) == ("personal-blogs", "Sam Altman", 1)
    [post] = result.data
    assert post.id == "tag:blog.samaltman.com,2013:Post/123"
    assert (post.title, post.content, post.url) == ("Reflections", "Some thoughts.", "https://blog.samaltman.com/reflections")


def test_account_routes_declare_accounts_and_snapshot_backfill():
    assert list(substack_newsletters.ROUTE_META["params"]["type"]["type"]) == [
        "gary-marcus", "ahead-of-ai", "dwarkesh-patel", "one-useful-thing", "interconnects"]
    assert list(personal_blogs.ROUTE_META["params"]["type"]["type"]) == [
        "sam-altman", "dario-amodei", "karpathy", "lilian-weng", "simon-willison", "tomer-tunguz",
        "ruanyifeng", "daring-fireball", "latent-space"]
    for module in (substack_newsletters, personal_blogs):
        assert module.BACKFILL["*"].strategy is BackfillStrategy.SNAPSHOT

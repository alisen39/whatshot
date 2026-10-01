from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import _arxiv_common, arxiv_cs_cl
from whats_hot_api.utils.http_client import RequestResult


@pytest.fixture(autouse=True)
def _no_arxiv_spacing(monkeypatch):
    monkeypatch.setattr(_arxiv_common, "_MIN_SPACING_SECONDS", 0.0)


LISTING_SAMPLE = """
<html><body>
<h3>Showing new listings for Friday, 25 September 2026</h3>
<dl>
<dt>[<a href="/abs/2609.12345v1">1</a>]</dt>
<dd>
<div class='list-title mathjax'>Title: A Study of Titles</div>
<div class='list-authors'>(<a href="/a/1">Alice Chen</a>, <a href="/a/2">Bob Liu</a>)</div>
<p class='mathjax'>Abstract: We study things.</p>
</dd>
<dt>[<a href="/abs/2609.67890v2">2</a>]</dt>
<dd>
<div class='list-title mathjax'>Title: Cross-listed Paper</div>
<div class='list-authors'>(<a href="/a/3">Carol Wang</a>)</div>
<p class='mathjax'>Abstract: More things.</p>
</dd>
</dl>
Total of 2 entries
</body></html>
"""


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/arxiv-cs-cl",
        "query_string": b"type=cs-cl",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_announcement_listing_is_parsed(monkeypatch):
    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-10-01T00:00:00+00:00", LISTING_SAMPLE)

    monkeypatch.setattr(arxiv_cs_cl, "get", fake_get)
    result = await arxiv_cs_cl.handle_route(_request(), no_cache=True)

    assert captured["url"] == "https://arxiv.org/list/cs.CL/new"
    assert captured["params"] == {"skip": 0, "show": 2000}
    assert captured["response_type"] == "text"
    assert captured["no_cache"] is True
    assert captured["headers"]["User-Agent"].startswith("whats-hot-api/")
    assert result.name == "arxiv-cs-cl"
    assert result.type == "最新公告 · cs.CL"
    assert result.total == 2
    assert result.message == "Showing new listings for Friday, 25 September 2026"
    first = result.data[0]
    assert first.id == "2609.12345v1"
    assert first.title == "A Study of Titles"
    assert first.author == "Alice Chen"  # 只取第一作者,与既有路由一致
    assert first.desc == "Abstract: We study things."
    assert first.url == "https://arxiv.org/abs/2609.12345v1"
    assert first.timestamp is None  # 列表页不提供单篇时间


@pytest.mark.asyncio
async def test_entry_total_mismatch_is_an_error(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, "t", LISTING_SAMPLE.replace("Total of 2 entries", "Total of 3 entries"))

    monkeypatch.setattr(arxiv_cs_cl, "get", fake_get)
    with pytest.raises(RuntimeError, match="declares 3 entries but 2 were parsed"):
        await arxiv_cs_cl.handle_route(_request(), no_cache=True)


@pytest.mark.asyncio
async def test_empty_listing_is_an_error(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, "t", "<html><body><h3>Showing new listings for Friday, 25 September 2026</h3></body></html>")

    monkeypatch.setattr(arxiv_cs_cl, "get", fake_get)
    with pytest.raises(RuntimeError, match="did not contain any entries"):
        await arxiv_cs_cl.handle_route(_request(), no_cache=True)

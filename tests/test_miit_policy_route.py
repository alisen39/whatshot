from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import miit_policy
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_miit_policy_uses_only_primary_list_links(monkeypatch):
    fragment = """<div class="page-content"><ul><li class="cf">
      <a class="fl" href="/zwgk/zcjd/art/2026/art_abc123.html" title="政策解读">政策解读</a>
      <span class="fr"><font style="display:none">政策</font>2026-07-13</span>
      <dl><dd><a href="/zwgk/zcwj/art/2026/art_related.html" title="相关政策">相关政策</a></dd></dl>
    </li></ul></div>"""
    calls = []

    async def fake_get(**kwargs):  # noqa: ANN003
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("cookie required")
        if kwargs["url"] == miit_policy.SOURCE_LINK:
            assert kwargs["no_cache"] is True
            return RequestResult(False, "bootstrap", "<html></html>")
        assert kwargs["params"] == miit_policy.API_PARAMS
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {
            "success": True, "data": {"html": fragment}
        })

    monkeypatch.setattr(miit_policy, "get", fake_get)
    request = Request({
        "type": "http", "method": "GET", "path": "/miit-policy",
        "query_string": b"", "headers": [],
    })
    route_data = await miit_policy.handle_route(request)

    assert len(calls) == 3
    assert route_data.total == 1
    assert route_data.data[0].id == "abc123"
    assert route_data.data[0].title == "政策解读"
    assert route_data.data[0].url.endswith("/art_abc123.html")

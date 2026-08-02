from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import dockerhub
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/dockerhub",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_dockerhub_parses_suggested_image_cards(monkeypatch):
    html = """
    <div data-testid="product-card">
      <a data-testid="product-card-link" href="/_/nginx">nginx</a>
      <div data-testid="productBadge">Docker Official Image</div>
      <p class="MuiTypography-body2">Official build of Nginx.</p>
      <img src="https://example.com/nginx.png">
      <div aria-label="Updated less than a minute ago"></div>
      <div aria-label="1B+ pulls"></div>
      <div aria-label="10K+ stars"></div>
    </div>
    <div data-testid="product-card">
      <a data-testid="product-card-link"
         href="/hardened-images/catalog/dhi/python">Python</a>
      <p class="MuiTypography-body2">Hardened Python image.</p>
      <div aria-label="10M+ pulls"></div>
    </div>
    <div data-testid="product-card">
      <a data-testid="product-card-link"
         href="/r/redhat/granite-3-2b-instruct">redhat/granite-3-2b-instruct</a>
      <div data-testid="productBadge">Verified Publisher</div>
      <p class="MuiTypography-body2">Granite model image.</p>
      <div aria-label="7.4K pulls"></div>
      <div aria-label="5 stars"></div>
    </div>
    """

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://hub.docker.com/search?type=image"
        assert kwargs["response_type"] == "text"
        return RequestResult(False, "2026-07-17T00:00:00+00:00", html)

    monkeypatch.setattr(dockerhub, "get", fake_get)
    route_data = await dockerhub.handle_route(_request())

    assert route_data.type == "推荐镜像"
    assert route_data.total == 3

    official = route_data.data[0]
    assert official.id == "library/nginx"
    assert official.title == "nginx"
    assert official.author == "Docker Official Image"
    assert official.hot == 1_000_000_000
    assert official.cover == "https://example.com/nginx.png"
    assert official.url == "https://hub.docker.com/_/nginx"
    assert "10K+ stars" in official.desc

    hardened = route_data.data[1]
    assert hardened.id == "dhi/python"
    assert hardened.hot == 10_000_000
    assert hardened.url == "https://hub.docker.com/hardened-images/catalog/dhi/python"

    publisher = route_data.data[2]
    assert publisher.id == "redhat/granite-3-2b-instruct"
    assert publisher.hot == 7_400
    assert publisher.url == "https://hub.docker.com/r/redhat/granite-3-2b-instruct"

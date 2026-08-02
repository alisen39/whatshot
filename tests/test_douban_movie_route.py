from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import douban_movie
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_douban_hot_board_uses_official_recent_hot_api(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/recent_hot/movie")
        assert kwargs["no_cache"] is True
        return RequestResult(
            False,
            "2026-07-30T00:00:00+00:00",
            {"items": [{"id": "1292052", "title": "肖申克的救赎", "card_subtitle": "剧情 / 犯罪"}]},
        )

    monkeypatch.setattr(douban_movie, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/douban-movie", "query_string": b"type=hot", "headers": []}
    )
    route_data = await douban_movie.handle_route(request, no_cache=True)

    assert route_data.type == "热门电影"
    assert route_data.data[0].id == "1292052"
    assert route_data.data[0].mobileUrl.endswith("/1292052/")


@pytest.mark.asyncio
async def test_douban_top250_paginates_and_extracts_stable_ids(monkeypatch):
    html = """
    <div class="item">
      <div class="pic"><em>1</em><img src="https://example.com/cover.jpg"></div>
      <div class="hd"><a href="https://movie.douban.com/subject/1292052/"><span class="title">肖申克的救赎</span></a></div>
      <div class="bd"><p>导演: 弗兰克·德拉邦特</p><div class="star"><span class="rating_num">9.7</span><span>3000000人评价</span></div><p class="quote"><span class="inq">希望让人自由。</span></p></div>
    </div>
    """
    calls: list[str] = []

    async def fake_get(**kwargs):  # noqa: ANN003
        calls.append(kwargs["params"]["start"])
        return RequestResult(False, "2026-07-16T00:00:00+00:00", html)

    monkeypatch.setattr(douban_movie, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/douban-movie", "query_string": b"type=top250", "headers": []}
    )
    route_data = await douban_movie.handle_route(request)

    assert calls == ["0"]
    assert route_data.type == "Top 250"
    assert route_data.data[0].id == "1292052"
    assert route_data.data[0].title == "肖申克的救赎"
    assert route_data.data[0].hot == 3000000
    assert "评分：9.7" in route_data.data[0].desc


def test_douban_top250_parser_skips_non_subject_links():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup('<div class="item"><div class="hd"><a href="/top250"><span class="title">无效</span></a></div></div>', "html.parser")
    assert douban_movie._parse_top250_page(soup) == []

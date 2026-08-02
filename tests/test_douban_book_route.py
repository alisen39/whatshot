from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import douban_book
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/douban-book",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_douban_book_maps_current_chart_fields(monkeypatch):
    html = """
    <html><body>
      <div id="content"><h1>6月热门图书榜</h1></div>
      <li class="media clearfix">
        <div class="media__img">
          <strong class="green-num-box">1</strong>
          <a href="https://book.douban.com/subject/38392174/">
            <img class="subject-cover" src="https://img.example/cover.jpg">
          </a>
        </div>
        <div class="media__body">
          <h2><a href="https://book.douban.com/subject/38392174/">抄写员巴托比</a></h2>
          <p class="subject-abstract">[美] 赫尔曼·梅尔维尔 / 2026-4-1 / 陕西师范大学出版总社 / 32.00元 / 平装</p>
          <p class="subject-rating">
            <span class="font-small">8.1</span>
            <span class="color-gray">(1657人评价)</span>
          </p>
          <div class="subject-tags">
            <span class="tag">小说</span>
            <span class="tag">连续上榜3个月</span>
          </div>
        </div>
      </li>
    </body></html>
    """

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://book.douban.com/chart"
        assert kwargs["response_type"] == "text"
        return RequestResult(False, "2026-07-17T00:00:00+00:00", html)

    monkeypatch.setattr(douban_book, "get", fake_get)
    route_data = await douban_book.handle_route(_request())
    item = route_data.data[0]

    assert route_data.type == "6月热门图书榜"
    assert item.id == "38392174"
    assert item.title == "抄写员巴托比"
    assert item.author == "[美] 赫尔曼·梅尔维尔"
    assert item.hot == 1657
    assert item.cover == "https://img.example/cover.jpg"
    assert item.desc == (
        "排名：1 · 评分：8.1 · "
        "[美] 赫尔曼·梅尔维尔 / 2026-4-1 / 陕西师范大学出版总社 / 32.00元 / 平装 · "
        "小说 / 连续上榜3个月"
    )
    assert item.url == "https://book.douban.com/subject/38392174/"
    assert item.mobileUrl == "https://m.douban.com/book/subject/38392174/"


def test_douban_book_rejects_rows_without_stable_subject_id():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        '<li class="media clearfix"><h2><a href="/chart">No ID</a></h2></li>',
        "html.parser",
    )

    assert douban_book._book_item(soup.li) is None

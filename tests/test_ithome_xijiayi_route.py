from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import ithome_xijiayi
from whats_hot_api.utils.http_client import RequestResult

FIXTURE_HTML = """
<ul class="newslist">
  <li>
    <div class="newspic"><a href="https://www.ithome.com/1/001/084.htm"><img data-original="https://img.ithome.com/newsuploadfiles/thumbnail/2026/9/1001084_240.jpg"></a></div>
    <div class="newsbody">
      <a href="https://www.ithome.com/1/001/084.htm"><h2>Steam 喜加一：新格式文章</h2></a>
      <p class="hidden-xs">新格式描述</p>
      <div class="newsbottom"><span class="time"><script>jsDateDiff('2026/9/11 8:07:50')</script></span><span class="comment">1236评论</span></div>
    </div>
  </li>
  <li>
    <div class="newspic"><a href="https://www.ithome.com/0/999/698.htm"><img data-original="https://img.ithome.com/old.jpg"></a></div>
    <div class="newsbody">
      <a href="https://www.ithome.com/0/999/698.htm"><h2>GOG 喜加一：旧格式文章</h2></a>
      <div class="newsbottom"><span class="comment">356评论</span></div>
    </div>
  </li>
</ul>
"""


def _request() -> Request:
    return Request(
        {"type": "http", "method": "GET", "path": "/ithome-xijiayi", "headers": []}
    )


@pytest.mark.asyncio
async def test_parses_seven_digit_and_legacy_article_urls(monkeypatch):
    async def fake_get(**kwargs):
        assert kwargs["url"] == "https://www.ithome.com/zt/xijiayi"
        assert kwargs["no_cache"] is True
        assert kwargs["response_type"] == "text"
        return RequestResult(False, "2026-09-11T00:00:00+00:00", FIXTURE_HTML)

    monkeypatch.setattr(ithome_xijiayi, "get", fake_get)
    route_data = await ithome_xijiayi.handle_route(_request(), no_cache=True)

    assert route_data.type == "最新动态"
    assert route_data.total == 2
    assert route_data.data[0].id == '1001084'
    assert route_data.data[0].mobileUrl == "https://m.ithome.com/html/1001084.htm"
    assert route_data.data[0].title == "Steam 喜加一：新格式文章"
    assert route_data.data[0].desc == "新格式描述"
    assert route_data.data[0].hot == 1236
    # Legacy /0/ URLs keep the pre-break int value of g1+g2.
    assert route_data.data[1].id == '999698'
    assert route_data.data[1].mobileUrl == "https://m.ithome.com/html/999698.htm"
    assert route_data.data[1].hot == 356


@pytest.mark.asyncio
async def test_non_article_href_is_skipped(monkeypatch):
    html = FIXTURE_HTML.replace(
        "https://www.ithome.com/1/001/084.htm", "https://www.ithome.com/zt/xijiayi"
    )

    async def fake_get(**kwargs):
        return RequestResult(False, "2026-09-11T00:00:00+00:00", html)

    monkeypatch.setattr(ithome_xijiayi, "get", fake_get)
    route_data = await ithome_xijiayi.handle_route(_request(), no_cache=True)

    assert route_data.total == 1
    assert route_data.data[0].id == "999698"


@pytest.mark.asyncio
async def test_page_with_only_non_article_links_is_rejected(monkeypatch):
    html = FIXTURE_HTML.replace(
        "https://www.ithome.com/1/001/084.htm", "https://www.ithome.com/zt/xijiayi"
    ).replace(
        "https://www.ithome.com/0/999/698.htm", "https://www.ithome.com/zt/xijiayi"
    )

    async def fake_get(**kwargs):
        return RequestResult(False, "2026-09-11T00:00:00+00:00", html)

    monkeypatch.setattr(ithome_xijiayi, "get", fake_get)
    with pytest.raises(RuntimeError, match="no valid article items"):
        await ithome_xijiayi.handle_route(_request(), no_cache=True)


@pytest.mark.asyncio
async def test_page_without_newslist_is_rejected(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, "2026-09-11T00:00:00+00:00", "<html><body>challenge</body></html>")

    monkeypatch.setattr(ithome_xijiayi, "get", fake_get)
    with pytest.raises(RuntimeError):
        await ithome_xijiayi.handle_route(_request(), no_cache=True)

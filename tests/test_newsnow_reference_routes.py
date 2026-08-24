from __future__ import annotations

import hashlib
import json
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import ghxi, linuxdo, steam, v2ex
from whats_hot_api.routes.newsflash import kr36_quick
from whats_hot_api.utils.http_client import RequestResult


def _request(**query: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": urlencode(query).encode(),
        "headers": [],
    })


@pytest.mark.asyncio
async def test_linuxdo_variants_use_distinct_feeds(monkeypatch):
    seen_url = ""
    rss = """<?xml version="1.0"?>
    <rss version="2.0"><channel><item>
      <title>Daily Linux.do topic</title>
      <link>https://linux.do/t/topic/42</link>
      <guid>topic-42</guid>
      <pubDate>Wed, 15 Jul 2026 10:00:00 +0000</pubDate>
    </item></channel></rss>
    """

    async def fake_get(**kwargs):  # noqa: ANN003
        nonlocal seen_url
        seen_url = kwargs["url"]
        return RequestResult(False, "linuxdo-update", rss)

    monkeypatch.setattr(linuxdo, "get", fake_get)

    route_data = await linuxdo.handle_route(_request(type="daily"))

    assert seen_url == "https://linux.do/top.rss?period=daily"
    assert route_data.type == "日榜"
    assert route_data.data[0].id == "topic-42"
    assert route_data.data[0].timestamp == 1784109600000


@pytest.mark.asyncio
async def test_v2ex_share_combines_deduplicates_and_sorts_feeds(monkeypatch):
    calls: list[str] = []

    async def fake_get(**kwargs):  # noqa: ANN003
        url = kwargs["url"]
        calls.append(url)
        feed_name = url.rsplit("/", 1)[-1].removesuffix(".json")
        items = [{
            "id": f"topic-{feed_name}",
            "title": f"{feed_name} topic",
            "url": f"https://www.v2ex.com/t/{feed_name}",
            "date_published": f"2026-07-{10 + len(calls):02d}T10:00:00Z",
        }]
        if feed_name == "share":
            items.append({
                "id": "topic-create",
                "title": "duplicate create topic",
                "url": "https://www.v2ex.com/t/create",
                "date_published": "2026-07-16T10:00:00Z",
            })
        return RequestResult(False, f"update-{feed_name}", {"items": items})

    monkeypatch.setattr(v2ex, "get", fake_get)

    route_data = await v2ex.handle_route(_request(type="share"))

    assert len(calls) == 4
    assert route_data.type == "分享主题"
    assert route_data.total == 4
    assert route_data.data[0].title == "share topic"
    assert len({item.id for item in route_data.data}) == 4


@pytest.mark.asyncio
async def test_ghxi_parses_software_updates(monkeypatch):
    html = """
    <div class="sec-panel"><div class="sec-panel-body"><ul class="post-loop">
      <li><div class="item-content">
        <h2 class="item-title"><a href="https://www.ghxi.com/tool.html">Tool 2.0</a></h2>
        <div class="item-excerpt">Useful desktop tool.</div>
        <span class="date">2小时前</span>
      </div></li>
    </ul></div></div>
    """

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(False, "ghxi-update", html)

    monkeypatch.setattr(ghxi, "get", fake_get)

    route_data = await ghxi.handle_route(_request())
    item = route_data.data[0]

    assert route_data.name == "ghxi"
    assert route_data.type == "软件更新"
    assert item.title == "Tool 2.0"
    assert item.desc == "Useful desktop tool."
    assert item.timestamp is not None


@pytest.mark.asyncio
async def test_steam_parses_current_and_peak_player_counts(monkeypatch):
    html = """
    <div id="detailStats"><table><tr class="player_count_row">
      <td><span class="currentServers">1,234,567</span></td>
      <td><span class="currentServers">1,500,000</span></td>
      <td><a class="gameLink" href="https://store.steampowered.com/app/730/Game/">Game</a></td>
    </tr></table></div>
    """

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(False, "steam-update", html)

    monkeypatch.setattr(steam, "get", fake_get)

    route_data = await steam.handle_route(_request())
    item = route_data.data[0]

    assert route_data.type == "在线人数榜"
    assert item.id == "730"
    assert item.hot == 1_234_567
    assert item.desc == "当前在线 1,234,567；今日峰值 1,500,000"


@pytest.mark.asyncio
async def test_36kr_quick_is_a_newsflash_route(monkeypatch):
    html = '<script>window.__GATEWAY_SIGN__="nonce-value"</script>'
    captured_get: dict = {}
    captured_post: dict = {}

    async def fake_get(**kwargs):
        captured_get.update(kwargs)
        return RequestResult(False, "36kr-update", html)

    async def fake_post(**kwargs):
        captured_post.update(kwargs)
        return RequestResult(
            False,
            "36kr-api-update",
            {
                "code": 0,
                "data": {
                    "itemList": [
                        {
                            "itemId": 123,
                            "itemType": 20,
                            "templateMaterial": {
                                "templateType": 0,
                                "widgetTitle": "Market update",
                                "widgetContent": "Full market update.（财联社）",
                                "widgetImage": "https://img.example/market.jpg",
                                "publishTime": 1787549277579,
                                "hasRed": 1,
                                "statComment": 2,
                                "sourceUrlRoute": (
                                    "webview?url=https%3A%2F%2Fexample.com%2Fmarket"
                                ),
                                "relevantProject": {"projectName": "Example Corp"},
                            },
                        }
                    ],
                },
            },
        )

    monkeypatch.setattr(kr36_quick, "get", fake_get)
    monkeypatch.setattr(kr36_quick, "post", fake_post)

    route_data = await kr36_quick.handle_route(_request(type="quick-stock"))
    item = route_data.data[0]
    signed_body = captured_post["body"]
    body = json.loads(signed_body)
    sign = parse_qs(urlsplit(captured_post["url"]).query)["sign"][0]

    assert route_data.kind == "newsflash"
    assert route_data.name == "36kr-quick"
    assert route_data.type == "股市快讯"
    assert route_data.fromCache is False
    assert route_data.updateTime == "36kr-api-update"
    assert item.title == "Market update"
    assert item.content == "Full market update.（财联社）"
    assert item.contentStatus == "full"
    assert item.source == "财联社"
    assert item.isImportant is True
    assert item.images == ["https://img.example/market.jpg"]
    assert item.symbols == [{"projectName": "Example Corp"}]
    assert item.metrics == {"commentCount": 2, "itemType": 20, "templateType": 0}
    assert item.timestamp == 1787549277579
    assert item.url == "https://example.com/market"
    assert item.mobileUrl == "https://www.36kr.com/newsflashes/123"
    assert body["nonce"] == "nonce-value"
    assert body["partner_id"] == "web"
    assert body["param"] == {
        "pageSize": 20,
        "pageEvent": 0,
        "pageCallback": "",
        "siteId": 1,
        "type": 2,
        "platformId": 2,
    }
    assert (
        sign
        == hashlib.md5(
            (signed_body + "nonce-value").encode(), usedforsecurity=False
        ).hexdigest()
    )
    assert captured_get["url"].endswith("/catalog/2")
    assert captured_post["headers"]["Referer"].endswith("/catalog/2")
    assert captured_post["cache_key"].endswith("?catalog=2")


def test_36kr_quick_declares_all_newsflash_catalogs():
    assert kr36_quick.TYPE_MAP == {
        "hot": "全部快讯",
        "quick": "全部快讯",
        "quick-hot": "热点快讯",
        "quick-stock": "股市快讯",
        "quick-company": "公司快讯",
        "quick-macro": "宏观快讯",
    }

"""design-community 路由测试（fixtures 依据 board_api design_community 证据净化内联）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import design_community as mod
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str | None) -> Request:
    query = f"type={board_type}".encode() if board_type else b""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/design-community",
            "query_string": query,
            "headers": [],
        }
    )


def _mock_get(body, *, capture: dict | None = None):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        if capture is not None:
            capture.update({"url": url, "headers": headers, "kwargs": kwargs})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", body)

    return fake_get


@pytest.mark.asyncio
async def test_uisdc_hot_posts_maps_views_and_date(monkeypatch):
    """优设热文榜单:"2.8w 阅读"->28000;日期按北京 0 点;封面取 .thumb 的 background-image。"""
    html = """
    <html><body><div class="p-items">
      <div class="p-item">
        <h2 class="item-title"><a href="https://www.uisdc.com/hot-one">热文一</a></h2>
        <p class="item-entry">摘要一</p>
        <span class="meta-author"><a href="/u/1">作者甲</a></span>
        <span class="meta-views">2.8w 阅读</span>
        <span class="meta-date">2026-09-15</span>
        <div class="item-thumb"><div class="thumb" style="background-image:url(https://image.uisdc.com/hot.png);"></div></div>
      </div>
      <div class="p-item">
        <h2 class="item-title"><a href="https://www.uisdc.com/hot-two">热文二</a></h2>
        <span class="meta-views">956 阅读</span>
      </div>
    </div></body></html>
    """
    monkeypatch.setattr(mod, "get", _mock_get(html))
    result = await mod.handle_route(_request("uisdc-hot-posts"), no_cache=True)

    assert result.type == "优设网 · 热文榜单"
    first, second = result.data
    assert first.id == "hot-one"
    assert first.hot == 28000  # "2.8w 阅读" -> 28000
    assert first.author == "作者甲"
    assert first.desc == "摘要一"
    assert first.cover == "https://image.uisdc.com/hot.png"  # background-image
    assert first.timestamp == int(datetime(2026, 9, 15, tzinfo=mod._BEIJING).timestamp() * 1000)
    assert second.hot == 956  # 无 w 后缀按原数
    assert second.timestamp is None and second.cover is None


@pytest.mark.asyncio
async def test_itsnicethat_props_edges(monkeypatch):
    """It's Nice That:props 的 data.page.items.edges[].node;slug 作 id;standfirst 去 HTML;
    publicationDate 转毫秒。props 缺失报错(页面改版,不静默降级)。"""
    node_html = "<p>standfirst <b>bold</b></p>"
    props = {
        "data": {
            "page": {
                "items": {
                    "edges": [
                        {"node": {"title": "Mestiza Estudio built this", "url": "/articles/mestiza-studio-canica-240926",
                                  "publicationDate": "2026-09-24T09:00:00+00:00", "standfirst": node_html,
                                  "listingImage": {"url": "https://www.itsnicethat.com/img.jpg"}}},
                        {"node": {"title": "无链接的不算", "url": ""}},
                    ]
                }
            }
        }
    }
    import json as jsonlib

    html = f'<html><head><script id="props" type="application/json">{jsonlib.dumps(props)}</script></head><body></body></html>'
    monkeypatch.setattr(mod, "get", _mock_get(html))
    result = await mod.handle_route(_request("itsnicethat-articles"), no_cache=True)

    assert result.type == "It's Nice That · Work"
    item = result.data[0]
    assert item.id == "mestiza-studio-canica-240926"  # url 最后一段 slug
    assert item.url == "https://www.itsnicethat.com/articles/mestiza-studio-canica-240926"
    assert item.desc == "standfirst bold"
    assert item.cover == "https://www.itsnicethat.com/img.jpg"
    assert item.timestamp == int(datetime(2026, 9, 24, 9, 0, tzinfo=UTC).timestamp() * 1000)

    async def fake_no_props(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html><body>改版了</body></html>")

    monkeypatch.setattr(mod, "get", fake_no_props)
    with pytest.raises(RuntimeError, match="no <script id=props>"):
        await mod.handle_route(_request("itsnicethat-articles"), no_cache=True)


@pytest.mark.asyncio
async def test_feed_boards_use_rss_and_browser_headers(monkeypatch):
    """Behance/designboom/数英 3 个 RSS 榜:浏览器 UA + feed Accept;保留 feed 原顺序。"""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        "<item><title>旧条目</title><link>https://www.behance.net/gallery/1/x</link><guid>https://www.behance.net/gallery/1/x</guid>"
        "<pubDate>Mon, 21 Sep 2026 08:00:00 GMT</pubDate></item>"
        "<item><title>新条目</title><link>https://www.behance.net/gallery/2/y</link>"
        "<pubDate>Tue, 22 Sep 2026 08:00:00 GMT</pubDate></item>"
        "</channel></rss>"
    )
    capture: dict = {}
    monkeypatch.setattr(mod, "get", _mock_get(xml, capture=capture))
    result = await mod.handle_route(_request("behance-featured"), no_cache=True)

    assert capture["url"] == "https://www.behance.net/feeds/projects"
    assert capture["headers"]["Accept"] == mod._ACCEPT_FEED
    assert capture["headers"]["User-Agent"].startswith("Mozilla/5.0")  # Behance 对程序 UA 403
    assert result.type == "Behance · Featured Projects"
    assert [item.title for item in result.data] == ["旧条目", "新条目"]  # feed 原顺序
    assert result.data[0].id == "https://www.behance.net/gallery/1/x"  # guid 作 id


@pytest.mark.asyncio
async def test_default_board_unknown_type_and_aliyun_waf(monkeypatch):
    """默认榜 = 声明序第一个 behance-featured;未知 type 拒绝;阿里云 WAF 挑战壳报错不绕。"""
    async def fake_waf(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", '<html><form name="aliyun_waf_aa">challenge</form></html>')

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        "<item><title>默认榜条目</title><link>https://www.behance.net/gallery/1/x</link></item>"
        "</channel></rss>"
    )
    monkeypatch.setattr(mod, "get", _mock_get(xml))
    result = await mod.handle_route(_request(None), no_cache=True)
    assert next(iter(mod.type_map)) == "behance-featured"  # 声明序第一个是默认榜
    assert result.type == "Behance · Featured Projects" and result.total == 1

    with pytest.raises(ValueError, match="Unknown board"):
        await mod.handle_route(_request("dribbble-popular"), no_cache=True)  # Dribbble 是不做的榜

    monkeypatch.setattr(mod, "get", fake_waf)
    with pytest.raises(RuntimeError, match="Aliyun WAF"):
        await mod.handle_route(_request("digitaling-latest"), no_cache=True)


def test_removed_zcool_and_uisdc_boards_are_gone():
    removed = {
        "uisdc-hunter-hot", "uisdc-latest", "zcool-all-recommend", "zcool-article-rank", "zcool-editor-picks",
        "zcool-film-editor-picks", "zcool-home-picks", "zcool-photo-editor-picks", "zcool-work-rank",
    }
    assert removed.isdisjoint(mod.type_map)
    assert list(mod.type_map) == [
        "behance-featured", "itsnicethat-articles", "designboom-latest", "digitaling-latest", "uisdc-hot-posts",
    ]

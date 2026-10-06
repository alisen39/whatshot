"""en-tech-review-feeds 路由测试（fixtures 依据 board_api en_tech_review_feeds 证据净化内联）。"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import en_tech_review_feeds as mod
from whats_hot_api.utils.http_client import RequestResult

_ET = ZoneInfo("America/New_York")


def _request(board_type: str | None) -> Request:
    query = f"type={board_type}".encode() if board_type else b""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/en-tech-review-feeds",
            "query_string": query,
            "headers": [],
        }
    )


def _rss_item(
    title: str,
    link: str,
    *,
    guid: str | None = "g-1",
    pub_date: str = "Tue, 22 Sep 2026 07:19:37 GMT",
    creator: str | None = "Ada",
    description: str = "<p>正文一</p>",
) -> str:
    parts = [f"<title>{title}</title>", f"<link>{link}</link>"]
    if guid:
        parts.append(f"<guid>{guid}</guid>")
    if pub_date:
        parts.append(f"<pubDate>{pub_date}</pubDate>")
    if creator:
        parts.append(f"<dc:creator>{creator}</dc:creator>")
    parts.append(f"<description><![CDATA[{description}]]></description>")
    return "<item>" + "".join(parts) + "</item>"


def _rss(items: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:media="http://search.yahoo.com/mrss/">'
        f"<channel><title>feed</title>{items}</channel></rss>"
    )


def _mock_get(body: str, *, capture: dict | None = None):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        if capture is not None:
            capture.update({"url": url, "headers": headers, "kwargs": kwargs})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", body)

    return fake_get


@pytest.mark.asyncio
async def test_feed_board_maps_fields_and_keeps_feed_order(monkeypatch):
    """RSS 字段映射 + feed 原顺序（不能按 timestamp 重排：Dark Reading 未来日期活动预告在 feed 末位）。"""
    capture: dict = {}
    # 第 1 条是 2020 年旧文，第 2 条是 2026 年新文：保留 feed 原顺序
    xml = _rss(
        _rss_item(
            "旧文",
            "https://www.darkreading.com/old",
            guid="id-old",
            pub_date="Sat, 22 Feb 2020 07:19:37 GMT",
            description="<p>旧文正文</p><img src='https://www.darkreading.com/a.png'/>",
        )
        + _rss_item("预告", "https://www.darkreading.com/event", guid="id-new", pub_date="Thu, 03 Dec 2026 09:00:00 GMT")
    )
    monkeypatch.setattr(mod, "get", _mock_get(xml, capture=capture))
    result = await mod.handle_route(_request("darkreading-latest"), no_cache=True)

    assert capture["url"] == "https://www.darkreading.com/rss.xml"
    assert capture["headers"]["Accept"] == mod._ACCEPT_FEED
    assert "User-Agent" not in capture["headers"]  # 其余站点对 UA 不敏感,不显式传
    assert capture["kwargs"].get("cache_key") == "en-tech-review-feeds:darkreading-latest"
    assert result.name == "en-tech-review-feeds"
    assert result.type == "Dark Reading · 全站最新"
    assert result.link == "https://www.darkreading.com/"
    assert result.total == 2
    first, second = result.data
    assert [item.id for item in result.data] == ["id-old", "id-new"]  # feed 原顺序,未按时间重排
    assert first.url == first.mobileUrl == "https://www.darkreading.com/old"
    assert first.author == "Ada"
    assert first.desc == "旧文正文"
    assert first.cover == "https://www.darkreading.com/a.png"  # 摘要里第一张图兜底
    expected_ms = int(datetime(2020, 2, 22, 7, 19, 37, tzinfo=UTC).timestamp() * 1000)
    assert first.timestamp == expected_ms  # pubDate -> 毫秒
    future_ms = int(datetime(2026, 12, 3, 9, 0, 0, tzinfo=UTC).timestamp() * 1000)
    assert second.timestamp == future_ms  # 未来日期照 feed 原样保留


@pytest.mark.asyncio
async def test_atom_feed_prefers_published_over_updated(monkeypatch):
    """CNET/ZDNET 的 Atom 按 updated 排序,timestamp 必须取首发 published,而不是 updated。"""
    capture: dict = {}
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
        "<title>CNET</title>"
        "<entry>"
        "<title>Atom 文章</title>"
        '<link href="https://www.cnet.com/tech/a-review/" />'
        "<id>123456</id>"
        "<published>2026-09-17T14:30:00Z</published>"
        "<updated>2026-09-28T08:00:00Z</updated>"
        "<summary>Atom 摘要</summary>"
        "</entry>"
        "</feed>"
    )
    monkeypatch.setattr(mod, "get", _mock_get(xml, capture=capture))
    result = await mod.handle_route(_request("cnet-latest"), no_cache=True)

    assert capture["url"] == "https://www.cnet.com/rss/all/"
    item = result.data[0]
    assert item.id == "123456"
    assert item.url == "https://www.cnet.com/tech/a-review/"
    expected_ms = int(datetime(2026, 9, 17, 14, 30, tzinfo=UTC).timestamp() * 1000)
    assert item.timestamp == expected_ms  # published(首发),不是 updated


@pytest.mark.asyncio
async def test_default_board_is_first_declared_type(monkeypatch):
    monkeypatch.setattr(mod, "get", _mock_get(_rss(_rss_item("默认榜", "https://www.cnet.com/x"))))
    result = await mod.handle_route(_request(None), no_cache=True)

    first_type = next(iter(mod.type_map))
    assert first_type == "cnet-latest"  # 声明序第一个是默认榜,与 board_api 缺省子榜一致
    assert result.type == mod.type_map[first_type]
    assert result.total == 1


@pytest.mark.asyncio
async def test_cnet_reviews_html_parse_and_dedup(monkeypatch):
    """CNET Reviews:头部 REVIEWS 区块 + LATEST REVIEWS 列表;同链接只留第一次的位置,
    封面/发布日从后面的卡片补齐;entry-archive 的日期只到日,按美东 0 点。"""
    html = """
    <html><body><main>
      <div class="c-ccb">
        <article class="list-entry"><h2><a href="/tech/list-title-one/">仅标题一</a></h2></article>
        <article class="grid-entry">
          <h3><a href="/tech/head-card/">头部卡片</a></h3>
          <time datetime="2026-09-18T12:00:00-04:00"></time>
          <img src="https://www.cnet.com/a/img/head.jpg" />
          <p class="grid-entry__excerpt">头部摘要</p>
        </article>
      </div>
      <div class="c-ccb">
        <h2 class="ccb-header__title">Tech</h2>
        <article class="grid-entry"><h3><a href="/tech/old-showcase/">分类展示旧文</a></h3></article>
      </div>
      <div class="zd-post-type-archive">
        <article class="entry-archive">
          <h2><a href="https://www.cnet.com/tech/head-card/">头部卡片</a></h2>
          <span class="entry-date">September 17, 2026</span>
        </article>
        <article class="entry-archive">
          <h2><a href="/tech/latest-two/">最新二</a></h2>
          <span class="entry-date">September 16, 2026</span>
        </article>
      </div>
    </main></body></html>
    """
    capture: dict = {}
    monkeypatch.setattr(mod, "get", _mock_get(html, capture=capture))
    result = await mod.handle_route(_request("cnet-reviews"), no_cache=True)

    assert capture["url"] == "https://www.cnet.com/reviews/"
    assert capture["headers"]["Accept"] == mod._ACCEPT_HTML
    assert [item.url for item in result.data] == [
        "https://www.cnet.com/tech/list-title-one/",
        "https://www.cnet.com/tech/head-card/",
        "https://www.cnet.com/tech/latest-two/",
    ]  # 分类展示区的旧文不取;同链接去重后保持第一次出现的位置
    head_card = result.data[1]
    assert head_card.title == "头部卡片"
    assert head_card.cover == "https://www.cnet.com/a/img/head.jpg"
    assert head_card.desc == "头部摘要"
    # 发布日(美东 0 点)从 entry-archive 补齐,替换精选卡的修改时间
    expected_ms = int(datetime(2026, 9, 17, tzinfo=_ET).timestamp() * 1000)
    assert head_card.timestamp == expected_ms
    title_only = result.data[0]
    assert title_only.cover is None and title_only.desc is None and title_only.timestamp is None  # 头部 4 条标题无日期无图
    latest_two = result.data[2]
    assert latest_two.timestamp == int(datetime(2026, 9, 16, tzinfo=_ET).timestamp() * 1000)
    assert result.type == "CNET · Reviews" and result.link == "https://www.cnet.com/reviews/"


@pytest.mark.asyncio
async def test_cnet_reviews_structure_change_raises(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html><main><p>改版了</p></main></html>")

    monkeypatch.setattr(mod, "get", fake_get)
    with pytest.raises(RuntimeError, match="CNET Reviews page structure changed"):
        await mod.handle_route(_request("cnet-reviews"), no_cache=True)


@pytest.mark.asyncio
async def test_restofworld_uses_program_ua(monkeypatch):
    """WordPress VIP 拒绝浏览器 UA:Rest of World 必须如实标明是程序。"""
    capture: dict = {}
    monkeypatch.setattr(mod, "get", _mock_get(_rss(_rss_item("RoW", "https://restofworld.org/2026/x/")), capture=capture))
    result = await mod.handle_route(_request("restofworld-latest"), no_cache=True)

    assert capture["headers"]["User-Agent"].startswith("python-httpx/")
    assert result.total == 1


def test_removed_spacenews_board_is_gone():
    assert "spacenews-ai" not in mod.type_map
    assert len(mod.type_map) == 25
    assert {feed.kind for feed in mod._FEEDS.values()} == {"feed", "cnet"}


@pytest.mark.asyncio
async def test_unknown_board_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await mod.handle_route(_request("pcmag-latest"), no_cache=True)  # PCMag 是不做的榜


@pytest.mark.asyncio
async def test_challenge_page_and_empty_feed_raise(monkeypatch):
    async def fake_vip_challenge(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<!DOCTYPE html><title>Checking your browser...</title><noscript>JS required</noscript>")

    async def fake_cf_challenge(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html><title>Just a moment...</title></html>")

    async def fake_empty(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", _rss(""))

    monkeypatch.setattr(mod, "get", fake_vip_challenge)
    with pytest.raises(RuntimeError, match="WordPress VIP browser-check"):
        await mod.handle_route(_request("restofworld-latest"), no_cache=True)

    monkeypatch.setattr(mod, "get", fake_cf_challenge)
    with pytest.raises(RuntimeError, match="Cloudflare challenge"):
        await mod.handle_route(_request("404media-latest"), no_cache=True)

    monkeypatch.setattr(mod, "get", fake_empty)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await mod.handle_route(_request("eetimes-latest"), no_cache=True)

"""en_science_misc_feeds 路由测试:fixtures 按证据目录 tmp/board_api/en_science_misc_feeds
净化(结构与字段与 evidence/*.response.body 一致,内容摘录改写,不含抓包原文)。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import en_science_misc_feeds as feeds
from whats_hot_api.utils.http_client import RequestResult

_UPDATE_TIME = "2026-09-28T00:00:00+00:00"


def _request(board_type: str | None = None) -> Request:
    query = f"type={board_type}".encode() if board_type else b""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/en-science-misc-feeds",
        "query_string": query,
        "headers": [],
    })


def _ok(data: Any) -> RequestResult:
    return RequestResult(False, _UPDATE_TIME, data)


def _mock(monkeypatch, responder) -> list[str]:
    """responder(url) -> body;返回捕获到的 URL 列表。"""
    calls: list[str] = []

    async def fake_get(**kwargs):
        url = kwargs["url"]
        calls.append(url)
        return _ok(responder(url))

    monkeypatch.setattr(feeds, "get", fake_get)
    return calls


# ---- FOX Sports 官方 RSS(结构与 evidence/03_foxsports_top 一致:media:content 套 media:thumbnail) ----

_FOX_RSS = """<rss xmlns:media="http://search.yahoo.com/mrss/" xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
<channel><title>Latest Sports News from FOX Sports</title><link>https://www.foxsports.com/stories</link>
<item><title><![CDATA[Jay Glazer: Giants Plan To Be Aggressive In QB Search]]></title>
<link>https://www.foxsports.com/stories/nfl/giants-qb-search</link>
<guid>https://www.foxsports.com/stories/nfl/giants-qb-search</guid>
<description><![CDATA[Insider Jay Glazer reported on the Giants' QB options.]]></description>
<pubDate>Sun, 27 Sep 2026 17:14:43 GMT</pubDate>
<media:content url="https://statics.foxsports.com/uploads/thumb-2.jpg" type="image/jpg">
<media:thumbnail url="https://a57.foxsports.com/uploads/128/72/thumb-2.jpg" width="128" height="72"/>
</media:content></item>
<item><title>Older story published earlier</title>
<link>https://www.foxsports.com/stories/nfl/older-story</link>
<guid>https://www.foxsports.com/stories/nfl/older-story</guid>
<description>Earlier news.</description>
<pubDate>Sat, 26 Sep 2026 10:00:00 GMT</pubDate></item>
</channel></rss>
"""


async def test_fox_top_feed_maps_fields_and_per_board_link(monkeypatch):
    calls = _mock(monkeypatch, lambda url: _FOX_RSS)
    result = await feeds.handle_route(_request("foxsports-top"), no_cache=True)

    # feed 地址照官方目录页原样(partnerKey 公开常量 + Top Headlines 的 aggregateId)
    assert calls == [
        (
            "https://api.foxsports.com/v2/content/optimized-rss?partnerKey=MB0Wehpmuj2lUhuRhQaafhBjAJqaPU244mlTDK1i"
            "&aggregateId=7f83e8ca-6701-5ea0-96ee-072636b67336"
        )
    ]
    assert result.name == "en-science-misc-feeds"
    assert result.type == "FOX Sports · Top Headlines"
    assert result.link == "https://www.foxsports.com/"  # 响应 link 是栏目页
    assert result.fromCache is False and result.updateTime == _UPDATE_TIME
    assert result.total == 2
    first = result.data[0]
    assert first.id == "https://www.foxsports.com/stories/nfl/giants-qb-search"  # guid
    assert first.title == "Jay Glazer: Giants Plan To Be Aggressive In QB Search"
    assert first.url == first.mobileUrl == first.id
    assert first.desc == "Insider Jay Glazer reported on the Giants' QB options."
    assert first.cover == "https://a57.foxsports.com/uploads/128/72/thumb-2.jpg"  # media:thumbnail
    assert first.author is None  # FOX feed 不带 dc:creator,hot 恒空
    assert first.hot is None
    assert first.timestamp == int(datetime(2026, 9, 27, 17, 14, 43, tzinfo=UTC).timestamp() * 1000)


async def test_fox_nba_board_builds_tags_feed_url(monkeypatch):
    calls = _mock(monkeypatch, lambda url: _FOX_RSS.replace("Latest Sports News", "Latest NBA News"))
    result = await feeds.handle_route(_request("foxsports-nba"), no_cache=True)

    assert calls[0].startswith(feeds.FOX_RSS + "&size=30&tags=fs/nba")
    assert result.type == "FOX Sports · NBA"


async def test_unknown_board_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown board 'nope'"):
        await feeds.handle_route(_request("nope"), no_cache=True)


async def test_empty_feed_is_an_error(monkeypatch):
    _mock(monkeypatch, lambda url: "<html>blocked</html>")
    with pytest.raises(RuntimeError, match="parsed no items"):
        await feeds.handle_route(_request("sciam-latest"), no_cache=True)


async def test_newscientist_omits_user_agent_and_uses_program_acceptance(monkeypatch):
    seen: dict[str, Any] = {}

    async def fake_get(**kwargs):
        seen.update(kwargs)
        return _ok(_FOX_RSS)

    monkeypatch.setattr(feeds, "get", fake_get)
    await feeds.handle_route(_request("newscientist-tech"), no_cache=True)

    assert seen["url"] == "https://www.newscientist.com/subject/technology/feed/"
    # New Scientist 拦冒充浏览器的请求(浏览器 UA 406 空响应),不发 User-Agent(httpx 缺省即程序 UA)
    assert "User-Agent" not in (seen.get("headers") or {})
    assert seen["headers"]["Accept"].startswith("application/rss+xml")


# ---- FOX Tennis 栏目页 __NUXT_DATA__(结构与 evidence/21 一致,内容摘录;含下标引用、-1 引用与 Date 包装) ----

def _nuxt_page(content_uri: str, results: list[dict[str, Any]]) -> str:
    # devalue 里带类型的值(如 Date)通过下标引用出现,不是内联数组
    typed_date_index = 10 + len(results)
    if len(results) > 2:
        results[2]["original_import_date"] = typed_date_index
    flat: list[Any] = [
        {"data": 1},
        {"league": 2},
        {"secondaryNavigationViewModel": 3},
        {"content": 4},
        {"apiEndpointResponseData": 5},
        {"contentUri": 6, "data": 7},
        content_uri,
        {"request": 8, "results": 9},
        {"params": '{"component_type":"news_article,video","from":"0","size":"25","uri":"' + content_uri + '"}'},
        [10 + index for index in range(len(results))],
        *results,
        ["Date", "2026-09-26T09:00:00Z"],
    ]
    return (
        "<html><head><script id=\"__NUXT_DATA__\" type=\"application/json\">"
        + json.dumps(flat)
        + "</script></head><body>cards</body></html>"
    )


_FOX_TENNIS_PAGE = _nuxt_page("tennis/atp/league/2", [
    {   # FOX 自己的稿:canonical_url 写成 foxsports.com/articles/…,页面链接补成 https://www.foxsports.com/…
        "id": "a1b2c3d1-0000-0000-0000-000000000001",
        "title": "ATP finals preview from FOX",
        "canonical_url": "foxsports.com/articles/tennis/atp-finals-preview",
        "dek": "<p>Fox preview for the season finale.</p>",
        "external_source": -1,  # devalue 负数引用 → None:卡片无外站来源,退署名
        "authors": [{"name": "FOX Sports Staff"}],
        "thumbnail": {"url": "https://a57.foxsports.com/uploads/tennis-1.jpg"},
        "last_published_date": "2026-09-27T18:35:17Z",
        "original_import_date": "2026-09-27T18:37:45Z",
    },
    {   # Newswhip 聚合的外站稿:canonical_url 是完整地址,author 显示外站来源
        "id": "a1b2c3d1-0000-0000-0000-000000000002",
        "title": "Zverev seals the Laver Cup title",
        "canonical_url": "https://www.si.com/tennis/zverev-laver-cup",
        "dek": "World No. 2 closed out the title.",
        "external_source": "si.com",
        "authors": [],
        "thumbnail": {"url": ""},
        "last_published_date": "2026-09-27T18:30:00.000Z",
        "original_import_date": "2026-09-27T18:37:45Z",
    },
    {   # 无 thumbnail / 无日期兜底字段:last_published_date 缺失时用 original_import_date;Date 包装的值
        "id": "a1b2c3d1-0000-0000-0000-000000000003",
        "title": "WTA wrap: three matches to watch",
        "canonical_url": "/articles/tennis/wta-wrap",
        "dek": None,
        "external_source": None,
        "authors": [],
        "last_published_date": None,
        "original_import_date": ["Date", "2026-09-26T09:00:00Z"],
    },
])


async def test_fox_tennis_page_parses_nuxt_results_in_page_order(monkeypatch):
    calls = _mock(monkeypatch, lambda url: _FOX_TENNIS_PAGE)
    result = await feeds.handle_route(_request("foxsports-tennis"), no_cache=True)

    assert calls == ["https://www.foxsports.com/tennis"]  # 301 → /tennis/atp 由共享 client 跟随
    assert result.type == "FOX Sports · Tennis"
    assert result.link == "https://www.foxsports.com/tennis/atp"
    assert result.total == 3
    first, second, third = result.data
    assert first.id == "a1b2c3d1-0000-0000-0000-000000000001"
    assert first.url == "https://www.foxsports.com/articles/tennis/atp-finals-preview"
    assert first.author == "FOX Sports Staff"  # external_source 为空退署名
    assert first.cover == "https://a57.foxsports.com/uploads/tennis-1.jpg"
    assert first.desc == "Fox preview for the season finale."  # dek 去 HTML
    assert first.timestamp == int(datetime(2026, 9, 27, 18, 35, 17, tzinfo=UTC).timestamp() * 1000)
    assert second.url == "https://www.si.com/tennis/zverev-laver-cup"  # 外站完整地址原样
    assert second.author == "si.com"
    assert second.cover is None
    assert second.timestamp == int(datetime(2026, 9, 27, 18, 30, 0, tzinfo=UTC).timestamp() * 1000)
    assert third.url == "https://www.foxsports.com/articles/tennis/wta-wrap"  # 相对 /articles/… 补全
    assert third.author is None
    assert third.desc is None
    assert third.timestamp == int(datetime(2026, 9, 26, 9, 0, 0, tzinfo=UTC).timestamp() * 1000)  # Date 包装 + 兜底字段


async def test_fox_page_guard_rejects_unexpected_list_uri(monkeypatch):
    # 页面列表的 uri 不是预期的 tennis/atp/league/2 → 栏目可能跳到了别的主题,直接报错
    _mock(monkeypatch, lambda url: _nuxt_page("olympics/winter/league/2", []))
    with pytest.raises(RuntimeError, match="expected tennis/atp/league/2"):
        await feeds.handle_route(_request("foxsports-tennis"), no_cache=True)


async def test_fox_page_without_nuxt_data_is_an_error(monkeypatch):
    _mock(monkeypatch, lambda url: "<html>no payload</html>")
    with pytest.raises(RuntimeError, match="__NUXT_DATA__"):
        await feeds.handle_route(_request("foxsports-olympics"), no_cache=True)


# ---- HBR Atom(evidence/18:ns6: 前缀、相对链接、thumbnail-image-uri;内容摘录) ----

_HBR_ATOM = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ns6:feed xmlns:ns6="http://www.w3.org/2005/Atom">
<ns6:title>HBR CMS</ns6:title>
<ns6:link href="http://hbr.org" rel="alternate" type="text/html"/>
<ns6:entry><ns6:title>Why Your Employees Override AI</ns6:title>
<ns6:id>tag:blogs.harvardbusiness.org,2007-03-31:999.434223</ns6:id>
<ns6:link href="/2026/09/why-your-employees-override-ai" rel="alternate" type="text/html"/>
<ns6:published>2026-09-25T12:15:11Z</ns6:published>
<ns6:summary><![CDATA[<p>These aren&#8217;t acts of resistance&#8212;they&#8217;re self-protection.</p>]]></ns6:summary>
<ns6:author><ns6:name>Adi Ignatius</ns6:name></ns6:author>
<ns6:thumbnail-image-uri>https://hbr.org/resources/images/2026/08/agenda-383x215.jpg</ns6:thumbnail-image-uri>
</ns6:entry>
<ns6:entry><ns6:title>Older entry kept in feed order</ns6:title>
<ns6:id>tag:blogs.harvardbusiness.org,2007-03-31:999.434100</ns6:id>
<ns6:link href="/2026/09/older-entry" rel="alternate" type="text/html"/>
<ns6:published>2026-09-20T10:00:00Z</ns6:published>
<ns6:summary>Plain summary</ns6:summary>
<ns6:author><ns6:name>First Author</ns6:name></ns6:author>
<ns6:author><ns6:name>Second Author</ns6:name></ns6:author>
</ns6:entry>
</ns6:feed>
"""


async def test_hbr_resolves_relative_links_and_keeps_feed_order(monkeypatch):
    calls = _mock(monkeypatch, lambda url: _HBR_ATOM)
    result = await feeds.handle_route(_request("hbr-latest"), no_cache=True)

    assert calls == ["http://feeds.hbr.org/harvardbusiness"]  # https 版 TLS 被断开,官方地址本身 http
    assert result.type == "Harvard Business Review · Latest"
    assert result.link == "https://hbr.org/"
    first, second = result.data
    assert first.id == "tag:blogs.harvardbusiness.org,2007-03-31:999.434223"
    assert first.url == "http://hbr.org/2026/09/why-your-employees-override-ai"  # 相对链接按 feed 声明补全
    assert first.author == "Adi Ignatius"
    assert first.cover == "https://hbr.org/resources/images/2026/08/agenda-383x215.jpg"
    assert first.desc == "These aren’t acts of resistance—they’re self-protection."
    assert first.timestamp == int(datetime(2026, 9, 25, 12, 15, 11, tzinfo=UTC).timestamp() * 1000)
    # 保留 feed 原顺序(第 2 条更旧,不按时间重排);多作者逗号连接;没有配图不填
    assert [item.title for item in result.data] == ["Why Your Employees Override AI", "Older entry kept in feed order"]
    assert second.author == "First Author, Second Author"
    assert second.cover is None


# ---- Apple 服务计划(evidence/10:section.as-container-column;内容摘录) ----

_APPLE_PAGE = """
<html><body>
<section class="as-container-column as-columns--2up-extended">
  <div class="column-item"><div class="as-richtext"><p class="as-center"><img
    src="/content/dam/edam/applecare/images/en_US/psp/mac-mini.png" alt="Mac mini"></p></div></div>
  <div class="column-item"><div class="as-richtext"><p><a href="/mac-mini-no-power-issue">
    <span class="icon icon-chevronright">Mac&nbsp;mini Service Program for No Power Issue</span></a><br>
    <span class="note">June 13, 2025 </span></p></div></div>
</section>
<section class="as-container-column as-columns--2up-extended">
  <div class="column-item"><div class="as-richtext"><p><a href="/watch-error-53">
    <span class="icon icon-chevronright">Apple&nbsp;Watch Error 53</span></a></p></div></div>
</section>
</body></html>
"""


async def test_apple_service_programs_parses_sections(monkeypatch):
    calls = _mock(monkeypatch, lambda url: _APPLE_PAGE)
    result = await feeds.handle_route(_request("apple-service-programs"), no_cache=True)

    assert calls == ["https://support.apple.com/service-programs"]
    assert result.type == "Apple 支持 · 服务计划（更换和维修扩展计划）"
    first, second = result.data
    assert first.id == "/mac-mini-no-power-issue"  # id 用计划页路径
    assert first.title == "Mac mini Service Program for No Power Issue"  # &nbsp; 归一成空格
    assert first.url == "https://support.apple.com/mac-mini-no-power-issue"
    assert first.cover == "https://support.apple.com/content/dam/edam/applecare/images/en_US/psp/mac-mini.png"
    # 页面只给日期,按当天 00:00 UTC → 毫秒
    assert first.timestamp == int(datetime(2025, 6, 13, tzinfo=UTC).timestamp() * 1000)
    assert second.timestamp is None  # 没有日期的条目留空
    assert second.cover is None


# ---- 国家地理(evidence/14、15:window['__natgeo__'];内容摘录) ----

def _natgeo_cursor(ms: int) -> str:
    import base64

    head = base64.b64encode(f"DYNA_0#ID:DRN|SORT:originalPublishedDate|{ms}".encode()).decode()
    return f"{head}.0.0"


_NATGEO_POTD = """
<html><body><img src="/content/dam/hero.jpg">
<script>window['__natgeo__'] = __STATE__;</script>
</body></html>
""".replace("__STATE__", json.dumps({
    "page": {"content": {"mediaspotlight": {"frms": [
        {"mods": [{"edgs": [
            {"media": [{
                "slug": "tomato-pickers-los-banos",
                "locator": "/photo-of-the-day/media-spotlight/tomato-pickers-los-banos",
                "img": {"src": "https://i.natgeofe.com/n/aaa/8T2A9108.JPG", "crdt": "Karla Gachet"},
                "caption": {"title": "September 25, 2026 | Before the Sun Rises",
                            "text": "Tomato pickers begin work early."},
                "cursor": _natgeo_cursor(1790334000000),
            }]},
            {"media": [{  # 没有 cursor:日期从图注标题取
                "slug": "spinning-mill",
                "locator": "/photo-of-the-day/media-spotlight/spinning-mill",
                "img": {"rt": "https://i.natgeofe.com/n/bbb/mill.jpg"},
                "caption": {"title": "September 24, 2026 | The Spinning Mill"},
                "cursor": "not-decodable",
            }]},
            {"media": [{"locator": "/photo-of-the-day/media-spotlight/no-title"}]},  # 无标题跳过
        ]}]},
    ]}}},
}))


async def test_natgeo_photo_of_the_day_parses_gallery(monkeypatch):
    calls = _mock(monkeypatch, lambda url: _NATGEO_POTD)
    result = await feeds.handle_route(_request("natgeo-photo-of-the-day"), no_cache=True)

    assert calls == ["https://www.nationalgeographic.com/photo-of-the-day"]
    assert result.type == "National Geographic · Photo of the Day"
    first, second = result.data
    assert first.id == "tomato-pickers-los-banos"  # 图片 slug
    assert first.title == "September 25, 2026 | Before the Sun Rises"  # 与 tophub 同形
    assert first.url == "https://www.nationalgeographic.com/photo-of-the-day/media-spotlight/tomato-pickers-los-banos"
    assert first.author == "Karla Gachet"  # 摄影师署名
    assert first.cover == "https://i.natgeofe.com/n/aaa/8T2A9108.JPG"
    assert first.desc == "Tomato pickers begin work early."
    assert first.timestamp == 1790334000000  # cursor 里的 originalPublishedDate(毫秒)
    assert second.cover == "https://i.natgeofe.com/n/bbb/mill.jpg"  # img 无 src 退 rt
    # cursor 解不出 → 从图注标题的日期取(2026-09-24 00:00 UTC)
    assert second.timestamp == int(datetime(2026, 9, 24, tzinfo=UTC).timestamp() * 1000)
    assert result.total == 2


_NATGEO_LATEST = """
<html><body><script>window['__natgeo__'] = __STATE__;</script></body></html>
""".replace("__STATE__", json.dumps({
    "page": {"content": {"hub": {"frms": [
        {"mods": [{"tiles": [  # PromoGridModule
            {"storyId": "drn:src:natgeo:unison::prod:aa11", "title": "Where to Eat on the Streets of Cairo",
             "ctas": [{"url": "https://www.nationalgeographic.com/travel/article/cairo-street-food"}],
             "img": {"src": "https://i.natgeofe.com/n/ccc/egypt.jpg"},
             "description": "A walking tour of the capital."},
            {"storyId": "drn:src:natgeo:unison::prod:bb22", "title": "Hanoi Breakfast Trail",
             "ctas": [{"url": "https://www.nationalgeographic.com/travel/article/hanoi-breakfast"}],
             "img": {}, "abstract": "Noodle soup before sunrise."},
        ]}]},
        {"mods": [{"tiles": [  # InfiniteFeedModule:重复 url 去重
            {"storyId": "drn:src:natgeo:unison::prod:aa11", "title": "Duplicate tile",
             "ctas": [{"url": "https://www.nationalgeographic.com/travel/article/cairo-street-food"}]},
            {"storyId": "drn:src:natgeo:unison::prod:cc33", "title": "No CTA tile", "ctas": []},
        ]}]},
    ]}}},
}))


async def test_natgeo_latest_tiles_have_no_timestamp_and_dedupe(monkeypatch):
    _mock(monkeypatch, lambda url: _NATGEO_LATEST)
    result = await feeds.handle_route(_request("natgeo-latest"), no_cache=True)

    assert result.type == "National Geographic · Latest Stories"
    assert result.link == "https://www.nationalgeographic.com/pages/topic/latest-stories"
    # 4 个 tile 里:重复 url 去重 1、无 CTA 跳过 1 → 2 条,按页面顺序不重排
    assert result.total == 2
    assert [item.id for item in result.data] == [
        "drn:src:natgeo:unison::prod:aa11",
        "drn:src:natgeo:unison::prod:bb22",
    ]
    first = result.data[0]
    assert first.url == "https://www.nationalgeographic.com/travel/article/cairo-street-food"  # ctas[0].url
    assert first.cover == "https://i.natgeofe.com/n/ccc/egypt.jpg"
    assert first.desc == "A walking tour of the capital."
    assert first.timestamp is None  # tile 没有日期字段,timestamp 留空
    assert result.data[1].desc == "Noodle soup before sunrise."  # 无 description 退 abstract

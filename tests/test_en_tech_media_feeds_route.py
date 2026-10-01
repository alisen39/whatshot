"""en-tech-media-feeds 路由测试：fixtures 为按 board_api 证据结构净化的合成样本（不含抓包原文）。"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import en_tech_media_feeds
from whats_hot_api.utils.http_client import RequestResult

_UA = en_tech_media_feeds._BROWSER_UA
_UPDATE_TIME = "2026-10-01T00:00:00+00:00"


def _request(board_type: str | None) -> Request:
    query = f"type={board_type}".encode() if board_type else b""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/en-tech-media-feeds",
            "query_string": query,
            "headers": [],
        }
    )


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _rss(items: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:media="http://search.yahoo.com/mrss/" '
        'xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        "<channel><title>Tech - Ars Technica</title>"
        f"{items}</channel></rss>"
    )


def _rss_item(
    title: str,
    url: str,
    *,
    author: str = "Samuel Axon",
    pub_date: str = "Fri, 25 Sep 2026 10:00:00 +0000",
    thumbnail: str | None = None,
    content: str = "",
) -> str:
    thumb = f'<media:thumbnail url="{thumbnail}" />' if thumbnail else ""
    return (
        "<item>"
        f"<title>{title}</title>"
        f"<link>{url}</link>"
        f"<guid isPermaLink=\"true\">{url}</guid>"
        f"<dc:creator><![CDATA[{author}]]></dc:creator>"
        f"<pubDate>{pub_date}</pubDate>"
        f"{thumb}"
        f"<content:encoded><![CDATA[{content}]]></content:encoded>"
        "</item>"
    )


def _atom(items: str, feed_title: str = "Science") -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">'
        f"<title>{feed_title} | The Verge</title>"
        f"{items}</feed>"
    )


def _atom_item(
    title: str,
    href: str,
    entry_id: str,
    *,
    published: str = "2026-09-24T14:04:44-04:00",
    author: str = "Justine Calma",
    thumbnail: str | None = None,
) -> str:
    thumb = f'<media:thumbnail url="{thumbnail}" />' if thumbnail else ""
    return (
        "<entry>"
        f"<author><name>{author}</name></author>"
        f'<title type="html"><![CDATA[{title}]]></title>'
        f'<link rel="alternate" type="text/html" href="{href}" />'
        f"<id>{entry_id}</id>"
        f"<updated>{published}</updated>"
        f"<published>{published}</published>{thumb}"
        "</entry>"
    )


def _register_page(main_cards: str) -> str:
    # 页脚的 "About Us" 等也是 article，但不在 section#main 里，不得混进结果
    return (
        "<html><body>"
        f'<section class="main front" id="main">{main_cards}</section>'
        '<footer><article><a href="https://www.theregister.com/about/">About Us</a>'
        "<h2 class=\"headline\">About headline</h2></article></footer>"
        "</body></html>"
    )


def _register_card(
    *,
    href: str,
    short: str | None,
    headline: str | None,
    subtitle: str | None = None,
    datetime_attr: str | None = None,
    img_src: str | None = None,
) -> str:
    short_attr = f' data-k5a-url="{short}"' if short else ""
    headline_html = f'<h2 class="headline">{headline}</h2>' if headline else ""
    subtitle_html = f"<p class=\"subtitle\">{subtitle}</p>" if subtitle else ""
    stamp_html = f'<time datetime="{datetime_attr}" itemprop="datePublished">27 Sep 2026</time>' if datetime_attr else ""
    img_html = f'<img src="{img_src}" alt="cover">' if img_src else ""
    return (
        f'<article data-instance="1"><a itemprop="url" href="{href}"{short_attr}>'
        f'<div class="media"><picture>{img_html}</picture></div></a>'
        f"{headline_html}{subtitle_html}{stamp_html}</article>"
    )


async def _fake_get(monkeypatch, responses: list[RequestResult | Exception], captured: dict):
    calls = {"n": 0}

    async def fake_get(url, headers=None, no_cache=None, response_type=None, cache_key=None, **kwargs):
        captured["url"] = url
        captured["headers"] = headers
        captured["cache_key"] = cache_key
        index = calls["n"]
        calls["n"] += 1
        outcome = responses[min(index, len(responses) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(en_tech_media_feeds, "get", fake_get)
    return calls


def _status_error(url: str, status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", url)
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"Client error '{status}'", request=request, response=response)


@pytest.mark.asyncio
async def test_feed_board_maps_fields(monkeypatch):
    captured: dict = {}
    xml = _rss(
        _rss_item(
            "Review: a phone",
            "https://arstechnica.com/gadgets/2026/09/review-a-phone/",
            thumbnail="https://cdn.arstechnica.net/a.jpg",
            content="<p>Better thermals.</p>",
            pub_date="Fri, 25 Sep 2026 10:00:00 +0000",
        )
        + _rss_item(
            "Older story",
            "https://arstechnica.com/gadgets/2026/09/older-story/",
            author="Another Author",
            pub_date="Thu, 24 Sep 2026 09:00:00 +0000",
        )
    )
    await _fake_get(monkeypatch, [RequestResult(False, _UPDATE_TIME, xml)], captured)

    result = await en_tech_media_feeds.handle_route(_request("ars-tech"), no_cache=True)

    assert captured["url"] == "https://arstechnica.com/gadgets/feed/"
    # board_api 全部子榜统一带项目缺省 Chrome UA；Accept 按 feed / 栏目页区分
    assert captured["headers"] == {
        "User-Agent": _UA,
        "Accept": en_tech_media_feeds._FEED_ACCEPT,
    }
    assert captured["cache_key"] == "en-tech-media-feeds:ars-tech"
    assert result.name == "en-tech-media-feeds"
    assert result.title == "Ars Technica"
    assert result.type == "Ars Technica · Tech"
    assert result.link == "https://arstechnica.com/gadgets/"
    assert result.fromCache is False
    assert result.updateTime == _UPDATE_TIME
    assert result.total == 2
    first = result.data[0]
    assert first.id == "https://arstechnica.com/gadgets/2026/09/review-a-phone/"  # guid（本 feed 是链接本身）
    assert first.title == "Review: a phone"
    assert first.url == "https://arstechnica.com/gadgets/2026/09/review-a-phone/"
    assert first.mobileUrl == first.url
    assert first.author == "Samuel Axon"
    assert first.cover == "https://cdn.arstechnica.net/a.jpg"
    assert first.desc == "Better thermals."
    assert first.hot is None  # feed 不提供热度
    assert first.timestamp == _ms(datetime(2026, 9, 25, 10, 0, 0, tzinfo=UTC))  # pubDate -> 毫秒
    assert result.data[1].author == "Another Author"


@pytest.mark.asyncio
async def test_default_board_is_first_declared_type_and_all_boards_declared(monkeypatch):
    captured: dict = {}
    await _fake_get(
        monkeypatch,
        [RequestResult(False, _UPDATE_TIME, _rss(_rss_item("默认榜", "https://arstechnica.com/gadgets/2026/09/x/")))],
        captured,
    )

    result = await en_tech_media_feeds.handle_route(_request(None), no_cache=False)

    first_key = next(iter(en_tech_media_feeds.type_map))
    assert first_key == "ars-tech"  # 声明序第一个是默认榜（与 board_api DEFAULT_TYPE 一致）
    assert captured["url"] == "https://arstechnica.com/gadgets/feed/"
    assert result.type == "Ars Technica · Tech"
    assert result.total == 1
    assert len(en_tech_media_feeds.type_map) == 23  # 23 个已完成榜全部声明
    assert len(set(en_tech_media_feeds.type_map.values())) == 23  # 标签互不相同


@pytest.mark.asyncio
async def test_atom_board_maps_fields(monkeypatch):
    captured: dict = {}
    xml = _atom(
        _atom_item(
            "Grid talks",
            "https://www.theverge.com/science/1000140/grid-talks",
            "https://www.theverge.com/?p=1000140",
            thumbnail="https://cdn.theverge.com/cover.jpg",
        )
    )
    await _fake_get(monkeypatch, [RequestResult(False, _UPDATE_TIME, xml)], captured)

    result = await en_tech_media_feeds.handle_route(_request("verge-science"), no_cache=True)

    assert captured["url"] == "https://www.theverge.com/rss/science/index.xml"
    assert captured["cache_key"] == "en-tech-media-feeds:verge-science"
    assert result.type == "The Verge · Science"
    assert result.link == "https://www.theverge.com/science"
    item = result.data[0]
    assert item.id == "https://www.theverge.com/?p=1000140"  # Atom 的 id（?p= 文章号）
    assert item.title == "Grid talks"
    assert item.url == "https://www.theverge.com/science/1000140/grid-talks"  # link@href
    assert item.author == "Justine Calma"  # author/name
    assert item.cover == "https://cdn.theverge.com/cover.jpg"
    assert item.timestamp == _ms(datetime(2026, 9, 24, 18, 4, 44, tzinfo=UTC))  # published（含时区）-> 毫秒


@pytest.mark.asyncio
async def test_unknown_board_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await en_tech_media_feeds.handle_route(_request("ars"), no_cache=True)  # ars 不是本路由的子榜键


@pytest.mark.asyncio
async def test_register_page_cards(monkeypatch):
    captured: dict = {}
    cards = (
        _register_card(
            href="https://www.theregister.com/columnists/2026/09/27/big_ai/5299007",
            short="https://www.theregister.com/a/5299007",
            headline="Big AI&#8217;s content problem",
            subtitle="Take the work keep the money",
            datetime_attr="2026-09-27T12:35:00+00:00",
            img_src="https://image.theregister.com/5299100.jpg",
        )
        + _register_card(
            href="https://www.theregister.com/2026/09/26/no_short_link/5299008",
            short=None,
            headline="No short link card",
        )
        + _register_card(href="https://www.theregister.com/2026/09/25/no_headline/5299009", short=None, headline=None)
    )
    await _fake_get(monkeypatch, [RequestResult(False, _UPDATE_TIME, _register_page(cards))], captured)

    result = await en_tech_media_feeds.handle_route(_request("register-ai-ml"), no_cache=True)

    assert captured["url"] == "https://www.theregister.com/ai_ml/"
    assert captured["headers"]["Accept"] == en_tech_media_feeds._HTML_ACCEPT  # 栏目页用 HTML Accept
    assert result.title == "The Register"
    assert result.type == "The Register · Software: AI + ML"
    assert result.link == "https://www.theregister.com/ai_ml/"
    assert result.total == 2  # 没有 headline 的卡片跳过；页脚 article 在主区外，不混入
    first = result.data[0]
    assert first.id == "https://www.theregister.com/a/5299007"  # data-k5a-url 短链，与旧 feed 的 id 同一形式
    assert first.title == "Big AI’s content problem"
    assert first.url == "https://www.theregister.com/columnists/2026/09/27/big_ai/5299007"
    assert first.desc == "Take the work keep the money"
    assert first.cover == "https://image.theregister.com/5299100.jpg"
    assert first.author is None  # 卡片上没有作者
    assert first.timestamp == _ms(datetime(2026, 9, 27, 12, 35, 0, tzinfo=UTC))  # time@datetime -> 毫秒
    second = result.data[1]
    assert second.id == second.url  # 没有 data-k5a-url 时用文章链接
    assert second.cover is None
    assert second.timestamp is None


@pytest.mark.asyncio
async def test_register_page_without_main_section_raises(monkeypatch):
    captured: dict = {}
    await _fake_get(monkeypatch, [RequestResult(False, _UPDATE_TIME, "<html><body><div>error page</div></body></html>")], captured)

    with pytest.raises(RuntimeError, match="parsed no items"):
        await en_tech_media_feeds.handle_route(_request("register-ai-ml"), no_cache=True)


@pytest.mark.asyncio
async def test_empty_feed_raises(monkeypatch):
    # feed 返回 200 但没有条目（结构变化 / 空壳）：严格报错，不降级为空榜
    captured: dict = {}
    await _fake_get(monkeypatch, [RequestResult(False, _UPDATE_TIME, _rss(""))], captured)

    with pytest.raises(RuntimeError, match="parsed no items"):
        await en_tech_media_feeds.handle_route(_request("ars-apple"), no_cache=True)


@pytest.mark.asyncio
async def test_venturebeat_429_challenge_retries_once(monkeypatch):
    # Vercel 机器人检测：429 挑战页等 5 秒重试 1 次，第二次成功（fake_sleep 截住真实等待）
    captured: dict = {}
    xml = _rss(_rss_item("VB story", "https://venturebeat.com/2026/09/vb-story/", author="Sean Szymkowski"))
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(en_tech_media_feeds.asyncio, "sleep", fake_sleep)
    calls = await _fake_get(
        monkeypatch,
        [_status_error("https://venturebeat.com/feed", 429), RequestResult(False, _UPDATE_TIME, xml)],
        captured,
    )

    result = await en_tech_media_feeds.handle_route(_request("venturebeat-latest"), no_cache=True)

    assert calls["n"] == 2  # 重试了 1 次
    assert sleeps == [5.0]  # 等 5 秒（board_api 同口径）
    assert captured["url"] == "https://venturebeat.com/feed"
    assert result.type == "VentureBeat · 全站最新"
    assert result.data[0].title == "VB story"


@pytest.mark.asyncio
async def test_venturebeat_429_twice_raises_and_other_boards_do_not_retry(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(en_tech_media_feeds.asyncio, "sleep", fake_sleep)
    captured: dict = {}
    calls = await _fake_get(
        monkeypatch,
        [_status_error("https://venturebeat.com/feed", 429)],
        captured,
    )
    with pytest.raises(httpx.HTTPStatusError):
        await en_tech_media_feeds.handle_route(_request("venturebeat-latest"), no_cache=True)
    assert calls["n"] == 2  # venturebeat：429 重试 1 次后仍 429，报错退出
    assert sleeps == [5.0]

    calls = await _fake_get(monkeypatch, [_status_error("https://arstechnica.com/apple/feed/", 429)], captured)
    with pytest.raises(httpx.HTTPStatusError):
        await en_tech_media_feeds.handle_route(_request("ars-apple"), no_cache=True)
    assert calls["n"] == 1  # 其余子榜不重试 429
    assert sleeps == [5.0]  # 没有新的等待

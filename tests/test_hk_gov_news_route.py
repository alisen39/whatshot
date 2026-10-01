from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import hk_gov_news
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/hk-gov-news",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _item_node(guid: str, title: str, link: str, pub_date: str, description: str) -> str:
    return (
        f"<item><guid>{guid}</guid><title>{title}</title><link>{link}</link>"
        f"<pubDate>{pub_date}</pubDate>"
        f'<enclosure url="{link.replace(".html", ".jpg")}" type="image/jpeg"/>'
        f"<description>{description}</description></item>"
    )


# pubDate(只到日)与链接稿件编号同天:取稿件编号的时分秒(香港时间)
RSS_SAMPLE = (
    "<?xml version=\"1.0\"?><rss><channel>"
    + _item_node(
        "2026093000123456789",
        "行政长官出席行政会议前见传媒",
        "https://sc.news.gov.hk/TuniS/www.news.gov.hk/chi/202609/20260930_093000_001.html",
        "Wed, 30 Sep 2026 00:00:00 GMT",
        "&lt;p&gt;摘要文字&lt;/p&gt;",
    )
    + "</channel></rss>"
)


@pytest.mark.asyncio
async def test_topstories_feed_maps_fields_and_hkt_timestamp(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured["url"] = url
        return RequestResult(False, "2026-10-01T00:00:00+00:00", RSS_SAMPLE)

    monkeypatch.setattr(hk_gov_news, "get", fake_get)
    result = await hk_gov_news.handle_route(_request("topstories"), no_cache=True)

    assert captured["url"] == "https://sc.news.gov.hk/TuniS/www.news.gov.hk/tc/common/html/topstories.rss.xml"
    assert result.name == "hk-gov-news"
    assert result.type == "重要新闻"
    assert result.link == "https://sc.news.gov.hk/TuniS/www.news.gov.hk/chi/index.html"
    assert result.total == 1
    item = result.data[0]
    assert item.id == "2026093000123456789"
    assert item.title == "行政长官出席行政会议前见传媒"
    assert "摘要文字" in (item.desc or "")
    assert item.cover == "https://sc.news.gov.hk/TuniS/www.news.gov.hk/chi/202609/20260930_093000_001.jpg"
    # 链接稿件编号 20260930_093000(香港时间 UTC+8)= 2026-09-30 01:30 UTC
    assert item.timestamp == 1790731800000  # 20260930_093000 香港时间


@pytest.mark.asyncio
async def test_cross_day_uses_pub_date_not_article_stamp(monkeypatch):
    # 特写类:稿件编号的日期与 pubDate 不同天(先写好、隔几天才上)→ 用 pubDate
    xml = (
        "<?xml version=\"1.0\"?><rss><channel>"
        + _item_node(
            "feature-1",
            "特写文章",
            "https://sc.news.gov.hk/TuniS/www.news.gov.hk/chi/202609/20260920_080000_001.html",
            "Wed, 30 Sep 2026 00:00:00 GMT",
            "正文",
        )
        + "</channel></rss>"
    )

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", xml)

    monkeypatch.setattr(hk_gov_news, "get", fake_get)
    result = await hk_gov_news.handle_route(_request("feature"), no_cache=True)

    # pubDate 2026-09-30 00:00 GMT → 香港时间 08:00
    assert result.data[0].timestamp == 1790726400000  # pubDate 2026-09-30 00:00 GMT(不取稿件编号的 09-20)


def test_item_timestamp_without_pub_date_uses_article_stamp():

    ms = hk_gov_news._item_timestamp(
        "https://sc.news.gov.hk/TuniS/www.news.gov.hk/chi/202609/20260929_235959_001.html",
        None,
    )
    expected = 1790697599000
    assert ms == expected


@pytest.mark.asyncio
async def test_empty_feed_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html>challenge page</html>")

    monkeypatch.setattr(hk_gov_news, "get", fake_get)
    with pytest.raises(RuntimeError, match="produced no items"):
        await hk_gov_news.handle_route(_request("ticker"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await hk_gov_news.handle_route(_request("nonsense"), no_cache=True)

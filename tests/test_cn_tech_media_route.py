"""cn-tech-media 路由测试：mock 共享 get，fixtures 从 board_api 证据净化。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import cn_tech_media as route
from whats_hot_api.utils.http_client import RequestResult

_CHINA_TZ = timezone(timedelta(hours=8))
_UPDATE_TIME = "2026-09-30T14:00:00+00:00"
# 页面生成时刻（模拟响应 Date 头）：2026-09-30 22:00:00 北京时间
_PAGE_NOW = datetime(2026, 9, 30, 22, 0, tzinfo=_CHINA_TZ)


def _request(board_type: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/cn-tech-media",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )


def _page_result(html: str, from_cache: bool = False) -> RequestResult:
    return RequestResult(
        from_cache,
        _UPDATE_TIME,
        {"data": html, "status": 200, "headers": {"date": "Wed, 30 Sep 2026 14:00:00 GMT", "Age": "0"}},
    )


IFANR_RSS = """<rss version="2.0"><channel><title>爱范儿</title>
<item><title>iQOO 16 体验：可能是今年最卷的「性能旗舰」</title>
<link>https://www.ifanr.com/1682609?utm_source=rss&amp;utm_medium=rss&amp;utm_campaign=</link>
<pubDate>Wed, 30 Sep 2026 10:30:18 +0000</pubDate>
<dc:creator>郑廷旭</dc:creator>
<description>&lt;p&gt;把日常当主场&lt;/p&gt;&lt;img src="https://s3.ifanr.com/wp-content/uploads/2026/09/cover.jpeg" /&gt;</description>
</item>
<item><title>微信新版内测</title><link>https://www.ifanr.com/news/1682600</link>
<pubDate>Wed, 30 Sep 2026 09:00:00 +0000</pubDate><dc:creator>爱范儿</dc:creator>
<description>微信推送新版本</description></item>
</channel></rss>"""

GEEKPARK_JSON = {
    "posts": [
        {
            "id": "371035",
            "title": "OPPO 姜昱辰：大模型的差距越来越小，AI 手机的差距才刚拉开",
            "abstract": "小布、ColorOS 17 与「AI 硬件」",
            "views": 27106,
            "cover_url": "https://imgslim.geekpark.net/uploads/image/file/49/77/497777880f3bedc8",
            "published_timestamp": 1790301025,
            "authors": [{"nickname": "张勇毅"}],
        }
    ]
}

QBITAI_HTML = """
<div class="article_list">
  <div class="picture_text">
    <div class="picture"><a href="https://www.qbitai.com/2026/09/499605.html"><img
      src="https://i.qbitai.com/wp-content/uploads/2026/09/abc.jpeg" /></a></div>
    <div class="text_box">
      <h4><a href="https://www.qbitai.com/2026/09/499605.html">直播回顾：工业AI的下一个机会在哪？</a></h4>
      <p><p>什么样的AI才适合工业现场？</p></p>
      <div class="info"><span class="author"><a href="/?author=47858">田晏林</a></span>
      <span class="time">1小时前 </span></div>
    </div>
  </div>
  <div class="picture_text">
    <div class="picture"><a href="https://www.qbitai.com/2026/09/499597.html"><img
      data-original="https://i.qbitai.com/wp-content/uploads/2026/09/def.webp" /></a></div>
    <div class="text_box">
      <h4><a href="https://www.qbitai.com/2026/09/499597.html">Anthropic，你是来给智谱打广告的吧！</a></h4>
      <div class="info"><span class="author"><a href="/?author=21">十三</a></span>
      <span class="time">09月28日 18:36</span></div>
    </div>
  </div>
</div>
"""

LEIPHONE_HTML = """
<div class="lph-pageList index-pageList"><div class="list"><ul class="clr">
<li><div class="box">
  <div class="img"><a href="https://www.leiphone.com/category/industrynews/7q7ZyMuKeWjc1uGz.html">
    <img class="lazy" data-original="https://static.leiphone.com/uploads/new/article/pic/202609/abc.jpeg"
      title="AI办公进入「上下文战争」，百度如何出牌？" /></a></div>
  <div class="word"><h3><a href="https://www.leiphone.com/category/industrynews/7q7ZyMuKeWjc1uGz.html"
    title="AI办公进入「上下文战争」，百度如何出牌？" class="headTit">AI办公进入「上下文战争」</a></h3>
    <div class="des">网盘文库十余年的家底，成为「库库AI」的上下文富矿。</div>
    <div class="msg clr"><a href="https://www.leiphone.com/author/zhangjiamin618" class="aut">张嘉敏</a>
      <div class="time">2小时前</div></div>
  </div>
</div></li>
<li><div class="box">
  <div class="img"><a href="https://www.leiphone.com/category/yanxishe/UUIfK7eeFE9Ws1JI.html">
    <img data-original="https://static.leiphone.com/uploads/new/article/pic/202609/def.jpg"
      title="DeepSeek 开源算子工具大礼包" /></a></div>
  <div class="word"><h3><a href="https://www.leiphone.com/category/yanxishe/UUIfK7eeFE9Ws1JI.html"
    class="headTit">DeepSeek 开源算子工具大礼包</a></h3>
    <div class="msg clr"><div class="time">2026-09-27</div></div>
  </div>
</div></li>
</ul></div></div>
"""


# ---------------------------------------------------------------- 爱范儿（RSS）


@pytest.mark.asyncio
async def test_ifanr_feed_strips_utm_and_maps_fields(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers})
        return RequestResult(False, _UPDATE_TIME, IFANR_RSS)

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("ifanr-latest"), no_cache=True)

    assert captured["url"] == "https://www.ifanr.com/feed"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "1682609"  # 链接里的文章 id
    assert first.url == "https://www.ifanr.com/1682609"  # utm 参数去掉
    assert first.mobileUrl == first.url
    assert first.author == "郑廷旭"  # dc:creator
    assert first.desc == "把日常当主场"
    assert first.cover == "https://s3.ifanr.com/wp-content/uploads/2026/09/cover.jpeg"  # 正文第一张图
    assert first.timestamp == int(datetime(2026, 9, 30, 10, 30, 18, tzinfo=UTC).timestamp()) * 1000
    assert result.data[1].id == "1682600"  # /news/<id> 形态也认


# ---------------------------------------------------------------- 极客公园


@pytest.mark.asyncio
async def test_geekpark_hot_week_maps_views_and_url(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "kwargs": kwargs})
        return RequestResult(False, _UPDATE_TIME, GEEKPARK_JSON)

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("geekpark-hot-week"), no_cache=True)

    assert captured["url"] == "https://mainssl.geekpark.net/api/v1/posts/hot_in_week?per=7"  # 组件请求
    assert captured["kwargs"]["response_type"] == "json"
    item = result.data[0]
    assert item.id == "371035"
    assert item.url == "https://www.geekpark.net/news/371035"  # 组件里的 /news/<id>
    assert item.hot == 27106  # views（列表按它倒序）
    assert item.author == "张勇毅"  # authors[0].nickname
    assert item.desc == "小布、ColorOS 17 与「AI 硬件」"  # abstract
    assert item.cover == "https://imgslim.geekpark.net/uploads/image/file/49/77/497777880f3bedc8"
    assert item.timestamp == 1790301025000  # published_timestamp 秒 → 毫秒


def test_relative_time_parses_qbitai_leiphone_display_formats():
    assert route.relative_time("刚刚", _PAGE_NOW) == int(_PAGE_NOW.timestamp())
    assert route.relative_time("30分钟前", _PAGE_NOW) == int((_PAGE_NOW - timedelta(minutes=30)).timestamp())
    assert route.relative_time("1小时前", _PAGE_NOW) == int((_PAGE_NOW - timedelta(hours=1)).timestamp())
    assert route.relative_time("昨天 18:56", _PAGE_NOW) == int(datetime(2026, 9, 29, 18, 56, tzinfo=_CHINA_TZ).timestamp())
    assert route.relative_time("前天 08:00", _PAGE_NOW) == int(datetime(2026, 9, 28, 8, 0, tzinfo=_CHINA_TZ).timestamp())
    assert route.relative_time("09月28日 18:36", _PAGE_NOW) == int(datetime(2026, 9, 28, 18, 36, tzinfo=_CHINA_TZ).timestamp())
    # 跨年：1 月看到「12月30日」要退一年
    january = datetime(2026, 1, 2, 10, 0, tzinfo=_CHINA_TZ)
    assert route.relative_time("12月30日", january) == int(datetime(2025, 12, 30, tzinfo=_CHINA_TZ).timestamp())
    # 只有日期取 0 点；认不出返回 None
    assert route.relative_time("2026-09-27", _PAGE_NOW) == int(datetime(2026, 9, 27, tzinfo=_CHINA_TZ).timestamp())
    assert route.relative_time("乱写的", _PAGE_NOW) is None


# ---------------------------------------------------------------- 量子位 / 雷锋网


@pytest.mark.asyncio
async def test_qbitai_home_parses_cards_with_page_time_base(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers, "kwargs": kwargs})
        return _page_result(QBITAI_HTML)

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("qbitai-latest"), no_cache=True)

    assert captured["url"] == "https://www.qbitai.com/"
    assert captured["kwargs"]["origin_info"] is True  # 相对时间需要响应 Date 头
    assert "Mozilla/5.0" in captured["headers"]["User-Agent"]  # 量子位拦程序 UA，必须浏览器 UA
    assert result.total == 2
    first = result.data[0]
    assert first.id == "499605"
    assert first.title == "直播回顾：工业AI的下一个机会在哪？"
    assert first.url == "https://www.qbitai.com/2026/09/499605.html"
    assert first.author == "田晏林"
    assert first.desc == "什么样的AI才适合工业现场？"
    assert first.cover == "https://i.qbitai.com/wp-content/uploads/2026/09/abc.jpeg"
    # 「1小时前」以页面生成时刻（响应 Date 头减 Age）为基准
    assert first.timestamp == int((_PAGE_NOW - timedelta(hours=1)).timestamp()) * 1000
    second = result.data[1]
    assert second.cover == "https://i.qbitai.com/wp-content/uploads/2026/09/def.webp"  # data-original
    assert second.timestamp == int(datetime(2026, 9, 28, 18, 36, tzinfo=_CHINA_TZ).timestamp()) * 1000


@pytest.mark.asyncio
async def test_leiphone_home_parses_headtit_and_skips_duplicates(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://www.leiphone.com/"
        return _page_result(LEIPHONE_HTML)

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("leiphone-latest"), no_cache=True)

    first = result.data[0]
    assert first.id == "7q7ZyMuKeWjc1uGz"  # 链接里的稳定标识（非名次）
    assert first.title == "AI办公进入「上下文战争」，百度如何出牌？"  # a[title] 优先
    assert first.author == "张嘉敏"
    assert first.desc == "网盘文库十余年的家底，成为「库库AI」的上下文富矿。"
    assert first.timestamp == int((_PAGE_NOW - timedelta(hours=2)).timestamp()) * 1000
    second = result.data[1]
    assert second.id == "UUIfK7eeFE9Ws1JI"
    assert second.timestamp == int(datetime(2026, 9, 27, tzinfo=_CHINA_TZ).timestamp()) * 1000  # 只有日期取 0 点


# ---------------------------------------------------------------- 错误路径


@pytest.mark.asyncio
async def test_unknown_board_and_broken_sources_rejected(monkeypatch):
    with pytest.raises(ValueError, match="Unknown board 'nope'"):
        await route.handle_route(_request("nope"), no_cache=True)

    async def fake_broken_json(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, {"error": "no posts"})

    monkeypatch.setattr(route, "get", fake_broken_json)
    with pytest.raises(RuntimeError, match="has no posts list"):
        await route.handle_route(_request("geekpark-hot-week"), no_cache=True)

    async def fake_broken_page(url, headers=None, params=None, no_cache=None, **kwargs):
        return _page_result("<div>改版后的页面</div>")

    monkeypatch.setattr(route, "get", fake_broken_page)
    with pytest.raises(RuntimeError, match="article_list"):
        await route.handle_route(_request("qbitai-latest"), no_cache=True)
    with pytest.raises(RuntimeError, match="lph-pageList"):
        await route.handle_route(_request("leiphone-latest"), no_cache=True)

from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.newsflash import wechat_qbit, zhidx
from whats_hot_api.utils import article_feed
from whats_hot_api.utils.http_client import RequestResult

LONG_TAIL = "尾段提到 GPT-6 Astra 正式发布。"
RSS_SAMPLE = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">
  <channel>
    <title>量子位</title>
    <link>https://wechat2rss.xlab.app/feed/7131b577c61365cb47e81000738c10d872685908.xml</link>
    <item>
      <title>早报：多家实验室更新模型</title>
      <link>https://mp.weixin.qq.com/s?__biz=MzIz&amp;mid=2247940029&amp;idx=2&amp;sn=abc&amp;scene=21</link>
      <pubDate>Fri, 06 Nov 2026 10:30:18 +0800</pubDate>
      <description><![CDATA[<p>摘要</p>]]></description>
      <content:encoded><![CDATA[
        <section><p>第一段<span>继续</span>。</p><script>track()</script>
        <p>{"很长的中段。" * 120}</p><p>{LONG_TAIL}</p></section>
      ]]></content:encoded>
    </item>
    <item>
      <title>另一篇</title>
      <link>https://mp.weixin.qq.com/s/opaqueId</link>
      <description><![CDATA[<p>只有简介</p>]]></description>
    </item>
    <item><title>没有链接</title></item>
  </channel>
</rss>
"""


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/wechat-qbit", "query_string": b"", "headers": []})


@pytest.mark.asyncio
async def test_route_keeps_public_summary_and_private_full_text(monkeypatch):
    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(True, "2026-11-07T01:00:00+00:00", RSS_SAMPLE)

    monkeypatch.setattr(article_feed, "get", fake_get)
    result = await wechat_qbit.handle_route(_request())

    assert captured == {
        "url": "https://wechat2rss.xlab.app/feed/7131b577c61365cb47e81000738c10d872685908.xml",
        "no_cache": False,
        "ttl": 3600,
        "response_type": "text",
        "headers": {"User-Agent": "WhatsHot/1.0"},
    }
    assert (result.kind, result.name, result.title, result.total) == ("newsflash", "wechat-qbit", "量子位 · 公众号", 2)
    assert result.fromCache is True  # A cached feed is re-parsed, so the full text is still there.

    article = result.data[0]
    assert article.id == "wechat:MzIz:2247940029:2"
    assert article.source == "量子位"
    assert article.timestamp == 1793932218000  # 10:30:18 +0800
    assert article.content.startswith("第一段继续。\n很长的中段。")
    assert len(article.content) == 500 and article.contentStatus == "summary"
    assert "track()" not in result._analysis_texts[article.id]
    assert result._analysis_texts[article.id].endswith(LONG_TAIL)

    assert result.data[1].id == "https://mp.weixin.qq.com/s/opaqueId"
    assert result._analysis_texts[result.data[1].id] == "只有简介"


def test_full_text_never_leaves_the_process():
    items, texts = article_feed.parse_feed(RSS_SAMPLE, "量子位")
    data = RouterData(kind="newsflash", **article_feed.route_meta("wechat-qbit"), type="公众号文章",
                      total=len(items), fromCache=False, updateTime="2026-11-07T01:00:00+00:00", data=items)
    data._analysis_texts = texts

    assert LONG_TAIL not in data.model_dump_json()
    assert "_analysis_texts" not in RouterData.model_json_schema()["properties"]
    assert data.model_copy(update={"title": "x"})._analysis_texts == texts
    assert RouterData.model_validate(data.model_dump())._analysis_texts == {}


def test_article_id_ignores_share_parameters():
    base = "https://mp.weixin.qq.com/s?__biz=MzIz&mid=1&idx=1&sn=a"
    assert article_feed.article_id(base) == article_feed.article_id(base + "&scene=21&chksm=b#rd")
    assert article_feed.article_id(base) != article_feed.article_id(base.replace("idx=1", "idx=2"))
    assert article_feed.article_id("https://mp.weixin.qq.com/s?__biz=MzIz&appmsgid=1&idx=1") == "wechat:MzIz:1:1"
    ifanr = "https://www.ifanr.com/1688251?utm_source=rss&utm_medium=rss&utm_campaign="
    assert article_feed.article_id(ifanr) == "https://www.ifanr.com/1688251"
    assert article_feed.article_id("https://example.com/?p=1&utm_source=rss") == "https://example.com/?p=1"


def test_non_rss_response_fails():
    with pytest.raises(RuntimeError, match="not a non-empty RSS feed"):
        article_feed.parse_feed("<html><body>403 Forbidden</body></html>", "量子位")


SITE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>智东西</title>
  <item>
    <title>前OpenAI CTO推新模型</title>
    <link>https://zhidx.com/p/123456.html</link>
    <pubDate>Fri, 06 Nov 2026 20:24:00 +0800</pubDate>
    <description><![CDATA[<p>导语。</p><p>正文第二段，模型细节。</p>]]></description>
  </item>
</channel></rss>
"""


@pytest.mark.asyncio
async def test_media_site_feed_reads_its_own_rss(monkeypatch):
    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, "2026-11-07T03:00:00+00:00", SITE_RSS)

    monkeypatch.setattr(article_feed, "get", fake_get)
    result = await zhidx.handle_route(_request(), no_cache=True)

    assert captured["url"] == "https://zhidx.com/rss" and captured["no_cache"] is True
    assert (result.name, result.title, result.type) == ("zhidx", "智东西 · 最新文章", "最新文章")
    [article] = result.data
    assert article.id == "https://zhidx.com/p/123456.html" and article.source == "智东西"
    assert result._analysis_texts[article.id] == "导语。\n正文第二段，模型细节。"

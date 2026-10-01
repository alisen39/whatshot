from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import fed_monetary
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/fed-monetary",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


# 结构取自 board_api/fed_monetary 证据 captured_data(净化):RSS 2.0,CDATA 包裹,
# 实体写作 &#39;,带 UTF-8 BOM;同日 18:00 同时发布的声明(…a.htm)与经济预测(…b.htm)
# pubDate 相同。故意把最旧的一条放在 feed 最前面,证明路由确实按时间倒序。
_FEED = (
    "\ufeff<?xml version=\"1.0\" encoding=\"utf-8\" ?>\n"
    "<rss version=\"2.0\">\n"
    "    <channel>\n"
    "        <title>FRB: Press Release - Monetary Policy</title>\n"
    "        <item>\n"
    "            <title>Minutes of the Board&#39;s discount rate meetings on July 20 and July 29, 2026</title>\n"
    "            <link><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20260825a.htm]]></link>\n"
    "            <guid><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20260825a.htm]]></guid>\n"
    "            <description><![CDATA[Minutes of the Board&#39;s discount rate meetings on July 20 and July 29, 2026]]></description>\n"
    "            <category>Monetary Policy</category>\n"
    "            <pubDate><![CDATA[Tue, 25 Aug 2026 18:00:00 GMT]]></pubDate>\n"
    "        </item>\n"
    "        <item>\n"
    "            <title>Federal Reserve issues FOMC statement</title>\n"
    "            <link><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm]]></link>\n"
    "            <guid><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm]]></guid>\n"
    "            <description><![CDATA[Federal Reserve issues FOMC statement]]></description>\n"
    "            <category>Monetary Policy</category>\n"
    "            <pubDate><![CDATA[Wed, 16 Sep 2026 18:00:00 GMT]]></pubDate>\n"
    "        </item>\n"
    "        <item>\n"
    "            <title>Federal Reserve Board and Federal Open Market Committee release economic projections</title>\n"
    "            <link><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916b.htm]]></link>\n"
    "            <guid><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916b.htm]]></guid>\n"
    "            <description><![CDATA[Federal Reserve Board and Federal Open Market Committee release economic projections]]></description>\n"
    "            <category>Monetary Policy</category>\n"
    "            <pubDate><![CDATA[Wed, 16 Sep 2026 18:00:00 GMT]]></pubDate>\n"
    "        </item>\n"
    "    </channel>\n"
    "</rss>\n"
)


@pytest.mark.asyncio
async def test_fetches_feed_and_maps_fields(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, response_type="json", **kwargs):
        captured.update({"url": url, "headers": headers, "no_cache": no_cache,
                         "response_type": response_type})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _FEED)

    monkeypatch.setattr(fed_monetary, "get", fake_get)
    result = await fed_monetary.handle_route(_request("hot"), no_cache=True)

    assert captured["url"] == "https://www.federalreserve.gov/feeds/press_monetary.xml"
    # feed 是 text/xml,必须按文本取回再解析
    assert captured["response_type"] == "text"
    assert captured["no_cache"] is True
    assert result.name == "fed-monetary"
    assert result.title == "美联储"
    assert result.type == "货币政策新闻稿"
    item = result.data[0]
    # id/url/mobileUrl 三者同为 guid(即链接)
    assert item.id == "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm"
    assert item.url == item.id
    assert item.mobileUrl == item.id
    assert item.title == "Federal Reserve issues FOMC statement"
    assert item.desc == item.title  # feed 的 description 与标题相同,照 whatshot 映射输出
    assert item.timestamp == 1789581600000  # pubDate 毫秒


@pytest.mark.asyncio
async def test_sorts_desc_and_keeps_tie_feed_order(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type="json", **kwargs):
        return RequestResult(False, "t", _FEED)

    monkeypatch.setattr(fed_monetary, "get", fake_get)
    result = await fed_monetary.handle_route(_request("hot"))
    urls = [item.url.rsplit("/", 1)[-1] for item in result.data]
    # 按发布时间倒序;同秒发布的 a/b 保持 feed 原顺序(a 在前,与原站一致)
    assert urls == [
        "monetary20260916a.htm",
        "monetary20260916b.htm",
        "monetary20260825a.htm",
    ]


@pytest.mark.asyncio
async def test_decodes_entities_in_cdata(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type="json", **kwargs):
        return RequestResult(False, "t", _FEED)

    monkeypatch.setattr(fed_monetary, "get", fake_get)
    result = await fed_monetary.handle_route(_request("hot"))
    minutes = result.data[-1]
    assert minutes.title == "Minutes of the Board's discount rate meetings on July 20 and July 29, 2026"
    assert minutes.desc == minutes.title  # &#39; 还原成 '


@pytest.mark.asyncio
async def test_empty_feed_is_an_error(monkeypatch):
    empty_feed = (
        "<?xml version=\"1.0\" encoding=\"utf-8\" ?>\n"
        "<rss version=\"2.0\"><channel><title>FRB: Press Release - Monetary Policy</title></channel></rss>\n"
    )

    async def fake_get(url, headers=None, no_cache=None, response_type="json", **kwargs):
        return RequestResult(False, "t", empty_feed)

    monkeypatch.setattr(fed_monetary, "get", fake_get)
    with pytest.raises(RuntimeError, match="produced no items"):
        await fed_monetary.handle_route(_request("hot"))


@pytest.mark.asyncio
async def test_unknown_type_is_rejected(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type="json", **kwargs):
        raise AssertionError("should not fetch for unknown type")

    monkeypatch.setattr(fed_monetary, "get", fake_get)
    with pytest.raises(ValueError, match="Unknown board"):
        await fed_monetary.handle_route(_request("minutes"))

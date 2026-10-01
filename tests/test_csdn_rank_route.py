from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import csdn_rank
from whats_hot_api.utils.http_client import RequestResult

# fixtures 依据 tmp/board_api/csdn_rank/evidence 的 captured_data 净化内联。
_HOT_RANK_ROW = {
    "productId": "166642710",
    "articleTitle": "不用 Spring，手写 AOP",
    "articleDetailUrl": "https://blog.csdn.net/Everest_cjq/article/details/166642710",
    "hotRankScore": "16491",
    "nickName": "Everest_cjq",
    "picList": ["https://i-blog.csdnimg.cn/direct/abc.png"],
    "period": None,
}
_AUTHOR_ROW = {
    "currentRank": "1",
    "hotRankScore": 19982,
    "nickName": "醍醐实验室",
    "articleId": "164059635",
    "articleTitle": "过程奖励模型实战",
    "articleDetailUrl": "https://blog.csdn.net/2201_75984884/article/details/164059635",
}
_CSDNNEWS_RSS = """<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>
<title>CSDN资讯</title><link>https://blog.csdn.net/csdnnews</link>
<item><title><![CDATA[CPU 重回 C 位]]></title>
<link>https://blog.csdn.net/csdnnews/article/details/166688978</link>
<guid>https://blog.csdn.net/csdnnews/article/details/166688978</guid>
<author>csdnnews</author>
<pubDate>Sat, 26 Sep 2026 13:17:48 +0800</pubDate>
<description><![CDATA[CPU 在推理与编排侧的相对权重上升。]]></description></item>
</channel></rss>"""
_HOME_EMBEDDED = [
    {"itemId": 166589719, "title": "荣耀落地行业首个系统级Agent Harness",
     "summary": "当智能体变成手机系统的基础能力", "cover": "https://i-blog.csdnimg.cn/direct/cover1.png",
     "nickname": "CSDN资讯"},
    {"itemId": 166571230, "title": "内嵌第二条", "summary": "摘要二", "cover": "", "nickname": "作者二"},
]
_HOME_HTML = f"""<html><body>
<div class="home-info">
  <div class="home-cont-title"><span>资讯头条</span></div>
  <div class="home-info-banner">
    <a href="https://blog.csdn.net/csdnnews/article/details/166589719">轮播一</a>
    <a>广告位没有 href</a>
  </div>
  <div class="home-info-headlines">
    <a href="https://blog.csdn.net/csdnnews/article/details/166571230">内嵌第二条</a>
  </div>
</div>
<script>window.__INITIAL_STATE__={json.dumps({"pageData": {"data": {"www-info-list-home": {"list": _HOME_EMBEDDED}}}})}</script>
</body></html>"""


def _request(board_type: str | None) -> Request:
    query = f"type={board_type}" if board_type is not None else ""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/csdn-rank",
        "query_string": query.encode(),
        "headers": [],
    })


@pytest.mark.asyncio
async def test_channel_board_maps_fields_and_query(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, response_type="json", **kwargs):
        captured.update({"url": url, "headers": headers, "no_cache": no_cache})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", {
            "code": 200,
            "data": [_HOT_RANK_ROW, {"productId": "", "articleTitle": "缺 id 照跳过"}],
        })

    monkeypatch.setattr(csdn_rank, "get", fake_get)
    result = await csdn_rank.handle_route(_request("java"), no_cache=True)

    # 页面缺省口径：page=0、pageSize=25、type 为空，child_channel 必需
    assert captured["url"] == (
        "https://blog.csdn.net/phoenix/web/blog/hot-rank?page=0&pageSize=25&child_channel=java&type="
    )
    assert captured["headers"]["Referer"].startswith("https://blog.csdn.net/rank/list/content")
    assert captured["no_cache"] is True
    assert result.type == "Java热榜"
    item = result.data[0]
    assert item.id == "166642710"
    assert item.title == "不用 Spring，手写 AOP"
    assert item.url == item.mobileUrl == _HOT_RANK_ROW["articleDetailUrl"]
    assert item.hot == 16491
    assert item.cover == "https://i-blog.csdnimg.cn/direct/abc.png"
    assert item.author == "Everest_cjq"
    # 接口没有发布时间（period 全 null），timestamp 留空
    assert item.timestamp is None
    assert result.total == 1


@pytest.mark.asyncio
async def test_default_board_is_ai(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type="json", **kwargs):
        assert "child_channel=%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD" in url
        return RequestResult(True, "t", {"code": 200, "data": [_HOT_RANK_ROW]})

    monkeypatch.setattr(csdn_rank, "get", fake_get)
    result = await csdn_rank.handle_route(_request(None))
    assert result.type == "人工智能热榜"
    assert result.fromCache is True


@pytest.mark.asyncio
async def test_new_author_board_uses_page_one(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, response_type="json", **kwargs):
        captured["url"] = url
        return RequestResult(False, "t", {"code": 200, "data": {"list": [_AUTHOR_ROW]}})

    monkeypatch.setattr(csdn_rank, "get", fake_get)
    result = await csdn_rank.handle_route(_request("new-author"))

    # 新晋作者榜页码从 1 开始（page=0 返回空 list）
    assert captured["url"] == (
        "https://blog.csdn.net/phoenix/web/v2/rank?page=1&pageSize=25&rankType=new_author"
    )
    assert result.type == "新晋作者热文榜"
    item = result.data[0]
    assert item.id == "164059635"
    assert item.hot == 19982
    assert item.author == "醍醐实验室"
    assert item.timestamp is None


@pytest.mark.asyncio
async def test_csdnnews_board_parses_rss(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type="text", **kwargs):
        assert url == "https://blog.csdn.net/csdnnews/rss/list"
        assert response_type == "text"
        return RequestResult(False, "t", _CSDNNEWS_RSS)

    monkeypatch.setattr(csdn_rank, "get", fake_get)
    result = await csdn_rank.handle_route(_request("csdnnews"))

    item = result.data[0]
    assert result.type == "CSDN资讯"
    assert item.id == "https://blog.csdn.net/csdnnews/article/details/166688978"
    assert item.title == "CPU 重回 C 位"
    assert item.author == "csdnnews"
    # RSS pubDate 归一化为毫秒
    assert item.timestamp == 1790399868000


@pytest.mark.asyncio
async def test_headlines_parses_home_block_in_order(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type="text", **kwargs):
        assert url == "https://www.csdn.net/"
        return RequestResult(False, "t", _HOME_HTML)

    monkeypatch.setattr(csdn_rank, "get", fake_get)
    result = await csdn_rank.handle_route(_request("headlines"))

    assert result.type == "今日头条热点"
    # 轮播在前、文字列表在后，按页面顺序；无 href 的广告格跳过
    assert [item.id for item in result.data] == ["166589719", "166571230"]
    first = result.data[0]
    assert first.title == "荣耀落地行业首个系统级Agent Harness"
    assert first.cover == "https://i-blog.csdnimg.cn/direct/cover1.png"
    assert first.author == "CSDN资讯"
    assert first.desc == "当智能体变成手机系统的基础能力"
    # editTime / timestamp 是编辑放进列表的时间，不是发布时间，留空
    assert first.timestamp is None


@pytest.mark.asyncio
async def test_headlines_missing_block_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type="text", **kwargs):
        return RequestResult(False, "t", "<html><body>改版后的首页</body></html>")

    monkeypatch.setattr(csdn_rank, "get", fake_get)
    with pytest.raises(RuntimeError, match="home-info"):
        await csdn_rank.handle_route(_request("headlines"))


@pytest.mark.asyncio
async def test_business_error_shell_raises(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type="json", **kwargs):
        return RequestResult(False, "t", {"code": 500, "message": "服务器开小差"})

    monkeypatch.setattr(csdn_rank, "get", fake_get)
    for board in ("java", "new-author"):
        with pytest.raises(RuntimeError, match="code=500"):
            await csdn_rank.handle_route(_request(board))


@pytest.mark.asyncio
async def test_empty_list_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type="json", **kwargs):
        return RequestResult(False, "t", {"code": 200, "data": []})

    monkeypatch.setattr(csdn_rank, "get", fake_get)
    with pytest.raises(RuntimeError, match="no items"):
        await csdn_rank.handle_route(_request("python"))


def test_unknown_board_is_rejected():
    request = _request("nosuch")
    with pytest.raises(ValueError, match="Unknown board"):
        import asyncio

        asyncio.run(csdn_rank.handle_route(request))

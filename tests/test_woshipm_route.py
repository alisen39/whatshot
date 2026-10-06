from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import woshipm
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/woshipm",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


# 分类页"最新"页签的服务端渲染结构(evidence/02_cat_* 的净化版)
_CATEGORY_PAGE = """<html><body>
<div class="category-card"><a href="https://www.woshipm.com/pd/6174294.html">推荐位旧文不算</a></div>
<template v-if="homeTab == 'latest'">
<article class="postlist-item" data-id="6471144">
  <div class="post-img"><img src="https://image.woshipm.com/2023/04/17/cover.png!/both/236x143"></div>
  <div class="content">
    <h2 class="post-title"><a href="https://www.woshipm.com/pd/6471144.html" title="AI赋能硬件">AI赋能硬件IPD开发的四个等级</a></h2>
    <div class="des">硬件出身的作者用一套 skills 体系跑通了全链路。</div>
    <div class="author"><a class="ui-captionStrong" href="https://www.woshipm.com/u/756715">产品人卫朋</a></div>
  </div>
</article>
<article class="postlist-item" data-id="6462566">
  <h2 class="post-title"><a href="https://www.woshipm.com/ucd/6462566.html">合作媒体转载(不在 RSS 里)</a></h2>
</article>
</template>
<template v-else>推荐页签不解析</template>
</body></html>"""

# 同分类 RSS(evidence/03_feed_* 的净化版):只有第一条在 feed 里
_CATEGORY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>AI赋能硬件IPD开发的四个等级</title>
<link>https://www.woshipm.com/pd/6471144.html</link>
<pubDate>Wed, 30 Sep 2026 13:41:43 +0800</pubDate></item>
</channel></rss>"""


@pytest.mark.asyncio
async def test_category_board_parses_items_and_supplements_feed_time(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_get(url, headers=None, no_cache=None, response_type=None, **kwargs):
        captured["url"] = url
        if url.endswith("/feed"):
            return RequestResult(False, "2026-10-01T00:00:00+00:00", _CATEGORY_FEED)
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _CATEGORY_PAGE)

    monkeypatch.setattr(woshipm, "get", fake_get)
    result = await woshipm.handle_route(_request("pd"), no_cache=True)

    assert captured["url"] == "https://www.woshipm.com/category/pd/feed"  # 两个请求:页面 + 同名 RSS
    assert result.type == "产品设计"
    assert result.total == 2  # category-card 推荐位不输出
    first = result.data[0]
    assert first.id == "6471144"  # article 的 data-id,不是名次
    assert first.title == "AI赋能硬件IPD开发的四个等级"
    assert first.url == "https://www.woshipm.com/pd/6471144.html"
    assert first.author == "产品人卫朋"
    assert first.desc == "硬件出身的作者用一套 skills 体系跑通了全链路。"
    assert first.timestamp == 1790746903000  # RSS pubDate(2026-09-30 13:41:43 +08:00)补的毫秒时间
    assert result.data[1].timestamp is None  # 合作媒体转载不在 RSS 里,留空


_LATEST_PAGE = """<html><body>
<template v-if="homeTab == 'latest'">这是首页"推荐"页签,不取</template>
<template v-if="homeTab == 'all'">
<article class="postlist-item" data-id="6472100">
  <h2 class="post-title"><a href="https://www.woshipm.com/ai/6472100.html">首页最新一条</a></h2>
</article>
</template>
</body></html>"""


@pytest.mark.asyncio
async def test_latest_board_reads_home_all_tab(monkeypatch):
    urls: list[str] = []

    async def fake_get(url, headers=None, no_cache=None, response_type=None, **kwargs):
        urls.append(url)
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _LATEST_PAGE)

    monkeypatch.setattr(woshipm, "get", fake_get)
    result = await woshipm.handle_route(_request("latest"), no_cache=True)

    assert urls == ["https://www.woshipm.com/", "https://www.woshipm.com/feed"]  # 首页 + 全站 RSS
    assert result.type == "最新"
    assert result.data[0].id == "6472100"


# 首页"热门"页签接口(evidence/04_popular_* 的净化版)
_POPULAR_PAYLOAD = {
    "RESULT": [
        {
            "controlTypeCode": 2001,
            "data": {
                "id": 6472100,
                "articleTitle": "豆包连夜&#8221;抄作业&#8221;，字节版Muse要来了？",
                "articleSummary": "",
                "articleAuthor": "怪哥",
                "imageUrl": "https://tu.aixq.cc/wp-content/uploads/2026/09/Muse-01.jpg",
                "publishTime": 1790684659000,
            },
            "scores": 502,
            "trueScores": 502,
        },
        {"controlTypeCode": 2001, "data": {"id": 6471893, "articleTitle": "产品经理转型FDE指南"},
         "scores": 88},
    ]
}


@pytest.mark.asyncio
async def test_popular_board_maps_scores_and_permalink(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_get(url, headers=None, no_cache=None, response_type=None, **kwargs):
        captured["url"] = url
        captured["response_type"] = response_type
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _POPULAR_PAYLOAD)

    monkeypatch.setattr(woshipm, "get", fake_get)
    result = await woshipm.handle_route(_request("daily"), no_cache=True)

    assert captured["url"] == "https://www.woshipm.com/api2/app/article/popular/daily"
    assert captured["response_type"] == "json"
    assert result.type == "日榜"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "6472100"
    assert first.title == "豆包连夜”抄作业”，字节版Muse要来了？"  # HTML 实体已解
    assert first.url == "https://www.woshipm.com/?p=6472100"  # 组件 permalink
    assert first.hot == 502  # scores 是榜单排序依据
    assert first.timestamp == 1790684659000  # publishTime 毫秒原样


@pytest.mark.asyncio
async def test_popular_error_shell_is_rejected(monkeypatch):
    # 上游返回 {"RESULT":{},"CODE":500,...}(yearly 这类不存在的类型),RESULT 不是列表
    async def fake_get(url, headers=None, no_cache=None, response_type=None, **kwargs):
        return RequestResult(False, "t", {"RESULT": {}, "CODE": 500, "MESSAGE": "服务器异常,稍后再试"})

    monkeypatch.setattr(woshipm, "get", fake_get)
    with pytest.raises(RuntimeError, match="no RESULT list"):
        await woshipm.handle_route(_request("daily"), no_cache=True)


@pytest.mark.asyncio
async def test_page_without_tab_block_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type=None, **kwargs):
        return RequestResult(False, "t", "<html><body>改版后的页面</body></html>")

    monkeypatch.setattr(woshipm, "get", fake_get)
    with pytest.raises(RuntimeError, match="no tab block"):
        await woshipm.handle_route(_request("it"), no_cache=True)


@pytest.mark.asyncio
async def test_empty_postlist_is_an_error(monkeypatch):
    empty = """<html><body><template v-if="homeTab == 'latest'">没有条目</template></body></html>"""

    async def fake_get(url, headers=None, no_cache=None, response_type=None, **kwargs):
        return RequestResult(False, "t", empty)

    monkeypatch.setattr(woshipm, "get", fake_get)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await woshipm.handle_route(_request("ucd"), no_cache=True)


@pytest.mark.asyncio
async def test_popular_with_only_malformed_rows_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type=None, **kwargs):
        return RequestResult(False, "t", {"RESULT": [{"data": {}}, {"scores": 1}]})

    monkeypatch.setattr(woshipm, "get", fake_get)
    with pytest.raises(RuntimeError, match="no valid rows"):
        await woshipm.handle_route(_request("weekly"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await woshipm.handle_route(_request("nonsense"), no_cache=True)

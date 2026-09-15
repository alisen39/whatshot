"""2026-09-15 production collisions, reproduced from sanitized upstream fields."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.routes.hotlist import baidu, eastmoney_market, openai_news
from whats_hot_api.routes.newsflash import fastbull
from whats_hot_api.utils.http_client import RequestResult

FIXTURES = Path(__file__).parent / "fixtures" / "board_identity"
UPDATED = "2026-09-15T14:20:00+00:00"


def request(board: str) -> Request:
    return Request({"type": "http", "query_string": f"type={board}".encode()})


@pytest.mark.parametrize("board", ["express", "news"])
async def test_fastbull_native_identity_and_main_content(monkeypatch, board):
    html = (FIXTURES / "fastbull.html").read_text()

    async def get(**kwargs):
        assert kwargs["url"] == "https://www.fastbull.com" + fastbull._PATHS[board]
        assert kwargs["no_cache"] is True
        assert kwargs["ttl"] == fastbull.config.NEWSFLASH_CACHE_TTL
        assert kwargs["response_type"] == "text"
        return RequestResult(False, UPDATED, html)

    monkeypatch.setattr(fastbull, "get", get)
    result = await fastbull.handle_route(request(board), no_cache=True)
    assert result.kind == "newsflash"
    assert result.updateTime == UPDATED
    assert len(result.data) == len({i.id for i in result.data}) == 2
    prefix = "/cn/fastshort/" if board == "express" else "/cn/news-detail/"
    assert all(i.id.startswith(prefix) for i in result.data)
    assert all(i.timestamp and i.timestamp > 1_000_000_000_000 for i in result.data)
    assert all(i.url != fastbull.SOURCE_LINK for i in result.data)
    if board == "news":
        assert all(i.summary and i.content == i.summary for i in result.data)

    # Newest-first order changes and repeated cards cannot change source IDs.
    soup = BeautifulSoup(html, "lxml")
    parent = soup.select_one("#main-content" if board == "express" else ".news_main")
    parent.insert(0, parent.contents[-1].extract())
    html = str(soup)
    again = await fastbull.handle_route(request(board), no_cache=True)
    assert {i.title: i.id for i in again.data} == {i.title: i.id for i in result.data}


@pytest.mark.parametrize("board,html", [
    ("express", '<div id="side_fast_news"><div class="news-list">sidebar only</div></div>'),
    ("news", '<html><h1>Access denied</h1></html>'),
    ("express", '<div id="main-content"><div class="news-list"><span class="title_name">消息</span></div></div>'),
    ("express", '<div id="main-content"><div class="news-list" data-id="123"><span class="title_name">消息</span><div data-href="/cn/fastshort/456"></div></div></div>'),
])
async def test_fastbull_rejects_missing_identity_or_main_list(monkeypatch, board, html):
    async def get(**kwargs):
        return RequestResult(False, UPDATED, html)
    monkeypatch.setattr(fastbull, "get", get)
    with pytest.raises(ValueError, match="FastBull"):
        await fastbull.handle_route(request(board))


@pytest.mark.parametrize("board", list(baidu.type_map))
async def test_baidu_id_survives_rank_and_score_changes(monkeypatch, board):
    payload = json.loads((FIXTURES / f"baidu-{board}.json").read_text())

    async def get(url, **kwargs):
        assert url == f"https://top.baidu.com/board?tab={board}"
        assert kwargs["no_cache"] is True
        assert kwargs["response_type"] == "text"
        return RequestResult(False, UPDATED, "<!--s-data:" + json.dumps(payload) + "-->")

    monkeypatch.setattr(baidu, "get", get)
    result = await baidu.handle_route(request(board), no_cache=True)
    assert len(result.data) == len({i.id for i in result.data}) == 2
    assert result.updateTime == UPDATED
    assert result.kind == "hotlist"
    original = {i.title: i.id for i in result.data}
    rows = payload["data"]["cards"][0]["content"]
    rows.reverse()
    for index, row in enumerate(rows):
        row.update(index=index + 20, hotScore="1")
    rows.append(copy.deepcopy(rows[0]))
    again = await baidu.handle_route(request(board), no_cache=True)
    assert len(again.data) == 2
    assert {i.title: i.id for i in again.data} == original
    rows[0].update(word="完全不同的话题", query="完全不同的话题")
    changed = await baidu.handle_route(request(board), no_cache=True)
    assert changed.data[0].id not in original.values()


@pytest.mark.parametrize("html", ["<html>challenge</html>", "<!--s-data:{}-->", "<!--s-data:broken-->"])
async def test_baidu_rejects_invalid_ranking(monkeypatch, html):
    async def get(*args, **kwargs):
        return RequestResult(False, UPDATED, html)
    monkeypatch.setattr(baidu, "get", get)
    with pytest.raises(ValueError, match="Baidu"):
        await baidu.handle_route(request("realtime"))


async def test_openai_nested_articles_are_distinct(monkeypatch):
    xml = (FIXTURES / "openai-news.xml").read_text()
    async def get(**kwargs):
        assert kwargs["url"] == "https://openai.com/news/rss.xml"
        assert kwargs["no_cache"] is True
        return RequestResult(False, UPDATED, xml)
    monkeypatch.setattr(openai_news, "get", get)
    result = await openai_news.handle_route(request("news"), no_cache=True)
    assert len(result.data) >= 2
    assert len({i.id for i in result.data}) == len(result.data)
    assert any("nvidia" in i.id for i in result.data)
    assert any("virgin-atlantic" in i.id for i in result.data)
    assert result.updateTime == UPDATED
    assert openai_news._slug("https://openai.com/index/old-story/") == "old-story"
    assert openai_news._slug("https://openai.com/index/a/story/?utm_source=x") == openai_news._slug("https://openai.com/index/a/story")


@pytest.mark.parametrize("board", list(eastmoney_market._DRAGON_TIGER_TYPES))
async def test_dragon_tiger_reasons_are_independent_and_stable(monkeypatch, board):
    payload = json.loads((FIXTURES / "eastmoney-dragon-tiger.json").read_text())
    dates = '<ul class="day_type">' + ''.join(f'<li data-value="{n}" date="2026-09-15"></li>' for n in (1, 3, 5, 10, 30)) + '</ul>'
    async def get(**kwargs):
        assert kwargs["no_cache"] is True
        assert kwargs["ttl"] == eastmoney_market.config.NEWSFLASH_CACHE_TTL
        if kwargs["url"] == eastmoney_market._DRAGON_TIGER_PAGE_URL:
            return RequestResult(False, "bootstrap-time", dates)
        assert kwargs["url"] == eastmoney_market._DATACENTER_URL
        assert kwargs["params"]["reportName"] == "RPT_DAILYBILLBOARD_DETAILSNEW"
        return RequestResult(False, UPDATED, payload)
    monkeypatch.setattr(eastmoney_market, "get", get)
    result = await eastmoney_market.handle_route(request(board), no_cache=True)
    assert len(result.data) == len({i.id for i in result.data}) == 2
    assert len({i.url for i in result.data}) == 1
    assert result.data[0].hot != result.data[1].hot
    assert result.updateTime == UPDATED
    ids = {i.id for i in result.data}
    payload["result"]["data"].reverse()
    for row in payload["result"]["data"]:
        row.update(BILLBOARD_NET_AMT=1, EXPLAIN="分析文案变更")
    payload["result"]["data"].append(copy.deepcopy(payload["result"]["data"][0]))
    again = await eastmoney_market.handle_route(request(board), no_cache=True)
    assert len(again.data) == 2
    assert {i.id for i in again.data} == ids


@pytest.mark.parametrize("payload", [{}, {"success": False}, {"result": {"data": [{}]}}])
async def test_dragon_tiger_malformed_response(monkeypatch, payload):
    if payload == {"result": {"data": [{}]}}:
        payload = json.loads((FIXTURES / "eastmoney-dragon-tiger.json").read_text())
        del payload["result"]["data"][0]["EXPLANATION"]
    async def get(**kwargs):
        if kwargs["url"] == eastmoney_market._DRAGON_TIGER_PAGE_URL:
            return RequestResult(False, UPDATED, '<ul class="day_type"><li data-value="1" date="2026-09-15"></li></ul>')
        return RequestResult(False, UPDATED, payload)
    monkeypatch.setattr(eastmoney_market, "get", get)
    with pytest.raises(ValueError, match="Eastmoney"):
        await eastmoney_market.handle_route(request("dragon-tiger-1d"))

from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import netease_news_channels
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/netease-news-channels",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _state_page(topic_id: str, rows: list[dict]) -> str:
    import json

    state = {"store": {"homeArticleList": {"params": {"topicId": topic_id}, "data": {"list": rows}}}}
    return "<html><script>window.__INITIAL_STATE__=" + json.dumps(state, ensure_ascii=False) + "</script></html>"


_ROW = {"docid": "ABCDEF1234567890", "title": "文章标题", "ptime": "2026-09-30 12:00:00",
        "imgsrc": "https://n.163.com/1.jpg", "source": "网易", "digest": "摘要", "commentCount": 66}


@pytest.mark.asyncio
async def test_touch_board_parses_initial_state(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured["url"] = url
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _state_page("BDC4QSV3wangning", [_ROW]))

    monkeypatch.setattr(netease_news_channels, "get", fake_get)
    result = await netease_news_channels.handle_route(_request("touch-jiankang"), no_cache=True)

    assert captured["url"] == "https://m.163.com/touch/jiankang/"
    assert result.type == "健康频道"
    item = result.data[0]
    assert item.id == "ABCDEF1234567890"
    assert item.url == "https://m.163.com/jiankang/article/ABCDEF1234567890.html"
    assert item.timestamp == 1790740800000  # 2026-09-30 12:00 北京时间
    assert item.hot == 66


@pytest.mark.asyncio
async def test_touch_news_keeps_top_and_dedupes(monkeypatch):
    flow_row = dict(_ROW)
    top_row = {"docid": "TOP0000000000001", "type": "doc", "isTop": 1, "title": "置顶要闻",
               "ptime": "2026-09-30 13:00:00", "tcount": 9, "source": "网易"}
    state = {
        "store": {
            "focusArticleList": {"params": {"topicId": "BCR0CBQ2wangning"}, "data": {"list": []}},
            "homeArticleList": {"params": {"topicId": "BBM54PGAwangning"}, "data": {"list": [flow_row, dict(_ROW)]}},
            "importantNews": {"data": {"toutiao": [top_row]}},
        }
    }
    page = "<html><script>window.__INITIAL_STATE__=" + netease_news_channels.json.dumps(state, ensure_ascii=False) + "</script></html>"

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", page)

    monkeypatch.setattr(netease_news_channels, "get", fake_get)
    result = await netease_news_channels.handle_route(_request("touch-news"), no_cache=True)

    # 置顶在前,重复 docid 只留第一次
    assert [i.id for i in result.data] == ["TOP0000000000001", "ABCDEF1234567890"]


@pytest.mark.asyncio
async def test_non_article_placeholders_are_skipped(monkeypatch):
    placeholder = dict(_ROW, docid="L7C50CSFdongxiru")  # 含小写,非文章占位,拼出的地址 404
    normal = dict(_ROW, docid="ZZZZZZ1111111111", title="正常文章")
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", _state_page("BD21K0DLwangning", [placeholder, normal]))

    monkeypatch.setattr(netease_news_channels, "get", fake_get)
    result = await netease_news_channels.handle_route(_request("exclusive-qsyk"), no_cache=True)
    assert [i.id for i in result.data] == ["ZZZZZZ1111111111"]  # 占位记录不算条目


@pytest.mark.asyncio
async def test_latest_board_merges_categories_and_sorts(monkeypatch):
    payload = {
        "category": [{"n": "国内"}, {"n": "国际"}],
        "news": [
            [{"t": "旧闻", "l": "https://www.163.com/dy/article/AAAAAA1111111111.html", "p": "2026-09-30 08:00:00"},
             {"t": "新闻", "l": "https://www.163.com/dy/article/BBBBBB2222222222.html", "p": "2026-09-30 12:00:00"}],
            [{"t": "国际", "l": "https://www.163.com/dy/article/CCCCCC3333333333.html", "p": "2026-09-30 10:00:00"}],
        ],
    }

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        assert "new_json2021.js" in url
        return RequestResult(False, "t", "var data = " + netease_news_channels.json.dumps(payload, ensure_ascii=False) + ";")

    monkeypatch.setattr(netease_news_channels, "get", fake_get)
    result = await netease_news_channels.handle_route(_request("news-latest"), no_cache=True)

    assert [i.title for i in result.data] == ["新闻", "国际", "旧闻"]  # 时间倒序
    assert result.data[0].id == "BBBBBB2222222222"


@pytest.mark.asyncio
async def test_missing_initial_state_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html>challenge</html>")

    monkeypatch.setattr(netease_news_channels, "get", fake_get)
    with pytest.raises(RuntimeError, match="__INITIAL_STATE__"):
        await netease_news_channels.handle_route(_request("touch-jiankang"), no_cache=True)

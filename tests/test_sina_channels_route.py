from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import sina_channels
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/sina-channels",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


ROLL_PAYLOAD = {
    "result": {
        "status": {"code": 0},
        "data": [
            {"docid": "doc1", "title": "滚动一", "url": "https://news.sina.com.cn/c/2026-09-30/doc1.shtml",
             "wapurl": "//news.sina.com.cn/c/2026-09-30/doc1.shtml", "img": {"u": "//n.sinaimg.cn/1.jpg"},
             "media_name": "媒体一", "intro": "简介", "ctime": 1790769600},
            {"docid": "doc1", "title": "重复", "url": "https://news.sina.com.cn/c/2026-09-30/doc1.shtml"},
        ],
    }
}


@pytest.mark.asyncio
async def test_roll_board_maps_fields(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", ROLL_PAYLOAD)

    monkeypatch.setattr(sina_channels, "get", fake_get)
    result = await sina_channels.handle_route(_request("news-roll"), no_cache=True)

    assert "pageid=153" in captured["url"] and "lid=2509" in captured["url"]
    assert captured["headers"]["Referer"] == "https://news.sina.com.cn/roll/"
    assert result.total == 1  # 重复链接去重
    item = result.data[0]
    assert item.id == "doc1"
    assert item.cover == "https://n.sinaimg.cn/1.jpg"  # // 补 https
    assert item.author == "媒体一"
    assert item.timestamp == 1790769600000  # 秒 -> 毫秒


ESTATE_PAYLOAD = {"data": [
    {"docid": "e1", "title": "房产一", "url": "https://finance.sina.com.cn/e1.html",
     "thumb": "https://n.sinaimg.cn/e.jpg", "media": "乐居", "comment_count": 88, "ctime": 1790769600},
]}


@pytest.mark.asyncio
async def test_estate_board_uses_tyfeed(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured["url"] = url
        return RequestResult(False, "t", ESTATE_PAYLOAD)

    monkeypatch.setattr(sina_channels, "get", fake_get)
    result = await sina_channels.handle_route(_request("finance-estate"), no_cache=True)

    assert "interface.sina.cn" in captured["url"] and "cids=249945" in captured["url"]
    item = result.data[0]
    assert item.hot == 88
    assert item.timestamp == 1790769600000


TOUSU_PAYLOAD = {"result": {"status": {"code": 0}, "data": {"articles": [
    {"id": "t1", "title": "投诉一", "url": "https://tousu.sina.com.cn/t1",
     "cover": "https://img.sina.cn/t.jpg", "media": "黑猫", "time": "2026.09.30 10:00"}
]}}}


@pytest.mark.asyncio
async def test_tousu_maps_beijing_time(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", TOUSU_PAYLOAD)

    monkeypatch.setattr(sina_channels, "get", fake_get)
    result = await sina_channels.handle_route(_request("tousu-hot"), no_cache=True)

    item = result.data[0]
    assert item.id == "t1"
    assert item.timestamp == 1790733600000  # 2026-09-30 10:00 北京时间


@pytest.mark.asyncio
async def test_tousu_error_status_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"result": {"status": {"code": 500, "msg": "err"}}})

    monkeypatch.setattr(sina_channels, "get", fake_get)
    with pytest.raises(RuntimeError, match="abnormal status"):
        await sina_channels.handle_route(_request("tousu-hot"), no_cache=True)


def _top_row(i: int, url: str) -> dict:
    return {"title": f"热文{i}", "url": url, "top_num": f"{1000 + i}", "media": "新浪",
            "ext2": "https://n.sinaimg.cn/h.jpg", "create_date": "2026-09-30", "create_time": "09:00:00"}


@pytest.mark.asyncio
async def test_comment_rank_all_applies_page_filter(monkeypatch):
    rows = [
        _top_row(0, "https://news.sina.com.cn/c/a.html"),
        _top_row(1, "https://sports.sina.com.cn/z/b.html"),
        _top_row(2, "https://ent.sina.com.cn/c/c.html"),
        _top_row(3, "https://finance.sina.com.cn/d.html"),
        _top_row(4, "https://weibo.com/external"),  # 非新浪域名,页面脚本剔除
    ]

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "var comment_all_data = " + sina_channels.json.dumps({"data": rows}) + ";")

    monkeypatch.setattr(sina_channels, "get", fake_get)
    result = await sina_channels.handle_route(_request("hotnews-comment-all"), no_cache=True)

    assert result.total == 4  # 外域链接被页面同款过滤剔除
    item = result.data[0]
    assert item.hot == 1000
    assert item.timestamp is not None
    assert result.message is None

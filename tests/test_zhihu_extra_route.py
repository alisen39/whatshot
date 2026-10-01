from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import zhihu_extra
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/zhihu-extra",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
async def test_hot_search_cleans_tracking_and_uses_query_as_id(monkeypatch):
    payload = {
        "hot_search_queries": [
            {
                "query": "话题一",
                "real_query": "话题一",
                "hot": 4810000,
                "redirect_link": "https://www.zhihu.com/search?utm=x&utm_medium=1&request_click_id=abc123",
            },
            {"query": "话题二", "real_query": "话题二", "hot": 1000, "redirect_link": "zhihu://search"},
        ]
    }

    async def fake_get(url, params=None, no_cache=None, **kwargs):
        assert url == "https://www.zhihu.com/api/v4/search/hot_search"
        return RequestResult(False, "2026-10-01T00:00:00+00:00", payload)

    monkeypatch.setattr(zhihu_extra, "get", fake_get)
    result = await zhihu_extra.handle_route(_request("hot-search"), no_cache=True)

    assert result.type == "热搜"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "话题一"  # query_id 是请求编号不能用,搜索词本身作 id
    assert first.url == "https://www.zhihu.com/search?utm=x&utm_medium=1"  # request_click_id 已去掉
    assert first.hot == 4810000
    second = result.data[1]
    assert second.url == "https://www.zhihu.com/search?type=content&q=%E8%AF%9D%E9%A2%98%E4%BA%8C"


@pytest.mark.asyncio
async def test_pin_news_uses_first_line_as_title(monkeypatch):
    payload = {
        "data": [
            {
                "target": {
                    "id": 7100000000000000001,
                    "content": [
                        {"type": "text", "content": "第一行内容<br/>第二行"},
                        {"type": "image", "url": "https://pic.zh/img.png"},
                    ],
                    "author": {"name": "作者"},
                    "reaction_count": 321,
                    "created": 1790769600,
                }
            }
        ]
    }

    async def fake_get(url, params=None, no_cache=None, **kwargs):
        assert "pins/special/972884951192113152/moments" in url
        assert params == {"order_by": "newest", "reverse_order": 0, "limit": 20}
        return RequestResult(False, "2026-10-01T00:00:00+00:00", payload)

    monkeypatch.setattr(zhihu_extra, "get", fake_get)
    result = await zhihu_extra.handle_route(_request("pin-news"), no_cache=True)

    item = result.data[0]
    assert item.id == "7100000000000000001"
    assert item.title == "第一行内容"  # 想法没有标题字段,取正文第一行
    assert item.desc == "第一行内容 第二行"
    assert item.author == "作者"
    assert item.cover == "https://pic.zh/img.png"
    assert item.hot == 321
    assert item.timestamp == 1790769600000


@pytest.mark.asyncio
async def test_new_books_and_weekly_share_book_mapping(monkeypatch):
    book = {"id": 1001, "title": "书名", "authors": [{"name": "甲"}, {"name": "乙"}], "cover": "https://img/1.jpg", "description": "简介"}

    async def fake_get(url, params=None, no_cache=None, **kwargs):
        if "books/features/new" in url:
            return RequestResult(False, "t", {"data": [book]})
        # weekly:服务端渲染页面内嵌 zh-data-state
        state = '{"weekly":{"allWeekly":{"data":[' + zhihu_extra.json.dumps(book, ensure_ascii=False) + "]}}}"
        return RequestResult(False, "t", f'<html><textarea id="zh-data-state">{state}</textarea></html>')

    monkeypatch.setattr(zhihu_extra, "get", fake_get)

    books = await zhihu_extra.handle_route(_request("new-books"), no_cache=True)
    assert books.data[0].id == "1001"
    assert books.data[0].author == "甲、乙"

    weekly = await zhihu_extra.handle_route(_request("weekly"), no_cache=True)
    assert weekly.data[0].title == "书名"


@pytest.mark.asyncio
async def test_weekly_missing_state_is_an_error(monkeypatch):
    async def fake_get(url, params=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html>其他页面</html>")

    monkeypatch.setattr(zhihu_extra, "get", fake_get)
    with pytest.raises(RuntimeError, match="zh-data-state"):
        await zhihu_extra.handle_route(_request("weekly"), no_cache=True)

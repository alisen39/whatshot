from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import hupu_boards
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str | None) -> Request:
    query = f"type={board_type}".encode() if board_type else b""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/hupu-boards",
        "query_string": query,
        "headers": [],
    })


def _page(payload: dict, *, before_mark: str = "虎扑社区") -> str:
    return (
        "<html><head><title>虎扑</title></head><body>"
        f"<div class='nav'>{before_mark}</div>"
        "<script>window.$$data = "
        + json.dumps(payload, ensure_ascii=False)
        + ";</script></body></html>"
    )


def _thread(tid: str, title: str, **extra) -> dict:
    return {"tid": tid, "title": title, "lights": 1, "replies": 2, **extra}


@pytest.mark.asyncio
async def test_category_board_limits_to_text_list_and_maps_fields(monkeypatch):
    captured = {}
    threads = [
        _thread(
            "642637392",
            "吴艳妮赛后落泪",
            cover="https://i3.hoopchina.com.cn/1.jpeg",
            desc="2026名古屋亚运会田径项目摘要",
        )
    ]
    threads += [_thread(f"6426400{i:02d}", f"帖子{i}") for i in range(65)]

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers})
        payload = {
            "cateId": "1",
            "pageData": {
                "category": {"cateId": "1", "name": "步行街", "url": "/all-gambia"},
                "threads": threads,
            },
        }
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _page(payload))

    monkeypatch.setattr(hupu_boards, "get", fake_get)
    result = await hupu_boards.handle_route(_request("all-gambia"), no_cache=True)

    assert captured["url"] == "https://bbs.hupu.com/all-gambia"
    # 浏览器 UA 是硬口径:bbs.hupu.com 的阿里云 WAF 拦 python- 开头的 UA
    assert "Mozilla/5.0" in captured["headers"]["User-Agent"]
    assert result.name == "hupu-boards"
    assert result.title == "虎扑社区"
    assert result.type == "步行街热帖"
    assert result.link == "https://bbs.hupu.com/all-gambia"
    assert result.total == 60  # 数据里有 66 条,页面缺省文字列表只渲染前 60 条
    first = result.data[0]
    assert first.id == "642637392"
    assert first.title == "吴艳妮赛后落泪"
    assert first.url == "https://bbs.hupu.com/642637392.html"
    assert first.mobileUrl == first.url
    assert first.hot == 2  # 回复数,不是亮数
    assert first.cover == "https://i3.hoopchina.com.cn/1.jpeg"
    assert first.desc == "2026名古屋亚运会田径项目摘要"
    assert first.timestamp is None  # 分区热帖数据里没有发帖时间


@pytest.mark.asyncio
async def test_category_board_rejects_fallback_home_page(monkeypatch):
    # 已下线的 /all-life 就是这样:返回 200 但回落成全站"虎扑社区"页
    payload = {
        "cateId": "0",
        "pageData": {
            "category": {"cateId": "0", "name": "虎扑社区", "url": "/"},
            "threads": [_thread("111", "全站帖")],
        },
    }

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", _page(payload))

    monkeypatch.setattr(hupu_boards, "get", fake_get)
    with pytest.raises(RuntimeError, match="fallback"):
        await hupu_boards.handle_route(_request("all-gambia"), no_cache=True)


@pytest.mark.asyncio
async def test_topic_board_maps_author_and_created_at(monkeypatch):
    payload = {
        "topic": {
            "topic": {"topicId": "6", "name": "恋爱区", "url": "/love"},
            "sort": "4",  # 页面有时给数字、有时给字符串
            "threads": {
                "list": [
                    {
                        "tid": "642620007",
                        "title": "马上要结婚了",
                        "cover": "",
                        "lights": 47,
                        "replies": 159,
                        "read": 43824,
                        "createdAt": 1790434119000,
                        "author": {"puid": "18556221", "puname": "circleygt"},
                    },
                    {"tid": "642600000", "title": "没有时间的帖子", "replies": 2},
                ]
            },
        }
    }

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        assert url == "https://bbs.hupu.com/love-hot"
        return RequestResult(False, "t", _page(payload, before_mark="恋爱区"))

    monkeypatch.setattr(hupu_boards, "get", fake_get)
    result = await hupu_boards.handle_route(_request("love-hot"), no_cache=True)

    assert result.type == "恋爱区 · 24小时榜"
    assert result.total == 2
    first = result.data[0]
    assert first.author == "circleygt"  # author.puname,分区热帖里没有
    assert first.timestamp == 1790434119000  # createdAt 毫秒
    assert first.hot == 159
    assert first.cover is None  # 空串归一为 None
    second = result.data[1]
    assert second.timestamp is None


@pytest.mark.asyncio
async def test_topic_board_rejects_sort_mismatch(monkeypatch):
    # 请求 24小时榜(sort=4),页面给的却是最新回复(sort=2):结构漂移,报错
    payload = {
        "topic": {
            "topic": {"topicId": "21", "name": "股票区", "url": "/stock"},
            "sort": 2,
            "threads": {"list": [_thread("222", "股票帖")]},
        }
    }

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", _page(payload, before_mark="股票区"))

    monkeypatch.setattr(hupu_boards, "get", fake_get)
    with pytest.raises(RuntimeError, match="股票区"):
        await hupu_boards.handle_route(_request("stock-hot"), no_cache=True)


@pytest.mark.asyncio
async def test_news_board_maps_img_content_and_keeps_prefix(monkeypatch):
    payload = {
        "menu": [],
        "pageData": [
            {
                "img": "https://i5.hoopchina.com.cn/1.png",
                "title": "[流言板]增强无球属性！",
                "content": "虎扑09月28日讯 内容摘要",
                "tid": 642642370,
                "topicName": "篮球资讯",
                "replies": 2,
                "lights": 0,
            },
            {"title": "没有 tid 的记录", "content": "x"},
        ],
    }

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        assert url == "https://www.hupu.com/"
        return RequestResult(False, "t", _page(payload, before_mark="虎扑资讯"))

    monkeypatch.setattr(hupu_boards, "get", fake_get)
    result = await hupu_boards.handle_route(_request("news"), no_cache=True)

    assert result.title == "虎扑"  # 资讯来自 www.hupu.com 首页,站点名跟页面走
    assert result.type == "虎扑资讯"
    assert result.total == 1  # 缺 tid 的占位记录跳过
    item = result.data[0]
    assert item.id == "642642370"  # 页面数据里 tid 是数字
    assert item.title == "[流言板]增强无球属性！"  # 前缀照原站保留
    assert item.cover == "https://i5.hoopchina.com.cn/1.png"
    assert item.desc == "虎扑09月28日讯 内容摘要"
    assert item.timestamp is None  # 只有日期没有时刻,不编


@pytest.mark.asyncio
async def test_missing_embedded_data_raises(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html><body>改版后的页面,没有内嵌数据</body></html>")

    monkeypatch.setattr(hupu_boards, "get", fake_get)
    with pytest.raises(RuntimeError, match=r"window\.\$\$data"):
        await hupu_boards.handle_route(_request("all-nba"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_board_and_default_board(monkeypatch):
    with pytest.raises(ValueError, match="Unknown board"):
        await hupu_boards.handle_route(_request("1"), no_cache=True)  # 1/6/... 属于 hupu 路由

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        payload = {
            "cateId": "1",
            "pageData": {
                "category": {"cateId": "1", "name": "步行街", "url": "/all-gambia"},
                "threads": [_thread("333", "默认榜帖")],
            },
        }
        return RequestResult(False, "t", _page(payload))

    monkeypatch.setattr(hupu_boards, "get", fake_get)
    result = await hupu_boards.handle_route(_request(None), no_cache=True)
    first_type = next(iter(hupu_boards.type_map))
    assert first_type == "all-gambia"  # 声明序第一个是默认榜
    assert result.type == hupu_boards.type_map[first_type]

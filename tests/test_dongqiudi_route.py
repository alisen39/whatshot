from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import dongqiudi
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/dongqiudi",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _article(aid: int, **overrides: object) -> dict:
    row: dict = {
        "id": aid,
        "title": f"文章{aid}",
        "share": f"https://www.dongqiudi.com/article/{aid}",
        "thumb": f"https://bdimg7.qunliao.info/{aid}.jpg",
        "top": False,
        "comments_total": 10,
        "author_name": "作者甲",
        "description": "",
        "show_time": 1790774705,
    }
    row.update(overrides)
    return row


# m 站频道页签(中超):置顶条的 published_at 是未来年份,show_time 是真实时间
_CSL_PAYLOAD = {
    "id": 56,
    "articles": [
        _article(
            6417978,
            title="海报：看成败，人生豪迈",
            top=True,
            comments_total=862,
            share="https://n.dongqiudi.com/webapp/tops.html?id=6417978",  # 海报类 mini_top
            published_at="2029-09-29 15:54:45",
            show_time=1885362885,  # 置顶排序把时间改成未来年份,晚于当前时间的一律留空
        ),
        _article(6419316),
    ],
}


@pytest.mark.asyncio
async def test_m_tab_maps_share_links_and_blank_future_timestamp(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, response_type=None, **kwargs):
        captured.update({"url": url, "params": params, "headers": headers})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _CSL_PAYLOAD)

    monkeypatch.setattr(dongqiudi, "get", fake_get)
    result = await dongqiudi.handle_route(_request("csl"), no_cache=True)

    assert captured["url"] == "https://api.dongqiudi.com/app/tabs/iphone/56.json"
    assert captured["params"] == {"mark": "gif", "version": "576"}  # m 站 homeSubTabList 自带参数
    assert (captured["headers"] or {}).get("User-Agent", "").startswith("Mozilla/5.0")  # 程序 UA 会被 567 拦
    assert result.type == "中超"
    first = result.data[0]  # 置顶条在前
    assert first.id == "6417978"
    assert first.url == "https://www.dongqiudi.com/articles/6417978.html"  # n.dongqiudi 海报 H5 改用 PC 链接
    assert first.mobileUrl == "https://m.dongqiudi.com/article/6417978.html"
    assert first.timestamp is None  # 未来年份的置顶时间留空,不输出未来时间
    second = result.data[1]
    assert second.url == "https://www.dongqiudi.com/article/6419316"  # m 站子榜取分享链接
    assert second.timestamp == 1790774705000  # show_time 秒 -> 毫秒
    assert second.author == "作者甲"


_HOT_PAYLOAD = {
    "id": 104,
    "contents": [
        {"day": "2026-09-30", "articles": [_article(6419316, title="点球大战日本U23 10-9乌兹别克斯坦U23")]},
        {"day": "2026-09-29", "articles": [_article(6418000, title="前一天的热门")]},
    ],
}


@pytest.mark.asyncio
async def test_hot_board_flattens_day_groups(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, response_type=None, **kwargs):
        return RequestResult(False, "t", _HOT_PAYLOAD)

    monkeypatch.setattr(dongqiudi, "get", fake_get)
    result = await dongqiudi.handle_route(_request("hot"), no_cache=True)

    assert [item.id for item in result.data] == ["6419316", "6418000"]  # 按组顺序展开


_PC_TAB_PAYLOAD = {"id": 1, "articles": [_article(101, comments_total=5), _article(6419316, comments_total=1209), _article(103, comments_total=88)]}


@pytest.mark.asyncio
async def test_pc_tab_puts_headline_article_first(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, response_type=None, **kwargs):
        captured["url"] = url
        return RequestResult(False, "t", _PC_TAB_PAYLOAD)

    monkeypatch.setattr(dongqiudi, "get", fake_get)
    result = await dongqiudi.handle_route(_request("headline"), no_cache=True)

    assert captured["url"] == "https://www.dongqiudi.com/api/app/tabs/web/1.json"
    # 页面把评论数最多的一条做大图头条放在最上面,其余照接口顺序
    assert [item.id for item in result.data] == ["6419316", "101", "103"]
    assert result.data[0].url == "https://www.dongqiudi.com/articles/6419316.html"  # PC 子榜用 PC 链接


_TEAM_PAYLOAD = {"code": 200, "message": "success", "data": {"page": 1, "size": 30, "articles": [_article(6419067, title="意媒：多纳鲁马或离队")]}}


@pytest.mark.asyncio
async def test_team_board_sends_page_query_and_maps_data_articles(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, response_type=None, **kwargs):
        captured.update({"url": url, "params": params})
        return RequestResult(False, "t", _TEAM_PAYLOAD)

    monkeypatch.setattr(dongqiudi, "get", fake_get)
    result = await dongqiudi.handle_route(_request("team-acmilan"), no_cache=True)

    assert captured["url"] == "https://www.dongqiudi.com/api/v3/archive/app/channel/feeds"
    assert captured["params"] == {
        "id": "50001038",
        "type": "team",
        "size": "30",  # 与页面 SSR 一致
        "platform": "web",  # 必需;不带返回另一份未按 web 过滤的列表
        "version": "",
    }
    assert result.type == "AC米兰"
    assert result.data[0].id == "6419067"
    assert result.data[0].url == "https://www.dongqiudi.com/articles/6419067.html"


_COLUMN_PAYLOAD = {
    "id": 48,
    "total": 3544,
    "data": [{"aid": "6416501", "title": "早报：你这是要和英超打擂台？", "litpic": "https://img1.qunliao.info/6416501.jpg", "show_time": 1790722800, "comments_total": 218}],
}


@pytest.mark.asyncio
async def test_column_board_maps_aid_and_litpic(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, response_type=None, **kwargs):
        return RequestResult(False, "t", _COLUMN_PAYLOAD)

    monkeypatch.setattr(dongqiudi, "get", fake_get)
    result = await dongqiudi.handle_route(_request("morning"), no_cache=True)

    assert result.type == "早报"
    item = result.data[0]
    assert item.id == "6416501"  # 早报条目用 aid
    assert item.cover == "https://img1.qunliao.info/6416501.jpg"  # litpic
    assert item.author is None  # 早报接口没有作者
    assert item.timestamp == 1790722800000


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await dongqiudi.handle_route(_request("nonsense"), no_cache=True)


@pytest.mark.asyncio
async def test_empty_rows_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, response_type=None, **kwargs):
        return RequestResult(False, "t", {"id": 56, "articles": []})

    monkeypatch.setattr(dongqiudi, "get", fake_get)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await dongqiudi.handle_route(_request("csl"), no_cache=True)


@pytest.mark.asyncio
async def test_non_dict_payload_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, response_type=None, **kwargs):
        return RequestResult(False, "t", ["unexpected"])

    monkeypatch.setattr(dongqiudi, "get", fake_get)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await dongqiudi.handle_route(_request("depth"), no_cache=True)

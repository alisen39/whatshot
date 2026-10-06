from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import yicai_21jingji
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str | None = None) -> Request:
    query = f"type={board_type}" if board_type else ""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/yicai-21jingji",
        "query_string": query.encode(),
        "headers": [],
    })


def _rank_payload() -> dict:
    return {
        "newsRank": {
            "week": [
                {"NewsID": 103378496, "NewsTitle": "刘欢去世", "NewsType": 10, "url": "/news/103378496.html"},
                {"NewsID": 103375756, "NewsTitle": "以旧换新", "NewsType": 10,
                 "url": "https://www.yicai.com/news/103375756.html"},
            ],
            "month": [
                {"NewsID": 999, "NewsTitle": "月榜条目不应出现", "url": "/news/999.html"},
            ],
        }
    }


def _embedded_page(var: str, rows: list[dict]) -> str:
    return f"<html><script>var {var}={json.dumps(rows, ensure_ascii=False)};</script></html>"


def _headline_row(news_id: int, url_path: str, **extra: object) -> dict:
    row = {
        "NewsID": news_id,
        "NewsTitle": f"标题{news_id}",
        "url": url_path,
        "NewsHot": 39298,
        "originPic": "",
        "NewsThumbs": "https://imgcdn.yicai.com/thumb.jpg",
        "NewsAuthor": "一财资讯",
        "NewsNotes": "摘要",
        "CreateDate": "2026-09-28T08:04:43",
    }
    row.update(extra)
    return row


def _m21_row(row_id: str, **extra: object) -> dict:
    row = {
        "id": row_id,
        "title": f"标题{row_id}",
        "type": "text",
        "url": f"https://m.21jingji.com/article/20260928/herald/{row_id}.html",
        "updatetime": "1790553660",
        "author": "闫硕",
        "description": "",
        "listthumb": "https://img.21jingji.com/small.jpg",
    }
    row.update(extra)
    return row


@pytest.mark.asyncio
async def test_rank_board_takes_week_and_joins_relative_urls(monkeypatch):
    captured = {}

    async def fake_get(url, no_cache=None, **kwargs):
        captured["url"] = url
        captured["no_cache"] = no_cache
        return RequestResult(False, "t", _rank_payload())

    monkeypatch.setattr(yicai_21jingji, "get", fake_get)
    result = await yicai_21jingji.handle_route(_request("yicai-news-rank"), no_cache=True)

    assert captured["url"] == "https://www.yicai.com/api/ajax/getranklistbykeys?keys=newsRank"
    assert captured["no_cache"] is True
    assert result.type == "第一财经 · 新闻排行周榜"
    assert result.total == 2  # month 不取，只取 week
    first = result.data[0]
    assert first.id == "103378496"
    assert first.title == "刘欢去世"
    assert first.url == "https://www.yicai.com/news/103378496.html"  # 相对链接补全
    assert first.timestamp is None  # 排行条目没有时间
    assert first.hot is None


@pytest.mark.asyncio
async def test_rank_board_without_week_rows_is_an_error(monkeypatch):
    async def fake_get(url, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"videoRank": {"week": []}})

    monkeypatch.setattr(yicai_21jingji, "get", fake_get)
    with pytest.raises(RuntimeError, match="no items"):
        await yicai_21jingji.handle_route(_request("yicai-video-rank"), no_cache=True)


@pytest.mark.asyncio
async def test_headline_slices_first_30_and_generates_mobile_url(monkeypatch):
    rows = [
        _headline_row(103378916, "/news/103378916.html"),
        _headline_row(103383064, "/vip/news/103383064.html", originPic="https://imgcdn.yicai.com/vip.jpg"),
        _headline_row(103383001, "/video/103383001.html", NewsHot=0),
    ]
    rows.extend(_headline_row(200000 + index, f"/news/{200000 + index}.html") for index in range(40))

    async def fake_get(url, no_cache=None, **kwargs):
        assert url == "https://www.yicai.com/"
        return RequestResult(False, "t", _embedded_page("headList", rows))

    monkeypatch.setattr(yicai_21jingji, "get", fake_get)
    result = await yicai_21jingji.handle_route(_request("yicai-headline"), no_cache=True)

    assert result.total == 30  # 首屏 30 条（index.js 按 30 切片），内嵌共 43 条
    first = result.data[0]
    assert first.id == "103378916"
    assert first.url == "https://www.yicai.com/news/103378916.html"
    # gotoMurl.js 规则：协议 + 域名换成 m.yicai.com，路径不变；不用内嵌 ShareUrl
    assert first.mobileUrl == "https://m.yicai.com/news/103378916.html"
    assert first.hot == 39298
    assert first.cover == "https://imgcdn.yicai.com/thumb.jpg"  # originPic 为空时取 NewsThumbs
    assert first.author == "一财资讯"
    assert first.desc == "摘要"
    assert first.timestamp == 1790553883000  # CreateDate 2026-09-28T08:04:43 北京时间
    vip = result.data[1]
    assert vip.mobileUrl == "https://m.yicai.com/vip/news/103383064.html"  # 会员稿同规则
    assert result.data[2].hot is None  # NewsHot=0 视为没有热度


@pytest.mark.asyncio
async def test_auto_board_uses_firstlist_and_first_screen_25(monkeypatch):
    rows = [_headline_row(300000 + index, f"/news/{300000 + index}.html") for index in range(30)]

    async def fake_get(url, no_cache=None, **kwargs):
        assert url == "https://www.yicai.com/news/automobile/"
        return RequestResult(False, "t", _embedded_page("firstlist", rows))

    monkeypatch.setattr(yicai_21jingji, "get", fake_get)
    result = await yicai_21jingji.handle_route(_request("yicai-auto"), no_cache=True)

    assert result.total == 25  # 频道页首屏 25 条（newslist.js 按 25 切片）
    assert result.data[0].mobileUrl == "https://m.yicai.com/news/300000.html"


@pytest.mark.asyncio
async def test_missing_embedded_var_is_an_error(monkeypatch):
    async def fake_get(url, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html>改版后的页面</html>")

    monkeypatch.setattr(yicai_21jingji, "get", fake_get)
    with pytest.raises(RuntimeError, match="var headList"):
        await yicai_21jingji.handle_route(_request("yicai-headline"), no_cache=True)


@pytest.mark.asyncio
async def test_m21_health_token_flow_maps_rows_and_filters_ads(monkeypatch):
    captured = {}

    async def fake_post(url, headers=None, no_cache=None, **kwargs):
        captured["token_url"] = url
        captured["token_headers"] = headers
        captured["token_no_cache"] = no_cache
        return RequestResult(False, "t", {"status": 1, "token": "Bearer test-token-value"})

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured["list_url"] = url
        captured["list_headers"] = headers
        rows = [
            _m21_row("900870"),
            _m21_row("4336", type="link", model="zhuanti",
                     url="https://m.21jingji.com/jujiao/getList?ztid=4336"),
            _m21_row("777", isAD=1, platform=101),
        ]
        return RequestResult(False, "t", rows)

    monkeypatch.setattr(yicai_21jingji, "post", fake_post)
    monkeypatch.setattr(yicai_21jingji, "get", fake_get)
    result = await yicai_21jingji.handle_route(_request("21jingji-health"), no_cache=True)

    assert captured["token_url"] == "https://m.21jingji.com/reader/cbhChannelAuth"
    assert captured["token_no_cache"] is True
    # 手机站对程序 UA 返回 493，必须带浏览器 UA
    assert captured["token_headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert captured["list_url"] == (
        "https://m.21jingji.com/channel/healthnews?short=healthnews&type=json&page=1"
    )
    assert captured["list_headers"]["Authorization"] == "Bearer test-token-value"
    assert result.total == 2  # isAD=1 的广告位不算条目
    topic = result.data[1]
    assert topic.id == "zt4336"  # 专题与文章是两套编号，加前缀
    assert topic.timestamp == 1790553660000  # updatetime Unix 秒 -> 毫秒
    assert result.data[0].cover == "https://img.21jingji.com/small.jpg"


@pytest.mark.asyncio
async def test_m21_hot_accepts_string_updatetime(monkeypatch):
    async def fake_post(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"status": 1, "token": "Bearer test-token-value"})

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        assert url == "https://m.21jingji.com/reader/index?more=1&type=json&page=1"
        return RequestResult(
            False, "t", [_m21_row("900872", updatetime="2026-09-28 08:04")]
        )

    monkeypatch.setattr(yicai_21jingji, "post", fake_post)
    monkeypatch.setattr(yicai_21jingji, "get", fake_get)
    result = await yicai_21jingji.handle_route(_request("21jingji-hot"), no_cache=True)

    assert result.data[0].timestamp == 1790553840000  # "YYYY-MM-DD HH:MM" 北京时间
    assert result.data[0].mobileUrl == result.data[0].url  # 本身就是手机站链接


@pytest.mark.asyncio
async def test_m21_token_failure_is_an_error(monkeypatch):
    async def fake_post(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"status": 0, "message": "denied"})

    async def fake_get(url, headers=None, no_cache=None, **kwargs):  # pragma: no cover
        raise AssertionError("token failure must not trigger the list request")

    monkeypatch.setattr(yicai_21jingji, "post", fake_post)
    monkeypatch.setattr(yicai_21jingji, "get", fake_get)
    with pytest.raises(RuntimeError, match="no token"):
        await yicai_21jingji.handle_route(_request("21jingji-hot"), no_cache=True)


@pytest.mark.asyncio
async def test_m21_html_response_is_an_error(monkeypatch):
    async def fake_post(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"status": 1, "token": "Bearer test-token-value"})

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        # token 缺失 / 错误时接口返回 404 HTML 页
        return RequestResult(False, "t", "<!DOCTYPE html PUBLIC>404 page")

    monkeypatch.setattr(yicai_21jingji, "post", fake_post)
    monkeypatch.setattr(yicai_21jingji, "get", fake_get)
    with pytest.raises(RuntimeError, match="did not return a list"):
        await yicai_21jingji.handle_route(_request("21jingji-health"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_type_is_rejected(monkeypatch):
    async def fake_get(url, no_cache=None, **kwargs):  # pragma: no cover
        raise AssertionError("unknown type must not trigger any request")

    monkeypatch.setattr(yicai_21jingji, "get", fake_get)
    with pytest.raises(ValueError, match="Unknown board"):
        await yicai_21jingji.handle_route(_request("yicai-other"), no_cache=True)

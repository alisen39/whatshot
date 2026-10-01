from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import infzm_latepost
from whats_hot_api.utils.http_client import RequestResult

_BEIJING = timezone(timedelta(hours=8))
# 晚点接口响应的 Date 头固定为 2026-09-30 15:00 GMT(北京时间 23:00,当天),相对日期以它为基准。
_LATEPOST_DATE_HEADER = "Wed, 30 Sep 2026 15:00:00 GMT"
_UPDATE_TIME = "2026-09-30T15:00:00+00:00"


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/infzm-latepost",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _latepost_result(rows: list[dict[str, Any]]) -> RequestResult:
    return RequestResult(
        False,
        _UPDATE_TIME,
        {"data": {"code": "1", "data": rows}, "status": 200, "headers": {"Date": _LATEPOST_DATE_HEADER}},
    )


def _ms(beijing_naive: str) -> int:
    moment = datetime.strptime(beijing_naive, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_BEIJING)
    return int(moment.timestamp() * 1000)


# ---------------------------------------------------------------- 南方周末


@pytest.mark.asyncio
async def test_infzm_contents_board_maps_fields(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(url, params=None, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "params": params, "headers": headers, "no_cache": no_cache})
        return RequestResult(False, _UPDATE_TIME, {
            "code": 200,
            "data": {
                "current_term": {"id": 998, "title": "推荐", "type": "module"},
                "contents": [
                    {
                        "id": 331624,
                        "subject": "李梅：现实版“忆秦娥”",
                        "author": "\u200b南方人物周刊记者 梁辰 ",  # 原站作者偶有零宽空格开头
                        "publish_time": "2026-09-27 23:00:00",
                        "introtext": "“秦腔不能总让老年人抹泪”",
                        "covers": [{"file_path": "http://images.infzm.com/cms/medias/image/26/09/24/a.jpg"}],
                    },
                    {"id": 331111, "short_subject": "只有 short_subject 的稿件", "publish_time": "", "list_desc": "列表摘要"},
                ],
            },
        })

    monkeypatch.setattr(infzm_latepost, "get", fake_get)
    result = await infzm_latepost.handle_route(_request("infzm-recommend"), no_cache=True)

    assert captured["url"] == "https://www.infzm.com/contents"
    assert captured["params"] == {"term_id": "998", "page": "1", "format": "json"}  # 今日推荐 = 998(PC 首页"推荐"区块)
    assert captured["no_cache"] is True
    assert result.type == "南方周末 · 今日推荐"
    assert result.message == "推荐（term_id=998）"
    first = result.data[0]
    assert first.id == "331624"
    assert first.title == "李梅：现实版“忆秦娥”"
    assert first.url == first.mobileUrl == "https://www.infzm.com/contents/331624"  # 不带 source 统计参数
    assert first.author == "南方人物周刊记者 梁辰"
    assert first.cover == "http://images.infzm.com/cms/medias/image/26/09/24/a.jpg"
    assert first.timestamp == _ms("2026-09-27 23:00:00")  # 毫秒
    second = result.data[1]
    assert second.title == "只有 short_subject 的稿件"
    assert second.desc == "列表摘要"  # introtext 缺失时退 list_desc
    assert second.timestamp is None


@pytest.mark.asyncio
async def test_infzm_hot_board_uses_hot_contents_endpoint(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(url, params=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return RequestResult(False, _UPDATE_TIME, {
            "code": 200,
            "data": {"hot_contents": [{"id": 331695, "subject": "逝者丨刘欢", "publish_time": "2026-09-26 13:42:44"}]},
        })

    monkeypatch.setattr(infzm_latepost, "get", fake_get)
    result = await infzm_latepost.handle_route(_request("infzm-hot"), no_cache=True)

    assert captured["url"] == "https://www.infzm.com/hot_contents"
    assert captured["params"] == {"format": "json"}
    assert result.message == "热门文章"
    assert result.data[0].id == "331695"
    assert result.data[0].timestamp == _ms("2026-09-26 13:42:44")


@pytest.mark.asyncio
async def test_infzm_error_shell_and_empty_parse_raise(monkeypatch):
    async def fake_get(url, params=None, **kwargs):
        if params.get("term_id") == "2":
            return RequestResult(False, _UPDATE_TIME, {"code": 401, "data": None, "msg": "unauthorized"})
        if params.get("term_id") == "3":
            return RequestResult(False, _UPDATE_TIME, {"code": 200, "data": {"contents": []}})
        return RequestResult(False, _UPDATE_TIME, {"code": 200, "data": {"current_term": {"title": "观点"}}})

    monkeypatch.setattr(infzm_latepost, "get", fake_get)
    # 业务错误壳不得静默降级为空榜
    with pytest.raises(RuntimeError, match="code=401"):
        await infzm_latepost.handle_route(_request("infzm-news"), no_cache=True)
    # 空解析同样报错
    with pytest.raises(RuntimeError, match="parsed no items"):
        await infzm_latepost.handle_route(_request("infzm-opinion"), no_cache=True)


# ---------------------------------------------------------------- 晚点


@pytest.mark.asyncio
async def test_latepost_programa_board_posts_form(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "body": body, "headers": headers, "cache_key": kwargs.get("cache_key")})
        return _latepost_result([
            {
                "id": "3741",
                "title": "晚点独家丨2 亿日活之后，豆包开始收缩对话团队",
                "intro": "栏目页显示 intro 字段",
                "abstract": "不是栏目页显示的字段",
                "cover": "/uploads/cover/bc4ed0fb.png",
                "release_time": "09月22日",
                "detail_url": "/news/dj_detail?id=3741",
            },
        ])

    monkeypatch.setattr(infzm_latepost, "post", fake_post)
    result = await infzm_latepost.handle_route(_request("latepost-newsletter"), no_cache=True)

    assert captured["url"] == "https://www.latepost.com/news/get-news-data"
    assert captured["body"] == "page=1&limit=10&programa=3"  # 表单编码,栏目页内联脚本的参数
    assert captured["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert captured["cache_key"] == "infzm-latepost:latepost-newsletter"
    assert result.message == "programa=3"
    item = result.data[0]
    assert item.id == "3741"
    assert item.desc == "栏目页显示 intro 字段"  # 人物访谈 / 晚点早知道显示 intro
    assert item.url == item.mobileUrl == "https://www.latepost.com/news/dj_detail?id=3741"
    assert item.cover == "https://www.latepost.com/uploads/cover/bc4ed0fb.png"
    assert item.timestamp == _ms("2026-09-22 00:00:00")  # Date 头基准 2026-09-30,当年日期按不晚于今天推年份


@pytest.mark.asyncio
async def test_latepost_dates_use_response_date_header(monkeypatch):
    rows = [
        {"id": "1", "title": "今天的稿件", "release_time": "今天", "abstract": "晚点独家显示 abstract"},
        {"id": "2", "title": "昨天的稿件", "release_time": "昨天", "abstract": "晚点独家显示 abstract"},
        {"id": "3", "title": "前天的稿件", "release_time": "前天", "abstract": "晚点独家显示 abstract"},
        {"id": "4", "title": "跨年的日期", "release_time": "12月30日", "abstract": "晚点独家显示 abstract"},
        {"id": "5", "title": "往年的日期", "release_time": "2025年09月29日", "abstract": "晚点独家显示 abstract"},
        {"id": "6", "title": "解析不了的日期", "release_time": "N/A", "abstract": "晚点独家显示 abstract"},
    ]

    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        # Date 头是 2026-09-30 15:00 GMT,北京日期 2026-09-30;不用本机当前时间。
        return _latepost_result(rows)

    monkeypatch.setattr(infzm_latepost, "post", fake_post)
    result = await infzm_latepost.handle_route(_request("latepost-exclusive"), no_cache=True)

    stamps = {item.id: item.timestamp for item in result.data}
    assert stamps["1"] == _ms("2026-09-30 00:00:00")
    assert stamps["2"] == _ms("2026-09-29 00:00:00")
    assert stamps["3"] == _ms("2026-09-28 00:00:00")
    assert stamps["4"] == _ms("2025-12-30 00:00:00")  # 比今天(基准日)晚,算去年
    assert stamps["5"] == _ms("2025-09-29 00:00:00")  # 带年份照用
    assert stamps["6"] is None  # 解析不了留空,条目本身保留
    assert all(item.desc == "晚点独家显示 abstract" for item in result.data)  # programa=1 用 abstract


@pytest.mark.asyncio
async def test_latepost_latest_merges_headline_and_list(monkeypatch):
    calls: list[tuple[str, Any]] = []
    home_html = """
    <div id="content-box">
      <div class="headlines">
        <a href="/news/dj_detail?id=3736" target="_blank"></a>
        <img class="headlines-pic" src="/uploads/bg_img/e436.jpeg?1790551397" alt="">
        <div class="headlines-body">
          <div class="headlines-title"><a href="/news/dj_detail?id=3736" target="_blank">阿里达摩院医疗 AI</a></div>
          <div class="headlines-abstract">从一个个具体的现实困难出发。</div>
        </div>
      </div>
    </div>
    """

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        calls.append(("GET", url))
        return RequestResult(True, _UPDATE_TIME, home_html)

    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        calls.append(("POST", url, body))
        if "/site/index" in url:
            assert body == "page=1&limit=5"
            return _latepost_result([
                {"id": "3736", "title": "头条也在列表里", "abstract": "重复的头条", "detail_url": "/news/dj_detail?id=3736", "release_time": "09月09日"},
                {"id": "3746", "title": "列表第一篇", "abstract": "列表摘要", "detail_url": "/news/dj_detail?id=3746", "release_time": "09月09日"},
            ])
        assert body == "page=1&limit=20&programa=0"  # 日期对照请求
        return _latepost_result([
            {"id": "3746", "title": "", "release_time": "09月24日"},
            {"id": "3736", "title": "", "release_time": "今天"},
        ])

    monkeypatch.setattr(infzm_latepost, "get", fake_get)
    monkeypatch.setattr(infzm_latepost, "post", fake_post)
    result = await infzm_latepost.handle_route(_request("latepost-latest"), no_cache=False)

    assert [item.id for item in result.data] == ["3736", "3746"]  # 头条在前,按 id 去重
    headline, listed = result.data
    assert headline.title == "阿里达摩院医疗 AI"
    assert headline.desc == "从一个个具体的现实困难出发。"
    assert headline.cover == "https://www.latepost.com/uploads/bg_img/e436.jpeg"  # 去掉 ?时间戳
    assert headline.timestamp == _ms("2026-09-30 00:00:00")  # 日期按 id 从 programa=0 对上("今天")
    assert listed.timestamp == _ms("2026-09-24 00:00:00")  # /site/index 自己的 release_time 是坏的,不采用
    assert result.message == "首页头条 + 列表"
    assert ("POST", "https://www.latepost.com/site/index") == (calls[1][0], calls[1][1])


@pytest.mark.asyncio
async def test_latepost_latest_without_headline_still_works(monkeypatch):
    async def fake_get(url, **kwargs):
        return RequestResult(False, _UPDATE_TIME, "<html><body>没有头条区块</body></html>")

    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        if "/site/index" in url:
            return _latepost_result([{"id": "3744", "title": "只有列表", "detail_url": "/news/dj_detail?id=3744"}])
        return _latepost_result([{"id": "3744", "title": "", "release_time": "09月23日"}])

    monkeypatch.setattr(infzm_latepost, "get", fake_get)
    monkeypatch.setattr(infzm_latepost, "post", fake_post)
    result = await infzm_latepost.handle_route(_request("latepost-latest"), no_cache=True)
    assert result.message == "首页列表（本次没有头条）"
    assert result.data[0].id == "3744"
    assert result.data[0].timestamp == _ms("2026-09-23 00:00:00")


@pytest.mark.asyncio
async def test_latepost_error_shell_raises(monkeypatch):
    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, {"data": {"code": "0", "data": None}})

    monkeypatch.setattr(infzm_latepost, "post", fake_post)
    with pytest.raises(RuntimeError, match="code=0"):
        await infzm_latepost.handle_route(_request("latepost-longform"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_board_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await infzm_latepost.handle_route(_request("nosuch"), no_cache=True)

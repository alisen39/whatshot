"""invest-community-research 路由测试：mock 共享 get，fixtures 从 board_api 证据净化。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import invest_community_research as route
from whats_hot_api.utils.http_client import RequestResult

_CHINA_TZ = timezone(timedelta(hours=8))
_UPDATE_TIME = "2026-09-30T00:00:00+00:00"


def _request(board_type: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/invest-community-research",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )


# ---------------------------------------------------------------- 雪球


@pytest.mark.asyncio
async def test_xueqiu_visits_home_first_then_api_with_category_zero(monkeypatch):
    calls: list[dict] = []

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        calls.append({"url": url, "headers": headers, "params": params, "no_cache": no_cache, **kwargs})
        if url == "https://www.xueqiu.com/":
            return RequestResult(False, _UPDATE_TIME, "<html>首页</html>")
        detail = {
            "id": 410667656,
            "target": "/1516479974/410667656",
            "topic_title": "当下养殖业环境与2023年的比较",
            "view_count": 133778,
            "created_at": 1790496834000,
            "topic_pic": "https://xqimg.imedao.com/a.png!800.jpg",
            "description": "<br/>结合各种草根数据……",
            "user": {"screen_name": "HindSight后视镜"},
        }
        return RequestResult(False, _UPDATE_TIME, {"list": [{"data": json.dumps(detail)}]})

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("xueqiu-today"), no_cache=True)

    # 第 1 步 GET 首页领访客 cookie（不带 xq_a_token 接口 400 error_code=400016），且不读缓存
    assert calls[0]["url"] == "https://www.xueqiu.com/"
    assert calls[0]["no_cache"] is True
    assert calls[0]["response_type"] == "text"
    # 第 2 步是「今日话题」组件的请求（category=0 =「全部」tab；不是 /today 页的 listV2 热帖流）
    api_call = calls[1]
    assert api_call["url"] == "https://www.xueqiu.com/v4/statuses/public_timeline_by_category.json"
    assert api_call["params"] == {"since_id": "-1", "max_id": "-1", "category": "0"}
    assert api_call["headers"]["Referer"] == "https://xueqiu.com/today"

    item = result.data[0]
    assert item.id == "410667656"
    assert item.title == "当下养殖业环境与2023年的比较"
    assert item.url == "https://xueqiu.com/1516479974/410667656"
    assert item.hot == 133778
    assert item.author == "HindSight后视镜"
    assert item.cover == "https://xqimg.imedao.com/a.png!800.jpg"
    assert item.desc == "结合各种草根数据……"  # 富文本去标签
    assert item.timestamp == 1790496834000  # 上游毫秒原样


@pytest.mark.asyncio
async def test_xueqiu_title_falls_back_to_plain_description(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        if url == "https://www.xueqiu.com/":
            return RequestResult(False, _UPDATE_TIME, "<html>首页</html>")
        detail = {"id": 7, "target": "/u/7", "title": "", "description": "第一段<br/>第二段"}
        return RequestResult(False, _UPDATE_TIME, {"list": [{"data": json.dumps(detail)}]})

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("xueqiu-today"), no_cache=True)
    assert result.data[0].title == "第一段 第二段"
    assert result.data[0].timestamp is None  # 无 created_at 留空，不猜


@pytest.mark.asyncio
async def test_xueqiu_missing_list_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        if url == "https://www.xueqiu.com/":
            return RequestResult(False, _UPDATE_TIME, "<html>首页</html>")
        return RequestResult(False, _UPDATE_TIME, {"error_code": 400016, "error_description": "授权失败"})

    monkeypatch.setattr(route, "get", fake_get)
    with pytest.raises(RuntimeError, match="has no list"):
        await route.handle_route(_request("xueqiu-today"), no_cache=True)


# ---------------------------------------------------------------- 集思录


def _jsl_page(*items: str) -> str:
    body = "".join(f'<div class="aw-item">{item}</div>' for item in items)
    return f"<html><body><div class='aw-question-list'>{body}</div></body></html>"


_JSL_POSTED = """
<h4><a target="_blank" href="https://www.jisilu.cn/question/525642">2026-9-30 可转债 调仓</a></h4>
<span class="aw-text-color-999">
  <span class="aw-question-tags"><a href="https://www.jisilu.cn/category/4">债券/可转债</a></span>
  • <a href="https://www.jisilu.cn/people/linqiu" class="aw-user-name">linqiu</a> 发起 • 2026-09-30 09:30 • 1778 次浏览
</span>
"""

_JSL_REPLIED = """
<h4><a target="_blank" href="/question/525634">波斯湾产油国出口原油达到战前80%</a>
<a href="https://www.jisilu.cn/topic/xxx">话题标签</a></h4>
<span class="aw-text-color-999">
  <a href="https://www.jisilu.cn/people/wswddb" class="aw-user-name">wswddb</a> 回复 • 2026-09-30 17:48 • 1777 次浏览
</span>
"""


@pytest.mark.asyncio
async def test_jisilu_latest_parses_items_and_reply_rows_stay_blank(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://www.jisilu.cn/home/explore/category-__sort_type-add_time"
        return RequestResult(False, _UPDATE_TIME, _jsl_page(_JSL_POSTED, _JSL_REPLIED))

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("jisilu-latest"), no_cache=True)

    posted, replied = result.data[0], result.data[1]
    assert posted.id == "525642"
    assert posted.title == "2026-9-30 可转债 调仓"
    assert posted.author == "linqiu"
    assert posted.hot == 1778
    assert posted.timestamp == int(datetime(2026, 9, 30, 9, 30, tzinfo=_CHINA_TZ).timestamp()) * 1000
    # 「回复」行的时间与人是最后回复信息，不是发布时间：author/timestamp 留空
    assert replied.id == "525634"
    assert replied.url == "https://www.jisilu.cn/question/525634"  # 只取问题链接，不取话题标签
    assert replied.author is None
    assert replied.timestamp is None
    assert replied.hot == 1777


@pytest.mark.asyncio
async def test_jisilu_hot_today_allows_empty_but_broken_page_is_error(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://www.jisilu.cn/home/explore/sort_type-hot____day-1"
        return RequestResult(False, _UPDATE_TIME, _jsl_page())

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("jisilu-hot-today"), no_cache=True)
    assert result.data == []
    assert "当天" in (result.message or "")

    async def fake_get_broken(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, "<html><body>请稍候...</body></html>")

    monkeypatch.setattr(route, "get", fake_get_broken)
    with pytest.raises(RuntimeError, match="aw-question-list"):
        await route.handle_route(_request("jisilu-hot-today"), no_cache=True)


# ---------------------------------------------------------------- 艾瑞咨询


@pytest.mark.asyncio
async def test_iresearch_latest_uses_page_query_and_maps_fields(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "params": params})
        return RequestResult(
            False,
            _UPDATE_TIME,
            {
                "Status": "success",
                "List": [
                    {
                        "NewsId": 4869,
                        "Title": "Hedge Resilience Index（HRI）White Paper",
                        "views": 5980,
                        "SmallImg": "https://pic.iresearch.cn/news/202609/a.png",
                        "Author": "艾瑞咨询",
                        "Content": "<p>报告摘要<b>加粗</b></p>",
                        "Uptime": "2026/09/16 10:00:00",
                    }
                ],
            },
        )

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("iresearch-latest"), no_cache=True)

    assert captured["url"] == "https://www.iresearch.com.cn/api/products/GetReportList"
    # 页面 reportObj.query 初值；fee=0 必需（去掉 GetReportList 返回 0 条）
    assert captured["params"] == {"classId": "", "fee": "0", "date": "", "lastId": "", "pageSize": "12"}
    item = result.data[0]
    assert item.id == "4869"
    assert item.url == "https://www.iresearch.com.cn/Detail/report?id=4869&isfree=0"  # 页面卡片链接
    assert item.hot == 5980
    assert item.cover == "https://pic.iresearch.cn/news/202609/a.png"
    assert item.author == "艾瑞咨询"
    assert item.desc == "报告摘要 加粗"
    assert item.timestamp == int(datetime(2026, 9, 16, 10, 0, 0, tzinfo=_CHINA_TZ).timestamp()) * 1000


@pytest.mark.asyncio
async def test_iresearch_error_shell_is_rejected(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, {"Status": "fail", "Msg": "error"})

    monkeypatch.setattr(route, "get", fake_get)
    with pytest.raises(RuntimeError, match="non-success envelope"):
        await route.handle_route(_request("iresearch-hot"), no_cache=True)


# ---------------------------------------------------------------- QuestMobile


@pytest.mark.asyncio
async def test_questmobile_requires_code_100200_and_maps_fields(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "params": params})
        return RequestResult(
            False,
            _UPDATE_TIME,
            {
                "code": 100200,
                "data": [
                    {
                        "id": "2102284518631264258",
                        "title": "QuestMobile 2026四大核心地区数字生活研究报告",
                        "introduction": "QuestMobile数据显示……",
                        "coverImgUrl": "https://ws.questmobile.cn/report/article/images/a.jpg",
                        "publishTime": "2026-09-22",
                    }
                ],
            },
        )

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("questmobile-reports"), no_cache=True)

    # 与页面 SSR（QuestMobile-state）同参数
    assert captured["params"] == {"version": "0", "pageSize": "6", "pageNo": "1", "industryId": "-1", "labelId": "-1"}
    item = result.data[0]
    assert item.id == "2102284518631264258"
    assert item.url == "https://www.questmobile.com.cn/research/report/2102284518631264258"
    assert item.cover == "https://ws.questmobile.cn/report/article/images/a.jpg"
    assert item.timestamp == int(datetime(2026, 9, 22, tzinfo=_CHINA_TZ).timestamp()) * 1000

    async def fake_get_error(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, {"code": 500, "msg": "server error"})

    monkeypatch.setattr(route, "get", fake_get_error)
    with pytest.raises(RuntimeError, match="code=500"):
        await route.handle_route(_request("questmobile-reports"), no_cache=True)


# ---------------------------------------------------------------- Counterpoint


def _cp_card(href: str, title: str, date_text: str, image_url: str) -> str:
    return (
        f'<a class="block h-full" href="{href}"><article>'
        f'<img alt="t" src="/_next/image?url={image_url}&amp;w=3840&amp;q=75">'
        f"<p>{date_text}</p><h3>{title}</h3></article></a>"
    )


@pytest.mark.asyncio
async def test_counterpoint_parses_cards_and_skips_nav_links(monkeypatch):
    page = (
        "<html><body>"
        + _cp_card("/cn/insights/global-foldable-2026h2", "折叠屏报告", "2026年9月30日", "https%3A%2F%2Fstatic.counterpointresearch.com%2Fa.png")
        + _cp_card("/cn/insights/the-autonomous-driving-paradox", "自动驾驶悖论", "2026年9月3日", "https%3A%2F%2Fstatic.counterpointresearch.com%2Fb.png")
        # 导航/筛选里的链接没有 article/h3，不算条目
        + '<a href="/cn/insights?searchKeyword=Data&amp;category=data"><div>Data</div></a>'
        "</body></html>"
    )

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://counterpointresearch.com/cn/insights"
        return RequestResult(False, _UPDATE_TIME, page)

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("counterpoint-insights"), no_cache=True)

    first = result.data[0]
    assert first.id == "global-foldable-2026h2"  # 链接里的英文 slug
    assert first.url == "https://counterpointresearch.com/cn/insights/global-foldable-2026h2"
    assert first.cover == "https://static.counterpointresearch.com/a.png"  # /_next/image?url= 的原图
    assert first.timestamp == int(datetime(2026, 9, 30, tzinfo=_CHINA_TZ).timestamp()) * 1000
    assert len(result.data) == 2


# ---------------------------------------------------------------- 入口


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board 'nope'"):
        await route.handle_route(_request("nope"), no_cache=True)


def test_type_map_declares_all_boards():
    assert len(route._TYPE_MAP) == 7
    assert next(iter(route._TYPE_MAP)) == "xueqiu-today"  # 声明序第一个是默认榜

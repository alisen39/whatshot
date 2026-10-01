"""cctv-programs 路由测试：mock 共享 get，fixtures 从 board_api 证据净化。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import cctv_programs as route
from whats_hot_api.utils.http_client import RequestResult

_CHINA_TZ = timezone(timedelta(hours=8))
_UPDATE_TIME = "2026-09-28T00:00:00+00:00"


def _request(board_type: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/cctv-programs",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )


def _video_row(**overrides) -> dict:
    row = {
        "id": "VIDEQmiEum7pjn7ybpUoO6SF260924",
        "title": "《今日说法》 20260924 警惕\u201c偶像签名\u201d陷阱",
        "url": "https://tv.cctv.com/2026/09/24/VIDEQmiEum7pjn7ybpUoO6SF260924.shtml",
        "image": "//p4.img.cctvpic.com/fmspic/2026/09/24/50cf2c90-1.jpg",
        "brief": "本期节目主要内容：\n    崇敬偶像、追逐美好本就是青春期孩子十分正常的心理。",
        "time": "2026-09-24 12:38:00",
        "focus_date": 1790227378842,
        "guid": "50cf2c9060d24e75ade3db47b0fe3894",
    }
    row.update(overrides)
    return row


def _news_row(item_id: str, title: str, focus: str, **overrides) -> dict:
    row = {
        "id": item_id,
        "title": title,
        "url": f"https://news.cctv.com/2026/09/28/{item_id}.shtml",
        "image": "https://p3.img.cctvpic.com/photoworkspace/2026/09/28/a.jpg",
        "brief": "秋粮约占全年粮食产量的四分之三。",
        "focus_date": focus,
    }
    row.update(overrides)
    return row


_NEWS_PAGE_HTML = """
<div class="xinwen18886_ind01">
  <div class="list_con" id="slide">
    <div class="silde cur" dataurl="https://news.cctv.com/2026/09/28/ARTIhead00000000000001.shtml">
      <div class="image"><a href="#"><img class="lazy" src="//p2.img.cctvpic.com/templet.png"
        data-echo="//p3.img.cctvpic.com/photoworkspace/2026/09/28/head.jpg"></a></div>
      <div class="right_text"><h3><a href="#">全国秋粮收获已近两成 部分区域迎降雨</a></h3>
      <p><a href="#">秋粮约占全年粮食产量的四分之三。</a></p></div>
    </div>
  </div>
</div>
"""

_NBA_PAGE_HTML = """
<div id="zhiding"><script>var obj_data = [{dataUrl: 'https://sports.cctv.com/2026/09/28/ARTIpinned0000001.shtml',
dataTitle: '置\\'顶条目', dataImg: '//p1.img.cctvpic.com/pin.jpg'}];</script></div>
"""


def _fake_get(calls: list, handlers: dict) -> object:
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        calls.append({"url": url, "params": params, "headers": headers, "no_cache": no_cache, "kwargs": kwargs})
        for needle, payload in handlers.items():
            if needle in url:
                if isinstance(payload, str):
                    return RequestResult(False, _UPDATE_TIME, payload)
                return RequestResult(False, _UPDATE_TIME, payload)
        raise AssertionError(f"unexpected url {url}")

    return fake_get


# ---------------------------------------------------------------- 电视节目


@pytest.mark.asyncio
async def test_program_maps_fields_and_params(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        route,
        "get",
        _fake_get(calls, {"getVideoListByColumn": {"data": {"total": 1000, "list": [_video_row()]}}}),
    )
    result = await route.handle_route(_request("tv-jrsf"), no_cache=True)

    call = calls[0]
    assert call["url"] == "https://api.cntv.cn/NewVideo/getVideoListByColumn"
    assert call["params"]["id"] == "TOPC1451464665008914"  # 今日说法用 lmtopId，不是注释里的百家讲坛 id
    assert call["params"]["mode"] == 0
    assert call["params"]["n"] == 20
    assert call["params"]["serviceId"] == "tvcctv"  # 缺了返回 errcode=1105
    assert call["params"]["sort"] == "desc"
    assert call["no_cache"] is True
    item = result.data[0]
    assert item.id == "VIDEQmiEum7pjn7ybpUoO6SF260924"
    assert item.title == "《今日说法》 20260924 警惕“偶像签名”陷阱"  # 空白已合并
    assert item.url == "https://tv.cctv.com/2026/09/24/VIDEQmiEum7pjn7ybpUoO6SF260924.shtml"
    assert item.mobileUrl == item.url
    assert item.cover == "https://p4.img.cctvpic.com/fmspic/2026/09/24/50cf2c90-1.jpg"  # // 补 https:
    assert item.desc == "本期节目主要内容： 崇敬偶像、追逐美好本就是青春期孩子十分正常的心理。"
    expected = int(datetime(2026, 9, 24, 12, 38, 0, tzinfo=_CHINA_TZ).timestamp()) * 1000
    assert item.timestamp == expected  # 播出时间（北京时间）→ 毫秒
    assert result.total == 1
    assert result.type == "今日说法"
    assert result.link == "https://tv.cctv.com/lm/jrsf/"


@pytest.mark.asyncio
async def test_program_mode_and_n_follow_column_page_defaults(monkeypatch):
    """每周质量报告只有"全部视频"一栏（mode=2）；经济半小时取"往期节目"（n=10）。"""
    calls: list = []
    handlers = {
        "TOPC1451558650605123": {"data": {"list": [_video_row(id="VIDEmzzlbg1", mode=2)]}},
        "TOPC1451533652476962": {"data": {"list": [_video_row(id="VIDEjjbxs1")]}},
    }

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        calls.append({"params": params})
        for needle, payload in handlers.items():
            if params and needle in params["id"]:
                return RequestResult(False, _UPDATE_TIME, payload)
        raise AssertionError("unexpected params")

    monkeypatch.setattr(route, "get", fake_get)
    await route.handle_route(_request("tv-mzzlbg"), no_cache=False)
    assert calls[0]["params"]["mode"] == 2 and calls[0]["params"]["n"] == 20
    await route.handle_route(_request("tv-jjbxs"), no_cache=False)
    assert calls[1]["params"]["mode"] == 0 and calls[1]["params"]["n"] == 10


@pytest.mark.asyncio
async def test_program_time_missing_falls_back_to_focus_date(monkeypatch):
    monkeypatch.setattr(
        route,
        "get",
        _fake_get([], {"getVideoListByColumn": {"data": {"list": [_video_row(id="VIDEnotime1", time=None)]}}}),
    )
    result = await route.handle_route(_request("tv-jdft"), no_cache=False)
    assert result.data[0].id == "VIDEnotime1"
    assert result.data[0].timestamp == 1790227378842  # focus_date 毫秒原样


@pytest.mark.asyncio
async def test_program_rejects_errcode_shell_and_empty_list(monkeypatch):
    monkeypatch.setattr(
        route, "get", _fake_get([], {"getVideoListByColumn": {"errcode": "1105", "msg": "无效服务"}})
    )
    with pytest.raises(RuntimeError, match="1105"):
        await route.handle_route(_request("tv-jrsf"), no_cache=False)

    monkeypatch.setattr(
        route, "get", _fake_get([], {"getVideoListByColumn": {"data": {"total": 0, "list": []}}})
    )
    with pytest.raises(RuntimeError, match="no items"):
        await route.handle_route(_request("tv-jrsf"), no_cache=False)


# ---------------------------------------------------------------- 新闻频道


@pytest.mark.asyncio
async def test_news_head_slide_joins_list_and_dedupes(monkeypatch):
    calls: list = []
    rows = [
        # 头图条目也在列表里：用列表里的完整字段，且只出现一次、在第一位
        _news_row("ARTIhead00000000000001", "全国秋粮收获已近两成 部分区域迎降雨", "2026-09-28 04:30:00"),
        _news_row("ARTIsecond0000000000002", "第二条新闻", "2026-09-28 03:10:00"),
    ]
    monkeypatch.setattr(
        route,
        "get",
        _fake_get(
            calls,
            {
                "news.cctv.com/china/": _NEWS_PAGE_HTML,
                "china_1.jsonp": 'china({"data":{"total":500,"list":['
                + ",".join(__import__("json").dumps(r, ensure_ascii=False) for r in rows)
                + ']}})',
            },
        ),
    )
    result = await route.handle_route(_request("news-china"), no_cache=True)

    assert [c["url"] for c in calls] == [
        "https://news.cctv.com/china/",
        "https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/china_1.jsonp",
    ]
    assert calls[0]["kwargs"]["response_type"] == "text"  # 页面按文本取
    assert len(result.data) == 2  # 头图去重后不重复
    first = result.data[0]
    assert first.id == "ARTIhead00000000000001"
    assert first.title == "全国秋粮收获已近两成 部分区域迎降雨"  # 列表字段的标题（非头图 h3 文本差异）
    assert first.cover == "https://p3.img.cctvpic.com/photoworkspace/2026/09/28/a.jpg"
    expected = int(datetime(2026, 9, 28, 4, 30, 0, tzinfo=_CHINA_TZ).timestamp()) * 1000
    assert first.timestamp == expected  # focus_date 北京时间 → 毫秒


@pytest.mark.asyncio
async def test_news_slide_not_in_list_keeps_no_timestamp(monkeypatch):
    rows = [_news_row("ARTIsecond0000000000002", "第二条新闻", "2026-09-28 03:10:00")]
    jsonp = 'law({"data":{"total":500,"list":' + __import__("json").dumps(rows, ensure_ascii=False) + "}})"
    monkeypatch.setattr(
        route,
        "get",
        _fake_get([], {"news.cctv.com/law/": _NEWS_PAGE_HTML, "law_1.jsonp": jsonp}),
    )
    result = await route.handle_route(_request("news-law"), no_cache=False)
    assert result.data[0].id == "ARTIhead00000000000001"  # 头图在前
    assert result.data[0].timestamp is None  # 不在列表里的头图没有发布时间，不从链接日期编造
    assert result.data[0].title == "全国秋粮收获已近两成 部分区域迎降雨"
    assert result.data[0].cover == "https://p3.img.cctvpic.com/photoworkspace/2026/09/28/head.jpg"  # data-echo
    assert result.data[1].id == "ARTIsecond0000000000002"
    assert result.total == 2


@pytest.mark.asyncio
async def test_news_rejects_missing_list(monkeypatch):
    monkeypatch.setattr(
        route,
        "get",
        _fake_get([], {"news.cctv.com/world/": _NEWS_PAGE_HTML, "world_1.jsonp": "world({\"data\":{}})"}),
    )
    with pytest.raises(RuntimeError, match="no data.list"):
        await route.handle_route(_request("news-world"), no_cache=False)


# ---------------------------------------------------------------- NBA


@pytest.mark.asyncio
async def test_nba_interleaves_photos_every_four_items(monkeypatch):
    rows = []
    for i in range(9):
        rows.append(_news_row(f"ARTInba{i:014d}", f"NBA 资讯 {i}", "2026-09-28 02:00:00"))
    for i in range(3):
        rows.append(_news_row(f"PHOAnba000000000000{i}", f"图集 {i}", "2026-09-28 02:00:00"))
    monkeypatch.setattr(
        route, "get", _fake_get([], {"sports.cctv.com/nba/": _NBA_PAGE_HTML, "nba_remen_1.jsonp": "nba_remen(" + __import__("json").dumps({"data": {"list": rows}}, ensure_ascii=False) + ")"})
    )
    result = await route.handle_route(_request("sports-nba"), no_cache=False)

    ids = [item.id for item in result.data]
    # 置顶条在最前（zhiding.js obj_data）
    assert ids[0] == "ARTIpinned0000001"
    assert ids[1] == "ARTInba00000000000000"
    # 每 4 条非图集后插 1 个图集：第 6、11 位（0 起：5、10）
    assert ids[5] == "PHOAnba0000000000000"
    assert ids[10] == "PHOAnba0000000000001"
    # zhiding.js 口径:循环结束后剩余图集只在"不止 1 个"时追加——
    # 9 条非图集只触发 2 次插图集,第 3 个图集(P2)被丢弃,最后一条是第 9 条资讯
    assert ids[-1] == "ARTInba00000000000008"
    assert result.data[0].title == "置'顶条目"  # 单引号转义还原
    assert result.total == 12  # 1 置顶 + 9 非图集 + 2 图集(第 3 个按 zhiding.js 丢弃)


# ---------------------------------------------------------------- 入口


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board 'tv-zfj'"):
        await route.handle_route(_request("tv-zfj"), no_cache=False)


def test_type_map_declares_all_boards():
    assert len(route._TYPE_MAP) == 11
    assert next(iter(route._TYPE_MAP)) == "news-china"  # 声明序第一个是默认榜（board_api DEFAULT_TYPE）
    assert route.ROUTE_META["params"]["type"]["type"] is route._TYPE_MAP

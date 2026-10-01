"""business-tech-media 路由测试：mock 共享 get/post，fixtures 从 board_api 证据净化。"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import business_tech_media as route
from whats_hot_api.utils.http_client import RequestResult

_CHINA_TZ = timezone(timedelta(hours=8))
_UPDATE_TIME = "2026-09-28T00:00:00+00:00"


def _request(board_type: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/business-tech-media",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )


def _kr_page(state: dict) -> str:
    return (
        "<!DOCTYPE html><html><head><title>36氪</title></head><body><script>"
        f"window.initialState={json.dumps(state, separators=(',', ':'), ensure_ascii=False)}"
        "</script></body></html>"
    )


def _kr_material_row(item_id: str, title: str, publish_ms: int, **extra) -> dict:
    material = {"itemId": int(item_id), "widgetTitle": title, "publishTime": publish_ms, **extra}
    return {"itemId": int(item_id), "templateMaterial": material}


# ---------------------------------------------------------------- 36氪


@pytest.mark.asyncio
async def test_36kr_home_hotlist_maps_material_fields(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers, "no_cache": no_cache, "kwargs": kwargs})
        state = {
            "homeData": {
                "data": {
                    "hotlist": {
                        "data": [
                            _kr_material_row(
                                "4001348750512260",
                                "刚刚，Gemini 4 Pro全新曝光",
                                1790496759863,
                                widgetImage="https://img.36krcdn.com/a.jpg",
                                authorName="硅星人",
                                summary="实测来了",
                            )
                        ]
                    }
                }
            }
        }
        return RequestResult(False, _UPDATE_TIME, _kr_page(state))

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("36kr-24h"), no_cache=True)

    assert captured["url"] == "https://36kr.com/"
    assert captured["kwargs"]["response_type"] == "text"
    assert captured["no_cache"] is True
    item = result.data[0]
    assert item.id == "4001348750512260"
    assert item.title == "刚刚，Gemini 4 Pro全新曝光"
    assert item.url == "https://www.36kr.com/p/4001348750512260"
    assert item.mobileUrl == "https://m.36kr.com/p/4001348750512260"
    assert item.cover == "https://img.36krcdn.com/a.jpg"
    assert item.author == "硅星人"
    assert item.desc == "实测来了"
    assert item.hot is None  # 首页热榜不显示数值
    assert item.timestamp == 1790496759863  # 上游毫秒原样


@pytest.mark.asyncio
async def test_36kr_zonghe_uses_beijing_date_and_stat_collect(monkeypatch):
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 28, 8, 0, tzinfo=_CHINA_TZ)

    monkeypatch.setattr(route, "datetime", _FixedDatetime)
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured["url"] = url
        state = {
            "hotListDetail": {
                "articleList": {
                    "itemList": [
                        {  # 综合榜条目是扁平的
                            "itemId": 4003891766038402,
                            "widgetTitle": "综合榜文章",
                            "publishTime": 1790555730457,
                            "statCollect": 47,
                        }
                    ]
                }
            }
        }
        return RequestResult(False, _UPDATE_TIME, _kr_page(state))

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("36kr-zonghe"), no_cache=True)

    # 不带日期的 /hot-list/zonghe 是 404，目录页链到北京日期当天的第 1 页
    assert captured["url"] == "https://36kr.com/hot-list/zonghe/2026-09-28/1"
    item = result.data[0]
    assert item.hot == 47  # 页面"N收藏"
    assert item.timestamp == 1790555730457


@pytest.mark.asyncio
async def test_36kr_zonghe_allows_empty_after_midnight(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, _kr_page({"hotListDetail": {"articleList": {"itemList": []}}}))

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("36kr-zonghe"), no_cache=True)
    assert result.data == []
    assert "综合榜为空" in (result.message or "")


@pytest.mark.asyncio
async def test_36kr_home_empty_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        state = {"homeData": {"data": {"hotlist": {"data": []}}}}
        return RequestResult(False, _UPDATE_TIME, _kr_page(state))

    monkeypatch.setattr(route, "get", fake_get)
    with pytest.raises(RuntimeError, match="no items"):
        await route.handle_route(_request("36kr-24h"), no_cache=True)


def _tmt_fake(rows: list[dict], captured: dict):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers, "params": params})
        return RequestResult(False, _UPDATE_TIME, {"result": "ok", "data": rows})

    return fake_get


@pytest.mark.asyncio
async def test_tmtpost_hot_requires_duration_and_app_headers(monkeypatch):
    captured: dict = {}
    rows = [
        {
            "post_guid": "8152285",
            "guid": None,
            "title": "对话高通中国区董事长孟樸：AI正在形成闭环",
            "short_url": "https://www.tmtpost.com/8152285.html",
            "time_published": "1790300216",
        }
    ]
    monkeypatch.setattr(route, "get", _tmt_fake(rows, captured))
    result = await route.handle_route(_request("tmtpost-hot"), no_cache=True)

    assert captured["url"] == "https://api.tmtpost.com/v1/posts/list/hot"
    assert captured["params"]["duration"] == 259200  # 不带返回 2014 年旧文章
    assert captured["params"]["limit"] == 20  # /hot 完整榜单页首屏
    assert captured["headers"]["app-version"] == "web1.0"  # 缺了 406 miss app_version header
    auth = captured["headers"]["Authorization"]
    assert re.fullmatch(r'"13:\d{13}\|44:[0-9a-f]{32}[a-z0-9]{12}"', auth), auth  # 两端带双引号
    item = result.data[0]
    assert item.id == "8152285"
    assert item.timestamp == 1790300216000  # 上游秒 → 毫秒


@pytest.mark.asyncio
async def test_tmtpost_business_error_shell_is_rejected(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, {"result": "error", "errors": [{"message": "miss"}]})

    monkeypatch.setattr(route, "get", fake_get)
    with pytest.raises(RuntimeError, match="non-ok envelope"):
        await route.handle_route(_request("tmtpost-hot"), no_cache=True)


@pytest.mark.asyncio
async def test_tmtpost_nictation_expands_power_pos_and_dedupes(monkeypatch):
    captured: dict = {}
    rows = [
        {  # 第 1 行"PC正能量组"：页面在列表最上方滚动展示的两条重要快报
            "item_type": "pc_power_pos",
            "items": [
                {"item_type": "word", "guid": "8150785", "title": "置顶快报一", "share_link": "https://www.tmtpost.com/nictation/8150785.html", "detail": "d1", "time_published": "1790555840", "author_name": "钛媒体"},
                {"item_type": "word", "guid": "8149938", "title": "置顶快报二", "share_link": "https://www.tmtpost.com/nictation/8149938.html", "detail": "", "time_published": None, "author_name": "钛媒体"},
            ],
        },
        {"item_type": "word", "guid": "8150785", "title": "置顶快报一（重复）", "share_link": "https://www.tmtpost.com/nictation/8150785.html", "detail": "dup", "time_published": "1790555840"},  # 与置顶重复
        {"item_type": "word", "guid": "8153660", "title": "普通快报", "share_link": "https://www.tmtpost.com/nictation/8153660.html", "detail": "d2", "time_published": "1790555840"},
    ]
    monkeypatch.setattr(route, "get", _tmt_fake(rows, captured))
    result = await route.handle_route(_request("tmtpost-nictation"), no_cache=True)

    assert [item.id for item in result.data] == ["8150785", "8149938", "8153660"]  # 置顶在前 + guid 去重
    assert result.data[0].author == "钛媒体"
    assert result.data[1].desc is None  # 空 detail → None
    assert captured["url"].endswith("/v1/lists/word_paid_special_column_post")


@pytest.mark.asyncio
async def test_tmtpost_new_builds_links_per_item_type(monkeypatch):
    captured: dict = {}
    rows = [
        {"item_type": "post", "guid": "8153611", "title": "Edge AI Daily 早报", "short_url": "https://www.tmtpost.com/8153611.html", "time_published": "1790554564", "summary": "s", "thumb_image": {"448_252": [{"url": "https://images.tmtpost.com/a.png"}]}, "authors": [{"username": "Edge AI Daily"}, {"username": "钛媒体"}]},
        {"item_type": "fm_audios", "guid": "8153602", "title": "音频节目", "short_url": None, "time_published": "1790554564", "authors": []},
        {"item_type": "video_article", "guid": "8153448", "title": "视频", "short_url": None, "time_published": "1790554564", "authors": []},
    ]
    monkeypatch.setattr(route, "get", _tmt_fake(rows, captured))
    result = await route.handle_route(_request("tmtpost-new"), no_cache=True)

    assert captured["params"]["subtype"] == "post;atlas;video_article;fm_audios;"  # 不带只返回文章
    assert result.data[0].url == "https://www.tmtpost.com/8153611.html"
    assert result.data[0].author == "Edge AI Daily、钛媒体"
    assert result.data[0].cover == "https://images.tmtpost.com/a.png"
    assert result.data[1].url == "https://www.tmtpost.com/fm/8153602.html"
    assert result.data[2].url == "https://www.tmtpost.com/video/8153448.html"


# ---------------------------------------------------------------- 华尔街见闻


@pytest.mark.asyncio
async def test_wallstreetcn_week_uses_week_items_not_day_items(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "params": params, "headers": headers})
        return RequestResult(
            False,
            _UPDATE_TIME,
            {
                "code": 20000,
                "data": {
                    "day_items": [{"id": 1, "title": "日榜条目", "uri": "https://wallstreetcn.com/articles/1", "pageviews": 10, "display_time": 1790409724}],
                    "week_items": [
                        {
                            "id": 3782582,
                            "title": "中美达成八点成果共识",
                            "uri": "https://wallstreetcn.com/articles/3782582",
                            "pageviews": 255384,
                            "display_time": 1790409724,
                            "content_short": None,
                            "author": None,
                            "image": None,
                        }
                    ],
                },
            },
        )

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("wallstreetcn-week"), no_cache=True)

    assert captured["url"] == "https://api-one.wallstcn.com/apiv1/content/articles/hot"
    assert captured["params"] == {"period": "all"}
    assert result.data[0].id == "3782582"  # week_items，不是 PC 组件展示的 day_items
    assert result.data[0].hot == 255384
    assert result.data[0].timestamp == 1790409724000


@pytest.mark.asyncio
async def test_wallstreetcn_breakfast_keeps_articles_only(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        payload = {
            "code": 20000,
            "data": {
                "items": [
                    {"resource_type": "article", "resource": {"id": 3782609, "title": "早餐FM", "uri": "https://wallstreetcn.com/articles/3782609", "display_time": 1790551229, "content_short": "摘要", "author": {"display_name": "乐鸣"}, "image": {"uri": "https://wpimg-wscn.awtmt.com/x.jpg"}}},
                    {"resource_type": "ad", "resource": {"id": 999, "title": "广告位"}},  # 页面插入的广告不算条目
                ]
            },
        }
        return RequestResult(False, _UPDATE_TIME, payload)

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("wallstreetcn-breakfast"), no_cache=True)
    assert len(result.data) == 1
    item = result.data[0]
    assert item.id == "3782609"
    assert item.author == "乐鸣"
    assert item.cover == "https://wpimg-wscn.awtmt.com/x.jpg"

    async def fake_get_error(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, {"code": 40000, "message": "bad"})

    monkeypatch.setattr(route, "get", fake_get_error)
    with pytest.raises(RuntimeError, match="non-20000"):
        await route.handle_route(_request("wallstreetcn-breakfast"), no_cache=True)


# ---------------------------------------------------------------- 财富中文网

_FC_HEAD = """
<div class="s1-box">
  <div class="pic"><a href="c/2026-09/28/content_477038.htm"><img src="https://images1.caifuzhongwen.com/a.jpg"></a></div>
  <div class="text-mod big"><a href="">
    <h2><a href="c/2026-09/28/content_477038.htm">美国企业AI转型速度缓慢</a></h2>
    <p>如果企业迟迟不能认清AI的深远影响</p>
  </a>
  <div class="info"><a class="author" href="">Ryan McManus</a><div class="date">2026-09-28</div></div></div>
</div>
"""

_FC_LI_TEMPLATE = """
<ul class="news-list">
  <li class="news-item"><div class="news-item-inner">
    <div class="pic"><a href="c/{date_dir}/content_477037.htm"><img src="https://images1.caifuzhongwen.com/b.jpg"></a></div>
    <div class="text-mod"><h2><a href="c/{date_dir}/content_477037.htm">专家认为，AI可破解绿色能源产能过剩问题</a></h2>
    <div class="info"><a class="author">Angelica Ang</a><div class="date">{date_text}</div></div></div>
  </div></li>
</ul>
"""


def _fc_page(li_html: str) -> str:
    return f"<html><body><div class='page-left'>{_FC_HEAD}{li_html}</div></body></html>"


@pytest.mark.asyncio
async def test_fortunechina_shangye_parses_head_and_news_items(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://www.fortunechina.com/shangye/"
        return RequestResult(False, _UPDATE_TIME, _fc_page(_FC_LI_TEMPLATE.format(date_dir="2026-09/28", date_text="2026-09-28")))

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("fortunechina-shangye"), no_cache=True)

    expected_midnight = int(datetime(2026, 9, 28, tzinfo=_CHINA_TZ).timestamp()) * 1000
    head, second = result.data[0], result.data[1]
    assert head.id == "477038"
    assert head.url == "https://www.fortunechina.com/shangye/c/2026-09/28/content_477038.htm"
    assert head.title == "美国企业AI转型速度缓慢"
    assert head.author == "Ryan McManus"
    assert head.desc == "如果企业迟迟不能认清AI的深远影响"
    assert head.cover == "https://images1.caifuzhongwen.com/a.jpg"
    assert head.timestamp == expected_midnight  # 页面日期 → 北京时间 0 点
    assert second.id == "477037"


@pytest.mark.asyncio
async def test_fortunechina_latest_falls_back_to_url_date_for_relative_time(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://www.fortunechina.com/"
        # 首页较新条目显示"11分钟前"这类相对时间，取链接里的 /c/YYYY-MM/DD/ 日期兜底
        return RequestResult(False, _UPDATE_TIME, _fc_page(_FC_LI_TEMPLATE.format(date_dir="2026-09/30", date_text="11分钟前")))

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("fortunechina-latest"), no_cache=True)
    expected = int(datetime(2026, 9, 30, tzinfo=_CHINA_TZ).timestamp()) * 1000
    assert result.data[1].timestamp == expected

    async def fake_get_broken(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, "<html><body>改版了</body></html>")

    monkeypatch.setattr(route, "get", fake_get_broken)
    with pytest.raises(RuntimeError, match="no news items"):
        await route.handle_route(_request("fortunechina-latest"), no_cache=True)


# ---------------------------------------------------------------- 虎嗅


def _huxiu_fake(payload: dict, captured: dict, headers: dict | None = None):
    async def fake_post(url, headers=None, body=None, no_cache=None, origin_info=None, **kwargs):
        captured.update({"url": url, "headers": headers, "body": body, "origin_info": origin_info})
        if origin_info:
            wrapped_headers = {"date": "Wed, 30 Sep 2026 15:34:31 GMT"}
            return RequestResult(False, _UPDATE_TIME, {"data": payload, "status": 200, "headers": wrapped_headers})
        return RequestResult(False, _UPDATE_TIME, payload)

    return fake_post


@pytest.mark.asyncio
async def test_huxiu_latest_posts_form_with_platform_www(monkeypatch):
    captured: dict = {}
    payload = {
        "success": True,
        "data": {
            "datalist": [
                {"aid": 4894179, "title": "小鹏没有产品经理", "url": "https://www.huxiu.com/article/4894179.html", "dateline": 1790555700, "pic_path": "https://img.huxiucdn.com/a.png", "user_info": {"username": "作者甲"}, "short_content": "摘要"},
                {"aid": 4894175, "title": "默认封面文章", "url": None, "dateline": 1790555700, "pic_path": "https://img.huxiucdn.com/article_default_picpath.png", "user_info": None, "short_content": ""},
            ]
        },
    }
    monkeypatch.setattr(route, "post", _huxiu_fake(payload, captured))
    result = await route.handle_route(_request("huxiu-latest"), no_cache=True)

    assert captured["url"] == "https://api-ms-article.huxiu.com/v1/channel/pcArticleList"
    assert "platform=www" in captured["body"]  # 缺了返回"platform类型不正确"
    assert "channel_id=0" in captured["body"]
    assert "pagesize=12" in captured["body"]
    first = result.data[0]
    assert first.id == "4894179"
    assert first.mobileUrl == "https://m.huxiu.com/article/4894179.html"
    assert first.author == "作者甲"
    assert first.timestamp == 1790555700000  # 上游秒 → 毫秒
    assert result.data[1].cover is None  # 默认占位图不作为封面


@pytest.mark.asyncio
async def test_huxiu_brief_relative_time_uses_response_date_header(monkeypatch):
    captured: dict = {}
    payload = {
        "success": True,
        "data": {
            "datalist": [
                {"brief_id": 293230, "title": "早报标题", "url": "https://www.huxiu.com/brief/293230.html", "format_publish_time": "48分钟前", "publish_time": None, "dateline": None},
                {"brief_id": 293225, "title": "绝对时间早报", "url": None, "format_publish_time": "2026-09-24", "publish_time": None, "dateline": None},
            ]
        },
    }
    monkeypatch.setattr(route, "post", _huxiu_fake(payload, captured))
    result = await route.handle_route(_request("huxiu-brief"), no_cache=True)

    assert captured["origin_info"] is True  # 需要响应 Date 头做相对时间换算基准
    date_header = datetime(2026, 9, 30, 15, 34, 31, tzinfo=UTC).astimezone(_CHINA_TZ)
    expect_relative = int((date_header - timedelta(minutes=48)).timestamp()) * 1000
    assert result.data[0].timestamp == expect_relative
    assert result.data[1].timestamp == int(datetime(2026, 9, 24, tzinfo=_CHINA_TZ).timestamp()) * 1000
    assert result.data[1].url == "https://www.huxiu.com/brief/293225.html"
    assert result.data[1].mobileUrl == "https://m.huxiu.com/brief/293225.html"


@pytest.mark.asyncio
async def test_huxiu_platform_error_is_rejected(monkeypatch):
    captured: dict = {}
    payload = {"error": {"message": "platform类型不正确"}, "success": False}
    monkeypatch.setattr(route, "post", _huxiu_fake(payload, captured))
    with pytest.raises(RuntimeError, match="non-success envelope"):
        await route.handle_route(_request("huxiu-hot"), no_cache=True)


# ---------------------------------------------------------------- 入口


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board 'nope'"):
        await route.handle_route(_request("nope"), no_cache=True)


def test_type_map_declares_all_boards():
    assert len(route._TYPE_MAP) == 17
    assert next(iter(route._TYPE_MAP)) == "36kr-24h"  # 声明序第一个是默认榜
    assert route.ROUTE_META["params"]["type"]["type"] is route._TYPE_MAP

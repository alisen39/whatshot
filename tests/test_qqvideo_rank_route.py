from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import qqvideo_rank
from whats_hot_api.utils.http_client import RequestResult

# 从 evidence/02_channel_3_cartoon.response.body 净化的最小样本：
# 结构保留 div.mod_row_box > .mod_rank_tab 页签 + ul.table_list（第 1 行 item_title 表头 + 条目行），
# a.name 的 href 保留页面里的 HTML 实体写法（&#x3D; 是 =、&amp; 是 &）
_CARTOON_HTML = """
<html><body><div id="app" class="mod_mini_box"><div class="site_container container_main">
<div class="container_inner"><div class="wrapper mod_row_box">
<div class="mod_rank_tab mod_tab_sunmenu"><div class="rank_tab">
<a href="javascipt:void(0);" class="link_nav current">动漫</a></div></div>
<div class="mod_rank_table mod_bd"><ul class="table_list">
<li class="item_list item_title"><span class="item item_a">关键词</span>
<span class="item item_c">搜索热度</span><span class="item item_d">升降趋势</span></li>
<li class="item_list item_odd item_1" key="0"><div class="item item_a"><span class="num">1</span>
<a href="https://v.qq.com/x/search/?q&#x3D;%E4%BB%99%E9%80%86&amp;stag&#x3D;12" class="name"
target="_blank" title="仙逆">仙逆</a></div>
<div class="item item_c"><div class="bar"><span class="bar_inner" style="width:100%;;"></span></div></div></li>
<li class="item_list item_odd item_1" key="1"><div class="item item_a"><span class="num">2</span>
<a href="https://v.qq.com/x/search/?q&#x3D;%E6%96%97%E7%BD%97%E5%A4%A7%E9%99%86&amp;stag&#x3D;12" class="name"
target="_blank" title="斗罗大陆Ⅱ绝世唐门">斗罗大陆Ⅱ绝世唐门</a></div>
<div class="item item_c"><div class="bar"><span class="bar_inner" style="width:63.3%;;"></span></div></div></li>
</ul></div></div></div></div></div></body></html>
"""


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/qqvideo-rank",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
async def test_cartoon_requests_channel_3_page_and_maps_items(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers, "no_cache": no_cache})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _CARTOON_HTML)

    monkeypatch.setattr(qqvideo_rank, "get", fake_get)
    result = await qqvideo_rank.handle_route(_request("cartoon"), no_cache=True)

    # 7 个榜共用 t=hotsearch 的分频道页，只有 channel 不同（动漫 = 3）
    assert captured["url"] == "https://v.qq.com/biu/ranks/?t=hotsearch&channel=3"
    assert captured["no_cache"] is True
    # header_matrix.jsonl：UA 非必需，统一带浏览器 UA
    assert "Mozilla/5.0" in captured["headers"]["User-Agent"]

    assert result.type == "动漫"
    assert result.total == 2
    assert result.fromCache is False
    assert result.updateTime == "2026-10-01T00:00:00+00:00"
    item = result.data[0]
    assert item.id == "仙逆"
    assert item.title == "仙逆"
    # 页面 href 的 HTML 实体要还原成真实链接（与 tophub 条目链接逐字相同）
    assert item.url == "https://v.qq.com/x/search/?q=%E4%BB%99%E9%80%86&stag=12"
    assert item.mobileUrl == item.url
    # 页面只有相对热度条（宽度百分比），不是热度数值，hot/timestamp 留空
    assert item.hot is None
    assert item.timestamp is None
    assert result.data[1].title == "斗罗大陆Ⅱ绝世唐门"


@pytest.mark.asyncio
async def test_hotsearch_is_default_board_and_header_row_is_skipped(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert "channel=0" in url
        return RequestResult(True, "t", _CARTOON_HTML.replace('>动漫<', '>热搜<'))

    monkeypatch.setattr(qqvideo_rank, "get", fake_get)
    result = await qqvideo_rank.handle_route(_request("hotsearch"), no_cache=False)
    assert result.type == "热搜"
    # item_title 表头行（没有 a.name）不计入条目
    assert [item.title for item in result.data] == ["仙逆", "斗罗大陆Ⅱ绝世唐门"]
    assert result.fromCache is True


@pytest.mark.asyncio
async def test_tab_mismatch_is_an_error(monkeypatch):
    """频道 ID 与页签名对不上（页面被改版或频道被挪）要报错，不能静默当别的榜输出。"""

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", _CARTOON_HTML)

    monkeypatch.setattr(qqvideo_rank, "get", fake_get)
    # child 请求拿到的却是"动漫"页签
    with pytest.raises(RuntimeError, match="expected '少儿'"):
        await qqvideo_rank.handle_route(_request("child"), no_cache=True)


@pytest.mark.asyncio
async def test_page_without_tab_or_items_is_an_error(monkeypatch):
    """无效频道 ID 时页面仍 200，但没有页签和列表（evidence/05_channel_999_invalid）；
    有页签但解析不到条目（列表结构变了）同样要报错。"""

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html><body><div id='app'></div></body></html>")

    monkeypatch.setattr(qqvideo_rank, "get", fake_get)
    with pytest.raises(RuntimeError, match="tab is ''"):
        await qqvideo_rank.handle_route(_request("doco"), no_cache=True)

    no_list = (
        '<html><body><div class="wrapper mod_row_box">'
        '<div class="mod_rank_tab"><div class="rank_tab">'
        '<a class="link_nav current">纪录片</a></div></div>'
        '<ul class="table_list"></ul></div></body></html>'
    )

    async def fake_get_empty(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", no_list)

    monkeypatch.setattr(qqvideo_rank, "get", fake_get_empty)
    with pytest.raises(RuntimeError, match="no items"):
        await qqvideo_rank.handle_route(_request("doco"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_type_is_rejected(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        raise AssertionError("unknown type must not hit upstream")

    monkeypatch.setattr(qqvideo_rank, "get", fake_get)
    with pytest.raises(ValueError, match="Unknown board"):
        await qqvideo_rank.handle_route(_request("tech"), no_cache=True)
    # 电视剧（channel=2）是 qqvideo-tv-hotsearch 的榜，不在本路由
    with pytest.raises(ValueError, match="Unknown board"):
        await qqvideo_rank.handle_route(_request("tv"), no_cache=True)


@pytest.mark.asyncio
async def test_duplicate_keywords_keep_first_occurrence(monkeypatch):
    dup = _CARTOON_HTML.replace(
        '<span class="num">2</span>',
        '<span class="num">2</span>',
    ).replace('title="斗罗大陆Ⅱ绝世唐门">斗罗大陆Ⅱ绝世唐门', 'title="仙逆">仙逆')
    dup = dup.replace('q&#x3D;%E6%96%97%E7%BD%97%E5%A4%A7%E9%99%86&amp;stag&#x3D;12',
                      'q&#x3D;%E4%BB%99%E9%80%86&amp;stag&#x3D;12')

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", dup)

    monkeypatch.setattr(qqvideo_rank, "get", fake_get)
    result = await qqvideo_rank.handle_route(_request("cartoon"), no_cache=True)
    assert len(result.data) == 1
    assert result.data[0].url == "https://v.qq.com/x/search/?q=%E4%BB%99%E9%80%86&stag=12"

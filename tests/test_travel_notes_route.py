"""travel-notes 路由测试：mock 共享 get，fixtures 依 board_api 证据结构净化内联。

证据来源：tmp/board_api/travel_notes/evidence/
（01_mfw_pagelet_hot：{data:{html}} 信封与 div.tn-item 结构；02_mfw_pagelet_hot_noreferer：403 空响应；
04_mfw_home：202 + probe.js 挑战页）。
"""

from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import travel_notes as route
from whats_hot_api.utils.http_client import RequestResult

_UPDATE_TIME = "2026-10-01T00:00:00+00:00"


def _request(board_type: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/travel-notes",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )


_FRAGMENT = """
<div id="_j_tn_content"><div class="tn-list">
<div class="tn-item clearfix">
 <div class="tn-image"><a href="/i/24883571.html">
   <img src="https://note.mafengwo.net/img/1b/03/abc.jpeg?imageMogr2%2Fthumbnail"></a></div>
 <div class="tn-wrapper"><dl>
   <dt><a href="/i/24883571.html">最后冲刺！中秋国庆发文有奖#我在马蜂窝写游记...</a></dt>
   <dd><a href="/i/24883571.html">蝉鸣、晚风、看不到尽头的夏天。</a></dd>
 </dl>
 <div class="tn-extra">
   <span class="tn-ding"><em id="topvote24883571">683</em></span>
   <span class="tn-place">北京，by</span>
   <span class="tn-user"><a href="/u/166011.html">蜂蜂甲</a></span>
 </div></div>
</div>
<div class="tn-item clearfix">
 <div class="tn-image"><a href="/i/24904249.html">
   <img data-rt-src="https://note.mafengwo.net/img/xyz.jpg"></a></div>
 <div class="tn-wrapper"><dl>
   <dt><a class="app" href="javascript:;">APP</a><a href="/i/24904249.html">川西小环线自驾全记录</a></dt>
   <dd>三天两夜，翻越折多山。</dd>
 </dl>
 <div class="tn-extra"><span class="tn-ding"><em>212</em></span></div>
</div>
</div>
</div></div>
"""


def _pagelet_response(fragment: str):
    return RequestResult(False, _UPDATE_TIME, json.dumps({"data": {"html": fragment, "css": "", "js": ""}}, ensure_ascii=False))


@pytest.mark.asyncio
async def test_mafengwo_maps_items_and_params(monkeypatch):
    captured: dict = {}
    calls = []

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        calls.append(1)
        captured.update({"url": url, "headers": headers, "params": params, "no_cache": no_cache, "kwargs": kwargs})
        return _pagelet_response(_FRAGMENT)

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("mafengwo-hot"), no_cache=True)

    assert captured["url"] == "https://pagelet.mafengwo.cn/note/pagelet/recommendNoteApi"
    # params 是 JSON 序列化后的 query 值（与页面 pagelet data-params 一致）
    assert json.loads(captured["params"]["params"]) == {"type": 0, "objid": 0, "page": 1, "ajax": 1, "retina": 1}
    assert captured["headers"]["Referer"] == "https://www.mafengwo.cn/"  # 不带或换站都 403 空响应
    assert captured["no_cache"] is True
    first, second = result.data
    assert first.id == "24883571"
    assert first.title == "最后冲刺！中秋国庆发文有奖#我在马蜂窝写游记..."  # 页面截断照页面
    assert first.url == "https://www.mafengwo.cn/i/24883571.html"
    assert first.cover == "https://note.mafengwo.net/img/1b/03/abc.jpeg?imageMogr2%2Fthumbnail"
    assert first.hot == 683  # 「顶」数
    assert first.author == "蜂蜂甲"
    assert first.desc == "蝉鸣、晚风、看不到尽头的夏天。"
    assert first.timestamp is None  # 片段里没有发表时间
    # 第二条：懒加载图取 data-rt-src；"APP" 角标链接不算标题
    assert second.id == "24904249"
    assert second.title == "川西小环线自驾全记录"
    assert second.cover == "https://note.mafengwo.net/img/xyz.jpg"
    assert second.hot == 212
    assert second.author is None


@pytest.mark.asyncio
async def test_mafengwo_probe_challenge_is_rejected(monkeypatch):
    # 首页/pagelet 对程序请求返回 202 + probe.js 挑战页（evidence/04_mfw_home）
    challenge = '<html><head><script src="/C2WF946J0/probe.js"></script></head><body></body></html>'
    monkeypatch.setattr(route, "get", _make_get(challenge))
    with pytest.raises(RuntimeError, match="challenge"):
        await route.handle_route(_request("mafengwo-hot"), no_cache=True)


@pytest.mark.asyncio
async def test_mafengwo_empty_fragment_is_rejected(monkeypatch):
    monkeypatch.setattr(route, "get", _make_get(json.dumps({"data": {"html": "<div></div>"}})))
    with pytest.raises(RuntimeError, match="no items"):
        await route.handle_route(_request("mafengwo-hot"), no_cache=True)


@pytest.mark.asyncio
async def test_mafengwo_non_json_is_rejected(monkeypatch):
    # Referer 不是马蜂窝站内地址时上游返回 403 空响应体（evidence/02_*），反序列化不出 JSON
    monkeypatch.setattr(
        route,
        "get",
        _make_get(""),
    )
    with pytest.raises(RuntimeError, match="did not return JSON"):
        await route.handle_route(_request("mafengwo-hot"), no_cache=True)


def _make_get(body: str):
    async def handler(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, body)

    return handler


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board 'ctrip-you'"):
        await route.handle_route(_request("ctrip-you"), no_cache=True)


def test_type_map_declares_all_boards():
    assert len(route._TYPE_MAP) == 1
    assert next(iter(route._TYPE_MAP)) == "mafengwo-hot"  # 声明序第一个是默认榜
    assert route.ROUTE_META["params"]["type"]["type"] is route._TYPE_MAP

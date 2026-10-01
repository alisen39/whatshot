from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import people_cn
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/people-cn",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


_GB_PAGE = """<html><body><div class="leftItem"><ul>
<li><a href="/n1/2026/0928/c461529-40804001.html">时评标题一</a> <i class="gray">2026-09-28 08:00</i></li>
<li><a href="/n1/2026/0927/c461529-40803999.html">时评标题二</a> <em>2026-09-27</em></li>
<li><a href="/special/index.html">专题入口不算</a></li>
</ul></div></body></html>"""

# 观点频道 gb 页的日期带具体时间;get_time 按本地解析,这里断言非空与单调,不做时区硬编码


@pytest.mark.asyncio
async def test_gb_board_maps_items_with_dates_and_article_ids(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        captured["url"] = url
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _GB_PAGE)

    monkeypatch.setattr(people_cn, "get", fake_get)
    result = await people_cn.handle_route(_request("opinion-rmsp"), no_cache=True)

    assert captured["url"].endswith("/49219/index.html")
    assert result.type == "人民时评"
    assert result.total == 2  # 专题入口被 _links 过滤
    first = result.data[0]
    assert first.id == "40804001"  # 稿件号作 id
    assert first.title == "时评标题一"
    assert first.url == "http://opinion.people.com.cn/n1/2026/0928/c461529-40804001.html"
    assert first.timestamp is not None  # 列表日期
    assert result.data[1].timestamp is not None


_JHSJK_PAYLOAD = {
    "status": "success",
    "list": [
        {"article_id": "40803888", "title": "  讲话  标题 ",
         "newcontent": "  摘要内容  ", "input_date": "2026-09-26 00:00:00"}
    ],
}


@pytest.mark.asyncio
async def test_jhsjk_board_posts_search_form_and_maps_rows(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "params": params})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _JHSJK_PAYLOAD)

    monkeypatch.setattr(people_cn, "get", fake_get)
    result = await people_cn.handle_route(_request("jhsjk-latest"), no_cache=True)

    assert captured["url"] == "https://jhsjk.people.cn/testnew/result"
    assert captured["params"]["source"] == "2"  # 必需;不带返回 HTML 页
    assert captured["params"]["page"] == "1"
    item = result.data[0]
    assert item.id == "40803888"
    assert item.title == "讲话 标题"
    assert item.desc == "摘要内容"
    assert item.url == "https://jhsjk.people.cn/article/40803888"
    assert item.timestamp is not None


@pytest.mark.asyncio
async def test_jhsjk_error_status_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"status": "error", "msg": "bad"})

    monkeypatch.setattr(people_cn, "get", fake_get)
    with pytest.raises(RuntimeError, match="status='error'"):
        await people_cn.handle_route(_request("jhsjk-latest"), no_cache=True)


_WWW_PAGE = """<html><body>
<h2 id="aq_one"><a href="/n1/2026/0928/c401234-40805000.html">文字头条</a></h2>
<ul id="aq_two">
<li><a href="/n1/2026/0928/c401234-40805001.html">要闻一</a></li>
<li><a href="/n1/2026/0928/c401234-40805001.html">要闻一重复</a></li>
</ul></body></html>"""


@pytest.mark.asyncio
async def test_www_yaowen_dedupes_by_url(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _WWW_PAGE)

    monkeypatch.setattr(people_cn, "get", fake_get)
    result = await people_cn.handle_route(_request("www-yaowen"), no_cache=True)

    assert result.total == 2  # 头条 + 去重后的一条
    assert result.data[0].id == "40805000"
    assert result.data[0].timestamp is not None  # 从链接日期取北京时间 0 点


_WWW_IMAGE_HEAD = """<html><body>
<h2 id="aq_one"><a href="/n1/2026/0928/c401234-40806000.html"><img src="/img/head.jpg"></a></h2>
<ul id="aq_two"><li><a href="/n1/2026/0928/c401234-40805001.html">要闻一</a></li></ul></body></html>"""
_HEAD_ARTICLE = "<html><h1>图片头条的真实标题</h1></html>"


@pytest.mark.asyncio
async def test_www_yaowen_image_head_fetches_article_title(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        if url.endswith("40806000.html"):
            return RequestResult(False, "t", _HEAD_ARTICLE)
        return RequestResult(False, "t", _WWW_IMAGE_HEAD)

    monkeypatch.setattr(people_cn, "get", fake_get)
    result = await people_cn.handle_route(_request("www-yaowen"), no_cache=True)

    assert result.data[0].title == "图片头条的真实标题"  # 头条图片无文字,补抓文章页
    assert result.data[0].id == "40806000"


_LIUYAN_PAGE = """<html><body><section class="hot">
<div class="hotTitle"><a href="http://liuyan.people.com.cn/threads/content?tid=22550100">留言标题</a></div>
<div class="hotList"><ul>
<li><a href="/n1/2026/0928/c401234-40807000.html">留言相关报道</a></li>
</ul></div></section></body></html>"""


@pytest.mark.asyncio
async def test_liuyan_uses_tid_as_id(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", _LIUYAN_PAGE)

    monkeypatch.setattr(people_cn, "get", fake_get)
    result = await people_cn.handle_route(_request("liuyan-hot"), no_cache=True)

    assert result.data[0].id == "22550100"  # 留言用 tid 作 id
    assert result.data[1].id == "40807000"


@pytest.mark.asyncio
async def test_empty_parse_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html><body>其它页面</body></html>")

    monkeypatch.setattr(people_cn, "get", fake_get)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await people_cn.handle_route(_request("opinion-rmsp"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await people_cn.handle_route(_request("nonsense"), no_cache=True)

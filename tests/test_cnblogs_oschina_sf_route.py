from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import cnblogs_oschina_sf
from whats_hot_api.utils.http_client import RequestResult

UPDATE_TIME = "2026-10-01T00:00:00+00:00"

# fixtures 按 board_api 证据(evidence/01_cnb_topdiggs、06_cnb_sitehome_rss、
# 10_osc_project_recommend)的结构净化内联,只取字段骨架。

_CNBLOGS_PAGE = """
<div id="post_list">
  <article class="post-item" data-post-id="23054351">
    <section class="post-item-body">
      <div class="post-item-text">
        <a class="post-item-title" href="https://www.cnblogs.com/sdcb/p/23054351/release">SimdPaddleOCR 1.4 发布</a>
        <p class="post-item-summary">纯 C# 写的 SimdPaddleOCR 今天发布 1.4 版本。</p>
      </div>
      <footer class="post-item-foot">
        <a href="https://www.cnblogs.com/sdcb" class="post-item-author"><span>.NET骚操作</span></a>
        <span class="post-meta-item"><span>2026-09-21 08:50</span></span>
        <a class="post-meta-item btn" href="#commentform" title="评论 11"><span>11</span></a>
        <a class="post-meta-item btn" title="推荐 40"><span>40</span></a>
        <a class="post-meta-item btn" title="阅读 1673"><span>1673</span></a>
      </footer>
    </section>
    <figure></figure>
  </article>
</div>
"""

_CNBLOGS_EMPTY_PAGE = """
<html><body><div id="post_list">当前博文列表为空！</div></body></html>
"""

_SITEHOME_ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title type="text">博客园_首页</title>
  <entry>
    <id>https://www.cnblogs.com/xiexj/p/23137129</id>
    <title type="text">Java中不容拒绝的一种优雅的写法 - 编程一生</title>
    <summary type="text">做CodeReview的时候，评价一段代码的好坏通常是仁者见仁。</summary>
    <published>2026-09-27T17:31:00Z</published>
    <updated>2026-09-27T17:31:00Z</updated>
    <author><name>编程一生</name><uri>https://www.cnblogs.com/xiexj/</uri></author>
    <link rel="alternate" href="https://www.cnblogs.com/xiexj/p/23137129" />
  </entry>
</feed>
"""

_OSC_PROJECT_OK = json.dumps(
    {
        "success": True,
        "error": False,
        "message": "操作成功！",
        "code": 200,
        "result": [
            {
                "id": 77427,
                "ident": "shrl-io",
                "name": "shrl.io",
                "title": "自托管 URL 短链接服务",
                "detail": "shrl.io 是一个自托管的 URL 短链接服务。",
                "createTime": "2026-09-03 15:47:18",
                "imgUrl": "https://oscimg.oschina.net/oscnet/up-icon.png",
                "viewCount": 305,
            },
            {"id": 77403, "ident": "", "name": "", "title": "空行没有 ident/name,应跳过"},
        ],
    },
    ensure_ascii=False,
)


def _request(board: str | None = None) -> Request:
    query = f"type={board}" if board else ""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/cnblogs-oschina-sf",
            "query_string": query.encode(),
            "headers": [],
        }
    )


def _fake_get(payload, **expected):
    async def fake_get(**kwargs):
        for key, value in expected.items():
            assert kwargs.get(key) == value, f"expected {key}={value!r}, got {kwargs.get(key)!r}"
        return RequestResult(False, UPDATE_TIME, payload)

    return fake_get


@pytest.mark.asyncio
async def test_default_board_is_sitehome_feed(monkeypatch):
    fake_get = _fake_get(_SITEHOME_ATOM, url="https://feed.cnblogs.com/blog/sitehome/rss")
    monkeypatch.setattr(cnblogs_oschina_sf, "get", fake_get)

    result = await cnblogs_oschina_sf.handle_route(_request(), no_cache=True)

    assert result.name == "cnblogs-oschina-sf"
    assert cnblogs_oschina_sf.DEFAULT_TYPE == "cnblogs-sitehome"
    assert result.title == "博客园"
    assert result.type == "首页推荐"
    assert result.link == "https://www.cnblogs.com/"
    assert result.total == 1
    item = result.data[0]
    assert item.id == "https://www.cnblogs.com/xiexj/p/23137129"
    # Atom 标题带" - 作者",与 tophub 口径一致
    assert item.title == "Java中不容拒绝的一种优雅的写法 - 编程一生"
    assert item.url == "https://www.cnblogs.com/xiexj/p/23137129"
    assert item.author == "编程一生"
    assert item.timestamp == 1790530260000  # published → 毫秒
    assert result.message is None


@pytest.mark.asyncio
async def test_topdiggs_html_maps_fields(monkeypatch):
    fake_get = _fake_get(_CNBLOGS_PAGE, url="https://www.cnblogs.com/aggsite/topdiggs")
    monkeypatch.setattr(cnblogs_oschina_sf, "get", fake_get)

    result = await cnblogs_oschina_sf.handle_route(_request("cnblogs-topdiggs"), no_cache=True)

    assert result.title == "博客园"
    assert result.type == "10天推荐排行"
    item = result.data[0]
    assert item.id == "23054351"  # data-post-id,不是名次
    assert item.title == "SimdPaddleOCR 1.4 发布"
    assert item.url == "https://www.cnblogs.com/sdcb/p/23054351/release"
    assert item.hot == 40  # 推荐排行取"推荐 N"
    assert item.author == ".NET骚操作"
    assert item.desc == "纯 C# 写的 SimdPaddleOCR 今天发布 1.4 版本。"
    assert item.timestamp == 1789951800000  # 北京时间 → 毫秒


@pytest.mark.asyncio
async def test_topviews_picks_read_count(monkeypatch):
    fake_get = _fake_get(_CNBLOGS_PAGE, url="https://www.cnblogs.com/aggsite/topviews")
    monkeypatch.setattr(cnblogs_oschina_sf, "get", fake_get)

    result = await cnblogs_oschina_sf.handle_route(_request("cnblogs-topviews"), no_cache=True)

    assert result.data[0].hot == 1673  # 阅读排行取"阅读 N",不是推荐/评论数


@pytest.mark.asyncio
async def test_cnblogs_empty_marker_is_legal_zero_board(monkeypatch):
    """原站明示"当前博文列表为空!"(48小时评论排行周末常为空)是合法态:0 条 + message。"""
    fake_get = _fake_get(
        _CNBLOGS_EMPTY_PAGE, url="https://www.cnblogs.com/aggsite/topcommented48h"
    )
    monkeypatch.setattr(cnblogs_oschina_sf, "get", fake_get)

    result = await cnblogs_oschina_sf.handle_route(
        _request("cnblogs-topcommented48h"), no_cache=True
    )

    assert result.total == 0
    assert result.data == []
    assert "当前博文列表为空" in (result.message or "")


@pytest.mark.asyncio
async def test_cnblogs_empty_page_without_marker_is_an_error(monkeypatch):
    fake_get = _fake_get("<html><body><div id='post_list'></div></body></html>", url="https://www.cnblogs.com/pick/")
    monkeypatch.setattr(cnblogs_oschina_sf, "get", fake_get)

    with pytest.raises(RuntimeError, match="no post-item"):
        await cnblogs_oschina_sf.handle_route(_request("cnblogs-pick"), no_cache=True)


@pytest.mark.asyncio
async def test_osc_project_query_maps_fields(monkeypatch):
    fake_get = _fake_get(
        json.loads(_OSC_PROJECT_OK),
        url="https://apiv1.oschina.net/oschinapi/project/query",
        params={
            "languageId": "",
            "osId": "",
            "orderBy": "",
            "pageNum": 1,
            "pageSize": 10,
            "onlyRecommend": "true",
        },
    )
    monkeypatch.setattr(cnblogs_oschina_sf, "get", fake_get)

    result = await cnblogs_oschina_sf.handle_route(
        _request("oschina-project-recommend"), no_cache=True
    )

    assert result.link == "https://www.oschina.net/project"
    item = result.data[0]
    assert item.id == "77427"
    # 标题是"软件名 - 一句话介绍"
    assert item.title == "shrl.io - 自托管 URL 短链接服务"
    assert item.url == "https://www.oschina.net/p/shrl-io"
    assert item.hot == 305  # viewCount
    assert item.cover == "https://oscimg.oschina.net/oscnet/up-icon.png"
    assert item.desc == "shrl.io 是一个自托管的 URL 短链接服务。"
    assert item.timestamp == 1788421638000  # createTime 北京时间 → 毫秒


@pytest.mark.asyncio
async def test_osc_project_error_shell_is_rejected(monkeypatch):
    fake_get = _fake_get({"code": 500, "message": "系统繁忙"}, url="https://apiv1.oschina.net/oschinapi/project/query")
    monkeypatch.setattr(cnblogs_oschina_sf, "get", fake_get)

    with pytest.raises(RuntimeError, match="error shell"):
        await cnblogs_oschina_sf.handle_route(
            _request("oschina-project-latest"), no_cache=True
        )


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board 'cnblogs-hot'"):
        await cnblogs_oschina_sf.handle_route(_request("cnblogs-hot"), no_cache=True)


def test_type_map_declares_all_eight_boards():
    assert len(cnblogs_oschina_sf.type_map) == 8
    removed = {"oschina-hot-news", "oschina-latest-info", "oschina-latest-news", "sf-backend", "sf-recommend"}
    assert removed.isdisjoint(cnblogs_oschina_sf.type_map)
    assert next(iter(cnblogs_oschina_sf.type_map)) == "cnblogs-sitehome"

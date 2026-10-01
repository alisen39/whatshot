"""epaper-central 路由测试:mock 共享 get/post,fixtures 按 board_api 证据结构净化内联。"""

from __future__ import annotations

import json
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import _epaper_common as epaper
from whats_hot_api.routes.hotlist import epaper_central
from whats_hot_api.utils.http_client import RequestResult

_UPDATE_TIME = "2026-10-01T00:00:00+00:00"
_TS_0927 = 1790438400000  # 2026-09-27 北京时间 0 点(毫秒)
_TS_0926 = 1790352000000
_TS_0928 = 1790524800000


def _request(board_type: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/epaper-central",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )


def _res(data: Any) -> RequestResult:
    return RequestResult(False, _UPDATE_TIME, data)


def _install_get(monkeypatch, pages: dict[str, Any], calls: list[str] | None = None) -> None:
    """按 URL 前缀路由到固定响应;所有请求都必须带浏览器 UA(header_matrix 证据)。"""

    async def fake_get(url: str, headers=None, no_cache=None, response_type="text", **kwargs):
        if calls is not None:
            calls.append(url)
        assert "Mozilla/5.0" in (headers or {}).get("User-Agent", "")
        for prefix, payload in pages.items():
            if url.startswith(prefix):
                return _res(payload)
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(epaper, "get", fake_get)
    monkeypatch.setattr(epaper, "_MIN_SITE_GAP_SECONDS", 0)


def _install_post(monkeypatch, responses: list[Any], calls: list[dict] | None = None) -> None:
    async def fake_post(url: str, headers=None, body=None, no_cache=None, response_type="json", **kwargs):
        if calls is not None:
            calls.append({"url": url, "headers": headers, "body": body})
        return _res(responses.pop(0))

    monkeypatch.setattr(epaper, "post", fake_post)
    monkeypatch.setattr(epaper, "_MIN_SITE_GAP_SECONDS", 0)


# --------------------------------------------------------------- 系统 A(人民日报)


_A_INDEX = """
<html><body><ul id="list">
<li><a href="202609/27/node_01.html">第01版 要闻</a></li>
<li><a href="202609/27/node_02.html">第02版 理论</a></li>
</ul></body></html>"""

_A_NODE_1 = """
<html><body>
<a href="../../../content/202609/27/content_101.html">标题一</a>
<a href="../../../content/202609/27/content_101.html">标题一重复链接不算</a>
<a href="../../../content/202609/26/content_099.html">上一期链接不算</a>
<a href="../../pic/202609/27/1.jpg">整版图不算</a>
</body></html>"""

_A_NODE_2 = """
<html><body>
<a href="../../../content/202609/27/content_201.html">广告</a>
<a href="../../../content/202609/27/content_202.html">标题二</a>
</body></html>"""


@pytest.mark.asyncio
async def test_fangzheng_a_maps_pages_articles_and_dedupes(monkeypatch):
    calls: list[str] = []
    _install_get(
        monkeypatch,
        {
            "https://paper.people.com.cn/rmrb/pc/layout/index.html": _A_INDEX,
            "https://paper.people.com.cn/rmrb/pc/layout/202609/27/node_01.html": _A_NODE_1,
            "https://paper.people.com.cn/rmrb/pc/layout/202609/27/node_02.html": _A_NODE_2,
        },
        calls,
    )
    result = await epaper_central.handle_route(_request("people-rmrb"), no_cache=True)

    assert calls == [
        "https://paper.people.com.cn/rmrb/pc/layout/index.html",
        "https://paper.people.com.cn/rmrb/pc/layout/202609/27/node_01.html",
        "https://paper.people.com.cn/rmrb/pc/layout/202609/27/node_02.html",
    ]
    assert result.type == "人民日报 · 电子报"
    assert result.name == "epaper-central"
    # 重复链接、上一期(日期目录不符)、无文字链接、"广告"位都不算
    assert result.total == 2
    first, second = result.data
    assert first.title == "标题一"
    assert first.url == "https://paper.people.com.cn/rmrb/pc/content/202609/27/content_101.html"
    assert first.id == first.url  # 电子报条目 id 用文章链接
    assert first.desc == "第01版 要闻"
    assert first.timestamp == _TS_0927
    assert second.desc == "第02版 理论"
    assert second.title == "标题二"
    assert "当期 2026-09-27" in (result.message or "")


# --------------------------------------------------------------- 解放军报(newestPaper + index.json)


_JFJB_NEWEST = {
    "code": 0,
    "data": [
        {"paperName": "中国国防报", "paperData": "2026-09-28"},
        {"paperName": "解放军报", "paperData": "2026-09-27"},
    ],
}
_JFJB_ISSUE = {
    "paperInfo": [
        {
            "paperNumber": "01",
            "paperBk": "要闻",
            "xyList": [
                {"id": 987447, "title": "习近平回到北京"},
                {"id": 987448, "title": "  多空  白  "},
            ],
        },
        {"paperNumber": "02", "paperBk": "评论", "xyList": []},
    ]
}


@pytest.mark.asyncio
async def test_jfjb_maps_json_and_builds_szbxq_urls(monkeypatch):
    calls: list[str] = []
    _install_get(
        monkeypatch,
        {
            "https://rmt-zuul.81.cn/api-paper/api/newestPaper": _JFJB_NEWEST,
            "http://www.81.cn/_szb/jfjb/2026/09/27/index.json": _JFJB_ISSUE,
        },
        calls,
    )
    result = await epaper_central.handle_route(_request("81cn-jfjb"), no_cache=True)

    assert calls == [
        "https://rmt-zuul.81.cn/api-paper/api/newestPaper",
        "http://www.81.cn/_szb/jfjb/2026/09/27/index.json",
    ]
    assert result.type == "解放军报 · 电子报"
    assert result.total == 2  # 空版不产生条目
    first = result.data[0]
    assert first.id == "987447"  # 接口里的文章 id 作 id
    assert (
        first.url
        == "http://www.81.cn/szb_223187/szbxq/index.html"
        "?paperName=jfjb&paperDate=2026-09-27&paperNumber=01&articleid=987447"
    )
    assert first.title == "习近平回到北京"
    assert first.desc == "第01版 要闻"
    assert first.timestamp == _TS_0927
    assert result.data[1].title == "多空 白"


@pytest.mark.asyncio
async def test_jfjb_missing_paper_is_an_error(monkeypatch):
    _install_get(
        monkeypatch,
        {"https://rmt-zuul.81.cn/api-paper/api/newestPaper": {"code": 0, "data": []}},
    )
    with pytest.raises(RuntimeError, match="newestPaper"):
        await epaper_central.handle_route(_request("81cn-jfjb"), no_cache=True)


# --------------------------------------------------------------- 科技日报(uv 接口)


_KJRB_DATE = {"status": 200, "obj": {"dateList": ["2026-09-19", "2026-09-26", "2099-01-01"]}}
_KJRB_EDITIONS = {
    "status": 200,
    "obj": {
        "editionList": [
            {"id": "ed2", "editionName": "第02版：要 闻", "weight": 2, "editionCode": "02"},
            {"id": "ed1", "editionName": "第01版：今日要闻", "weight": 1, "editionCode": "01"},
        ]
    },
}


def _kjrb_articles(edition_id: str) -> dict:
    return {
        "status": 200,
        "list": [
            {"id": f"{edition_id}-a1", "title": "<p>标题甲</p>", "author": "记者一"},
            {"id": f"{edition_id}-a2", "title": "标题乙", "author": ""},
        ],
    }


@pytest.mark.asyncio
async def test_kjrb_posts_with_required_header_and_builds_spa_urls(monkeypatch):
    posts: list[dict] = []
    responses = [_KJRB_DATE, _KJRB_EDITIONS, _kjrb_articles("ed1"), _kjrb_articles("ed2")]
    _install_post(monkeypatch, responses, posts)

    result = await epaper_central.handle_route(_request("stdaily-kjrb"), no_cache=True)

    assert [p["url"].split("uv/article/", 1)[1] for p in posts] == [
        "period/date",
        "period/periodTime",
        "article/editionId",
        "article/editionId",
    ]
    # 页面 axios 实例的缺省请求头,缺了接口返回 no access!(header_matrix 证据)
    assert posts[0]["headers"]["x-requested-with"] == "XMLHttpRequest"
    assert posts[0]["body"]["code"] == "KJRB"
    assert posts[0]["body"]["siteId"] == "811c18b08cf04e79be3b67d6902ee1a7"
    assert posts[0]["body"]["date"].endswith("-01")
    assert posts[1]["body"]["periodTime"] == "2026-09-26"  # 不晚于今天的最大日期
    assert posts[2]["body"]["id"] == "ed1"  # 版面按 weight 升序

    assert result.type == "科技日报 · 电子报"
    assert result.total == 4
    first = result.data[0]
    assert first.id == "ed1-a1"
    assert first.title == "标题甲"  # <p> 去掉
    assert first.author == "记者一"
    assert first.desc == "第01版 今日要闻"
    assert "currentNewsId=ed1-a1" in first.url
    assert first.url.startswith("https://epaper.stdaily.com/statics/technology-site/index.html#/home?")
    assert first.timestamp == _TS_0926
    assert result.data[2].desc == "第02版 要闻"  # 版名中间的排版空格去掉


@pytest.mark.asyncio
async def test_kjrb_no_access_shell_is_an_error(monkeypatch):
    _install_post(monkeypatch, [{"status": "500", "msg": "no access!"}])
    with pytest.raises(RuntimeError, match="no access"):
        await epaper_central.handle_route(_request("stdaily-kjrb"), no_cache=True)


# --------------------------------------------------------------- 军事记者(期刊)


_JSJZ_LIST = """
<html><body>
<a href="2026nd3q_111/index.html">2026年第3期</a>
<a href="2026nd4q_253225/index.html">2026年第4期</a>
<a href="/paper/other.html">其它链接</a>
</body></html>"""

_JSJZ_ISSUE = """
<html><body>
<dl><dt>卷首语</dt><dd><ul>
<li><a href="123.html">文章一<span class="author">作者：本刊编辑部</span></a></li>
</ul></dd></dl>
<dl><dt>特稿</dt><dd><ul>
<li><a href="/other/999.html">站外链接不算</a></li>
<li><a href="124.html">文章二</a></li>
</ul></dd></dl>
</body></html>"""


@pytest.mark.asyncio
async def test_periodical_takes_latest_issue_and_splits_authors(monkeypatch):
    calls: list[str] = []
    _install_get(
        monkeypatch,
        {
            "http://www.81.cn/rmjz_203219/jsjz/index.html": _JSJZ_LIST,
            "http://www.81.cn/rmjz_203219/jsjz/2026nd4q_253225/index.html": _JSJZ_ISSUE,
        },
        calls,
    )
    result = await epaper_central.handle_route(_request("81cn-jsjz"), no_cache=True)

    assert calls[-1].endswith("/2026nd4q_253225/index.html")  # 期号最大的一期
    assert result.type == "军事记者 · 电子报"
    assert result.total == 2
    first = result.data[0]
    assert first.title == "文章一"
    assert first.author == "本刊编辑部"  # "作者:"前缀去掉
    assert first.url == "http://www.81.cn/rmjz_203219/jsjz/2026nd4q_253225/123.html"
    assert first.desc == "卷首语"
    assert first.timestamp is None  # 期刊没有单一出版日期,timestamp 留空
    assert result.data[1].desc == "特稿"
    assert "2026年第4期" in (result.message or "")


# --------------------------------------------------------------- 系统 C(新华每日电讯,listdaohang)


_MRDX_PAPER_INDEX = (
    "<html><head><META HTTP-EQUIV='REFRESH' CONTENT='0; URL=20260928/IssueIndex.htm'>"
    "</head><body></body></html>"
)
_MRDX_ISSUE_INDEX = (
    "<html><head><META HTTP-EQUIV='REFRESH' CONTENT='0; URL=Page01BC.htm'>"
    "</head><body></body></html>"
)
_MRDX_PAGE_1 = """
<html><body>
<div class="listdaohang">
<h4><a href="../../PDF/20260928/01.pdf"><img src="../../public2/pdf.gif"/></a>
<a href="Page01BC.htm">01版：要闻 </a></h4>
<ul>
<li><a daoxiang="Articel01002NR.htm">大国正确相处的新路</a></li>
<li><a daoxiang="Articel01003NR.htm">厚植中国式现代化的平安底色</a></li>
</ul>
<h4><a href="../../PDF/20260928/02.pdf"><img src="../../public2/pdf.gif"/></a>
<a href="Page02BC.htm">02版：文化 </a></h4>
<ul>
<li><a daoxiang="Articel02002NR.htm">中美关系新定位</a></li>
</ul>
</div>
</body></html>"""


@pytest.mark.asyncio
async def test_paperindex_c_uses_listdaohang_without_fetching_every_page(monkeypatch):
    calls: list[str] = []
    _install_get(
        monkeypatch,
        {
            "http://mrdx.cn/content/PaperIndex.htm": _MRDX_PAPER_INDEX,
            "http://mrdx.cn/content/20260928/IssueIndex.htm": _MRDX_ISSUE_INDEX,
            "http://mrdx.cn/content/20260928/Page01BC.htm": _MRDX_PAGE_1,
        },
        calls,
    )
    result = await epaper_central.handle_route(_request("mrdx-mrdx"), no_cache=True)

    # 新华每日电讯首版页一页列出全期,不再逐版请求
    assert all(not url.endswith("Page02BC.htm") for url in calls)
    assert result.type == "新华每日电讯 · 电子报"
    assert result.total == 3
    first, second, third = result.data
    assert first.desc == "第01版 要闻"
    assert first.url == "http://mrdx.cn/content/20260928/Articel01002NR.htm"
    assert second.url.endswith("Articel01003NR.htm")
    assert third.desc == "第02版 文化"
    assert first.timestamp == _TS_0928


# --------------------------------------------------------------- 错误壳与未知子榜


@pytest.mark.asyncio
async def test_empty_layout_is_an_error(monkeypatch):
    _install_get(
        monkeypatch,
        {"https://paper.people.com.cn/rmrb/pc/layout/index.html": "<html><body>改版了</body></html>"},
    )
    with pytest.raises(RuntimeError, match="没有解析到版面"):
        await epaper_central.handle_route(_request("people-rmrb"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_type_is_rejected(monkeypatch):
    async def fail_get(*args, **kwargs):
        raise AssertionError("unknown type must not fetch")

    monkeypatch.setattr(epaper, "get", fail_get)
    with pytest.raises(ValueError, match="Unknown board"):
        await epaper_central.handle_route(_request("nonsense"), no_cache=True)


def test_route_meta_declares_all_types_in_order():
    types = epaper_central.ROUTE_META["params"]["type"]["type"]
    assert list(types) == list(epaper_central.type_map)
    assert next(iter(types)) == epaper_central.DEFAULT_TYPE
    assert len(types) == 17
    assert json.dumps(types, ensure_ascii=False)  # 可序列化

"""epaper-local 路由测试:mock 共享 get/post,fixtures 按 board_api 证据结构净化内联。"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import _epaper_common as epaper
from whats_hot_api.routes.hotlist import epaper_local
from whats_hot_api.utils.http_client import RequestResult

_UPDATE_TIME = "2026-10-01T00:00:00+00:00"
_TS_0927 = 1790438400000  # 2026-09-27 北京时间 0 点(毫秒)
_TS_0928 = 1790524800000


def _request(board_type: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/epaper-local",
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


# --------------------------------------------------------------- 系统 B(河南日报,meta refresh)


_HNRB_INDEX = (
    "<html><head><META HTTP-EQUIV='REFRESH' CONTENT='0; URL=html/2026-09/27/node_1.htm?v=1'>"
    "</head><body></body></html>"
)
_HNRB_NODE_1 = """
<html><body>
<a href="node_1.htm">第01版 要闻</a>
<a href="node_2.htm">第02版 理论</a>
<a href="content_1.htm">标题一</a>
<a href="content_2.htm">标题二</a>
<a href="javascript:print()">不算</a>
</body></html>"""
_HNRB_NODE_2 = """
<html><body>
<a href="node_1.htm">第01版 要闻</a>
<a href="content_3.htm">标题三</a>
<a href="content_1.htm">跨版重复只留第一次</a>
</body></html>"""


@pytest.mark.asyncio
async def test_fangzheng_b_follows_meta_refresh_and_maps_pages(monkeypatch):
    calls: list[str] = []
    _install_get(
        monkeypatch,
        {
            "https://newpaper.dahe.cn/hnrb/paperindex.htm": _HNRB_INDEX,
            "https://newpaper.dahe.cn/hnrb/html/2026-09/27/node_1.htm": _HNRB_NODE_1,
            "https://newpaper.dahe.cn/hnrb/html/2026-09/27/node_2.htm": _HNRB_NODE_2,
        },
        calls,
    )
    result = await epaper_local.handle_route(_request("dahe-hnrb"), no_cache=True)

    assert calls == [
        "https://newpaper.dahe.cn/hnrb/paperindex.htm",
        "https://newpaper.dahe.cn/hnrb/html/2026-09/27/node_1.htm?v=1",
        "https://newpaper.dahe.cn/hnrb/html/2026-09/27/node_2.htm",
    ]
    assert result.type == "河南日报 · 电子报"
    assert result.total == 3  # 跨版重复按链接去重
    first = result.data[0]
    assert first.url == "https://newpaper.dahe.cn/hnrb/html/2026-09/27/content_1.htm"
    assert first.desc == "第01版 要闻"
    assert first.timestamp == _TS_0927  # 出版日期取 html/YYYY-MM/DD 目录
    assert result.data[2].desc == "第02版 理论"


# --------------------------------------------------------------- 系统 C(大众日报,版面导航)


_DZRB_PAPER_INDEX = (
    "<html><head><META HTTP-EQUIV='REFRESH' CONTENT='0; URL=20260927/IssueIndex.htm'>"
    "</head><body></body></html>"
)
_DZRB_ISSUE_INDEX = (
    "<html><head><META HTTP-EQUIV='REFRESH' CONTENT='0; URL=Page01NU.htm'>"
    "</head><body></body></html>"
)
# 大众日报的版面导航:同一个 Page 链接出现两次(数字版号 + "头版"版名,"下一版"不算)
_DZRB_PAGE_1 = """
<html><body>
<LI class=banci>[<SPAN class=banci-A01><A href="Page01NU.htm">01</A></SPAN>]:<A href="Page01NU.htm">头版</A>
<LI class=banci>[<SPAN class=banci-A01><A href="Page02NU.htm">02</A></SPAN>]:<A href="Page02NU.htm">要闻</A>
<LI class=banci><A href="Page03NU.htm">下一版</A>
<UL id=newslist>
<LI><A href="Articel01002MT.htm">习近平结束对美国的国事访问回到北京</A></LI>
</UL>
</body></html>"""

_DZRB_PAGE_2 = """
<html><body>
<UL id=newslist>
<LI><A href="Articel02002MT.htm">评论标题</A></LI>
<LI><A href="Articel01002MT.htm">跨版重复只留第一次</A></LI>
</UL>
</body></html>"""


@pytest.mark.asyncio
async def test_paperindex_c_follows_nav_and_fetches_each_page(monkeypatch):
    calls: list[str] = []
    _install_get(
        monkeypatch,
        {
            "http://paper.dzwww.com/dzrb/content/PaperIndex.htm": _DZRB_PAPER_INDEX,
            "http://paper.dzwww.com/dzrb/content/20260927/IssueIndex.htm": _DZRB_ISSUE_INDEX,
            "http://paper.dzwww.com/dzrb/content/20260927/Page01NU.htm": _DZRB_PAGE_1,
            "http://paper.dzwww.com/dzrb/content/20260927/Page02NU.htm": _DZRB_PAGE_2,
        },
        calls,
    )
    result = await epaper_local.handle_route(_request("dzwww-dzrb"), no_cache=True)

    # 导航式系统 C:第 2 版要逐版请求("下一版"链接不算版面)
    assert any(url.endswith("Page02NU.htm") for url in calls)
    assert all(not url.endswith("Page03NU.htm") for url in calls)
    assert result.type == "大众日报 · 电子报"
    assert result.total == 2  # 跨版重复按链接去重
    first = result.data[0]
    assert first.title == "习近平结束对美国的国事访问回到北京"
    assert first.url == "http://paper.dzwww.com/dzrb/content/20260927/Articel01002MT.htm"
    assert first.desc == "第01版 头版"
    assert first.timestamp == _TS_0927  # 出版日期取 content/YYYYMMDD 目录
    assert result.data[1].desc == "第02版 要闻"


# --------------------------------------------------------------- 新京报(data.json)


_BJNEWS_HOME = "<html><head><meta http-equiv='refresh' content='0;url=html/2026/20260928/20260928_A01/index.html'></head></html>"
_BJNEWS_DATA = [
    {
        "pageNo": "01",
        "pageName": "要闻",
        "onePageArticleList": [
            {
                "mainTitle": "重点商圈<br/>客流同比增14.7%",
                "articleHref": "20260928_A01_01_9090_2104223382114406402.html",
                "articleAuthor": "记者一",
            },
            {"mainTitle": "  空白 标题 ", "articleHref": "20260928_A01_02_7462_2104223382458339329.html"},
        ],
    },
    {"pageNo": "02", "pageName": "评论", "onePageArticleList": []},
]


@pytest.mark.asyncio
async def test_bjnews_maps_data_json_and_builds_outline_urls(monkeypatch):
    _install_get(
        monkeypatch,
        {
            # data.json 的前缀更长,放在首页前面避免被 "/" 截住
            "http://epaper.bjnews.com.cn/html/2026/20260928/data.json": _BJNEWS_DATA,
            "http://epaper.bjnews.com.cn/": _BJNEWS_HOME,
        },
    )
    result = await epaper_local.handle_route(_request("bjnews-xjb"), no_cache=True)

    assert result.type == "新京报 · 电子报"
    assert result.total == 2  # 空版不产生条目
    first = result.data[0]
    assert first.title == "重点商圈 客流同比增14.7%"  # <br/> 换成空格
    assert (
        first.url
        == "http://epaper.bjnews.com.cn/html/2026/20260928/20260928_01/20260928_A01_01_9090_2104223382114406402.html"
    )  # outline.js:'../' + issueDate去横线 + '_' + pageNo + '/' + articleHref
    assert first.author == "记者一"
    assert first.desc == "第01版 要闻"
    assert first.timestamp == _TS_0928


# --------------------------------------------------------------- 解放日报(list.do + getJournalPage.do)


def _jfrb_listing() -> dict:
    return {
        "success": True,
        "object": {"departList": [{"code": "whb", "jdate": "2026-09-26"}, {"code": "jfrb", "jdate": "2026-09-27", "pnumber": "01"}]},
    }


_JFRB_PAGE_1 = {
    "success": True,
    "object": {
        "page": {"pnumber": "01", "pname": "要闻"},
        "pagelist": [{"pnumber": "01", "pname": "要闻"}, {"pnumber": "02", "pname": "评论"}],
        # 页面 index.js 把 articlelist 倒序显示,路由同样倒序
        "articlelist": [{"id": 536596, "title": "后一条"}, {"id": 536595, "title": "前一条"}],
    },
}
_JFRB_PAGE_2 = {
    "success": True,
    "object": {
        "page": {"pnumber": "02", "pname": "评论"},
        "pagelist": [{"pnumber": "02", "pname": "评论"}],
        "articlelist": [{"id": 536600, "title": "评论"}],
    },
}


@pytest.mark.asyncio
async def test_jfrb_reverses_articlelist_and_builds_detail_urls(monkeypatch):
    calls: list[str] = []
    pages: dict[str, Any] = {
        "https://www.jfdaily.com/journal/list.do": _jfrb_listing(),
        "https://www.jfdaily.com/journal/2026-09-27/getJournalPage.do?page=01": _JFRB_PAGE_1,
        "https://www.jfdaily.com/journal/2026-09-27/getJournalPage.do?page=02": _JFRB_PAGE_2,
    }

    async def fake_get(url: str, headers=None, no_cache=None, response_type="text", **kwargs):
        calls.append(url)
        assert "Mozilla/5.0" in (headers or {}).get("User-Agent", "")
        for prefix, payload in pages.items():
            if url.startswith(prefix):
                return _res(payload)
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(epaper, "get", fake_get)
    monkeypatch.setattr(epaper, "_MIN_SITE_GAP_SECONDS", 0)
    result = await epaper_local.handle_route(_request("jfdaily-jfrb"), no_cache=True)

    assert "https://www.jfdaily.com/journal/2026-09-27/getJournalPage.do?page=02&code=jfrb" in calls
    assert result.type == "解放日报 · 电子报"
    assert result.total == 3
    first = result.data[0]
    assert first.id == "536595"  # 倒序后第一条是接口的最后一个
    assert first.title == "前一条"
    assert first.url == "https://www.jfdaily.com/staticsg/res/html/journal/detail.html?code=jfrb&date=2026-09-27&id=536595&page=01"
    assert first.desc == "第01版 要闻"
    assert first.timestamp == _TS_0927
    assert result.data[2].desc == "第02版 评论"


@pytest.mark.asyncio
async def test_jfrb_error_shell_is_an_error(monkeypatch):
    _install_get(
        monkeypatch,
        {
            "https://www.jfdaily.com/journal/list.do": _jfrb_listing(),
            "https://www.jfdaily.com/journal/2026-09-27/getJournalPage.do?page=01": {
                "success": False,
                "errorinfo": "no issue",
            },
        },
    )
    with pytest.raises(RuntimeError, match="getJournalPage"):
        await epaper_local.handle_route(_request("jfdaily-jfrb"), no_cache=True)


# --------------------------------------------------------------- 21世纪经济报道(首页即当期)


_JJ21_HOME = """
<html><body><div class="content">
<h1>2026年09月25日 星期五</h1>
<div class="main">
<a href="/paper/01.htm"><h5>01版：头版</h5></a>
<ul>
<li><a href="http://www.21jingji.com/article/101.html">导读一<p>这是摘要要摘掉</p></a></li>
<li><a href="http://www.21jingji.com/ad/spot.html">广告位不算</a></li>
</ul>
<a href="/paper/02.htm"><h5>02版：评论</h5></a>
<ul>
<li><a href="http://www.21jingji.com/article/102.html">评论一</a></li>
</ul>
</div></div></body></html>"""


@pytest.mark.asyncio
async def test_21jingji_parses_home_layout_and_strips_summary(monkeypatch):
    _install_get(monkeypatch, {"http://epaper.21jingji.com/": _JJ21_HOME})
    result = await epaper_local.handle_route(_request("21jingji-21sjjjbd"), no_cache=True)

    assert result.type == "21世纪经济报道 · 电子报"
    assert result.total == 2  # /article/ 之外的链接不算
    first = result.data[0]
    assert first.title == "导读一"
    assert first.url == "http://www.21jingji.com/article/101.html"
    assert first.desc == "第01版 头版"
    assert first.timestamp == 1790265600000  # 2026-09-25 北京时间 0 点
    assert result.data[1].desc == "第02版 评论"


# --------------------------------------------------------------- 每日经济新闻(今日报纸文字版)


_NBD_PAGE = """
<html><body>
今日报纸 : 2026-09-28
<div class="newspapper">
<p class="newspapper-title">01 - 封面</p>
<ul>
<li><a href="https://www.nbd.com.cn/articles/2026-09-28/1001.html">文章一</a></li>
<li><a href="https://www.nbd.com.cn/column/home.html">栏目不算</a></li>
</ul>
</div>
<div class="newspapper">
<p class="newspapper-title">02 - 公司</p>
<ul><li><a href="/articles/2026-09-28/1002.html">文章二</a></li></ul>
</div>
</body></html>"""


@pytest.mark.asyncio
async def test_nbd_parses_today_blocks(monkeypatch):
    _install_get(monkeypatch, {"https://www.nbd.com.cn/newspapers/today": _NBD_PAGE})
    result = await epaper_local.handle_route(_request("nbd-mrjjxw"), no_cache=True)

    assert result.type == "每日经济新闻 · 电子报"
    assert result.total == 2
    first = result.data[0]
    assert first.title == "文章一"
    assert first.url == "https://www.nbd.com.cn/articles/2026-09-28/1001.html"
    assert first.desc == "第01版 封面"
    assert first.timestamp == _TS_0928
    assert result.data[1].url == "https://www.nbd.com.cn/articles/2026-09-28/1002.html"


# --------------------------------------------------------------- 经济观察报(文字版分页)


def _eeo_cover() -> str:
    return """
<html><body><div class="dzkw_dzb_box">
<input type="hidden" id="e_cid_1" value="1290"/>
<input type="hidden" id="e_cbqh_1" value="2026-09-28"/>
</div></body></html>"""


_EEO_P1 = """
<html><body><div class="wzlist"><ul class="new_list">
<li><a href="/eeo/2026/0925/1001.shtml">文字一</a></li>
<li><a href="/eeo/2026/0925/1002.shtml">文字二</a></li>
</ul></div>
<div class="wzlist_page"><a class="next" href="https://app.eeo.com.cn/?app=epaper&controller=text&action=eeolist&cid=261&qid=1290&page=2">下一页</a></div>
</body></html>"""

_EEO_P2 = """
<html><body><div class="wzlist"><ul class="new_list">
<li><a href="/eeo/2026/0925/1003.shtml">文字三</a></li>
</ul></div>
<div class="wzlist_page"><span class="next">下一页</span></div>
</body></html>"""


@pytest.mark.asyncio
async def test_eeo_follows_text_edition_pages(monkeypatch):
    calls: list[str] = []
    _install_get(
        monkeypatch,
        {
            "https://www.eeo.com.cn/epaper/eeocover/1.shtml": _eeo_cover(),
            # page=2 的前缀更长,放在前面避免被第 1 页的前缀截住
            "https://app.eeo.com.cn/?app=epaper&controller=text&action=eeolist&cid=261&qid=1290&page=2": _EEO_P2,
            "https://app.eeo.com.cn/?app=epaper&controller=text&action=eeolist&cid=261&qid=1290": _EEO_P1,
        },
        calls,
    )
    result = await epaper_local.handle_route(_request("eeo-jjgcb"), no_cache=True)

    assert calls[-1].endswith("qid=1290&page=2")  # 翻到最后一页为止
    assert result.type == "经济观察报 · 电子报"
    assert result.total == 3
    first = result.data[0]
    assert first.title == "文字一"
    assert first.url == "https://app.eeo.com.cn/eeo/2026/0925/1001.shtml"
    assert first.desc is None  # 文字版没有版面信息,desc 留空
    assert first.timestamp == _TS_0928
    assert "第1290期" in (result.message or "")


# --------------------------------------------------------------- 未知子榜


@pytest.mark.asyncio
async def test_unknown_type_is_rejected(monkeypatch):
    async def fail_get(*args, **kwargs):
        raise AssertionError("unknown type must not fetch")

    monkeypatch.setattr(epaper, "get", fail_get)
    with pytest.raises(ValueError, match="Unknown board"):
        await epaper_local.handle_route(_request("nonsense"), no_cache=True)


@pytest.mark.asyncio
async def test_system_a_empty_layout_is_an_error(monkeypatch):
    _install_get(
        monkeypatch,
        {"https://www.yicai.com/epaper/pc/index.html": "<html><body>改版了</body></html>"},
    )
    with pytest.raises(RuntimeError, match="没有解析到版面"):
        await epaper_local.handle_route(_request("yicai-dyjrb"), no_cache=True)


def test_route_meta_declares_all_types_in_order():
    types = epaper_local.ROUTE_META["params"]["type"]["type"]
    assert list(types) == list(epaper_local.type_map)
    assert next(iter(types)) != epaper_local.DEFAULT_TYPE  # 默认榜是新京报,声明序第一个是大众日报
    assert epaper_local.DEFAULT_TYPE == "bjnews-xjb"
    assert len(types) == 16

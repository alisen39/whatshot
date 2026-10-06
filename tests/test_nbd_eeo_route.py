from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import nbd_eeo
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str | None = None) -> Request:
    query = f"type={board_type}" if board_type else ""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/nbd-eeo",
        "query_string": query.encode(),
        "headers": [],
    })


def _nbd_column_html(with_truncated: bool = True) -> str:
    truncated_block = """
          <li class="u-news-title">
            <a class="news-title-a" href="https://www.nbd.com.cn/articles/2026-09-30/4596124.html">截短标题前半段；高</a>
            <span>22:09:06</span>
          </li>
""" if with_truncated else ""
    return f"""
    <html><body>
    <div class="g-list-text">
      <div class="m-list">
        <p class="u-channeltime">2026-09-30</p>
        <ul class="u-news-list">
          <li class="u-news-title">
            <a href="https://www.nbd.com.cn/articles/2026-09-30/4596022.html">完整标题一条</a>
            <span>22:14:12</span>
          </li>
{truncated_block}
        </ul>
      </div>
      <div class="m-list">
        <p class="u-channeltime">2026-09-29</p>
        <ul class="u-news-list">
          <li class="u-news-title">
            <a href="https://www.nbd.com.cn/articles/2026-09-29/4595000.html">前一日的完整标题</a>
            <span>09:00:00</span>
          </li>
        </ul>
      </div>
    </div>
    </body></html>
    """


def _nbd_mobile_html() -> str:
    return """
    <html><body>
    <div class="articleList">
      <a href="https://www.nbd.com.cn/articles/2026-09-30/4596124.html">截短标题前半段；高完整后续标题</a>
    </div>
    </body></html>
    """


def _nbd_article_html(title: str) -> str:
    return f"<html><head><title>{title} | 每经网</title></head><body></body></html>"


def _eeo_api_row(content_id: str, title: str, published: str) -> dict:
    return {
        "id": "48ffcec604334f5ea07c42266d125d77",
        "title": title,
        "thumb": "https://jg-app.obs.cn-north-4.example/thumb.jpg",
        "description": "导语",
        "author": "陈植",
        "published": published,
        "m_url": f"http://m.eeo.com.cn/2026/0930/{content_id}.shtml",
        "contentid": content_id,
        "url": f"https://www.eeo.com.cn/2026/0930/{content_id}.shtml",
        "pv": "221",
        "catname": "新科技",
    }


def _eeo_channel_html(with_top: bool = True) -> str:
    top_block = """
    <div id="top-bjtj">
      <a href="http://www.eeo.com.cn/2026/0928/1050721.shtml" class="xd-xny-a">
        <img src="https://img.example/top.jpg" alt="推荐区短标题">
        <b>推荐区短标题</b>
        <span>推荐区导语</span>
      </a>
    </div>
""" if with_top else ""
    return f"""
    <html><body>
    {top_block}
    <ul id="lyp_article"></ul>
    </body></html>
    """


def _eeo_home_html() -> str:
    return """
    <html><body>
    <div class="box_R_item line news">
      <ul class="tabs_click">
        <li class="on">每日热新闻</li>
        <li>每周热新闻</li>
      </ul>
      <div class="tab_contents">
        <ul class="tab_content">
          <li><a href="http://www.eeo.com.cn/2026/0928/1050830.shtml" target="_blank" title="公考培训，全面肉搏">公考培训，全面肉搏 </a></li>
          <li><a href="http://www.eeo.com.cn/2026/0928/1050630.shtml" target="_blank" title="碳与硅的第一次握手
——碳硅共生经济学导论">碳与硅的第一次握手 </a></li>
        </ul>
        <ul class="tab_content">
          <li><a href="http://www.eeo.com.cn/2026/0927/1050153.shtml" target="_blank" title="每周榜条目">每周榜条目 </a></li>
        </ul>
      </div>
    </div>
    </body></html>
    """


@pytest.mark.asyncio
async def test_default_board_fetches_nbd_news_column(monkeypatch):
    captured = {}

    async def fake_get(url, no_cache=None, **kwargs):
        captured["url"] = url
        captured["no_cache"] = no_cache
        return RequestResult(False, "t", _nbd_column_html(with_truncated=False))

    monkeypatch.setattr(nbd_eeo, "get", fake_get)
    result = await nbd_eeo.handle_route(_request(), no_cache=True)

    # 不带 type 参数取默认榜要闻（栏目 3）；column id 走 www.nbd.com.cn 电脑版栏目页
    assert captured["url"] == "https://www.nbd.com.cn/columns/3/"
    assert captured["no_cache"] is True
    assert result.type == "每经网 · 要闻"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "4596022"
    assert first.title == "完整标题一条"
    assert first.url == "https://www.nbd.com.cn/articles/2026-09-30/4596022.html"
    assert first.timestamp == 1790777652000  # 2026-09-30 22:14:12 北京时间，毫秒
    # 第二个分组换了日期，时间跟随分组标题
    assert result.data[1].timestamp == 1790643600000  # 2026-09-29 09:00:00 北京时间
    assert result.message is None


@pytest.mark.asyncio
async def test_nbd_truncated_title_completed_from_mobile_page(monkeypatch):
    urls = []

    async def fake_get(url, no_cache=None, **kwargs):
        urls.append(url)
        if url.startswith("https://m.nbd.com.cn"):
            return RequestResult(False, "t", _nbd_mobile_html())
        return RequestResult(False, "t", _nbd_column_html())

    monkeypatch.setattr(nbd_eeo, "get", fake_get)
    result = await nbd_eeo.handle_route(_request("nbd-market-events"), no_cache=True)

    assert urls[0] == "https://www.nbd.com.cn/columns/2226/"
    assert urls[1] == "https://m.nbd.com.cn/columns/2226/"  # 截短标题去手机版第 1 页补全
    assert all(not url.startswith("https://m.nbd.com.cn/columns/2226/page/")
               for url in urls)  # 第 1 页已补全，不再翻页
    item = next(entry for entry in result.data if entry.id == "4596124")
    assert item.title == "截短标题前半段；高完整后续标题"
    assert result.message is None


@pytest.mark.asyncio
async def test_nbd_title_falls_back_to_article_page(monkeypatch):
    async def fake_get(url, no_cache=None, **kwargs):
        if url.startswith("https://m.nbd.com.cn"):
            # 手机版是另一份列表（对不上电脑版的 id）
            return RequestResult(False, "t", '<div class="articleList"><a href="https://www.nbd.com.cn/articles/2020-01-01/111.html">别的列表</a></div>')
        if "/articles/" in url:
            return RequestResult(False, "t", _nbd_article_html("截短标题前半段；高后续完整标题"))
        return RequestResult(False, "t", _nbd_column_html())

    monkeypatch.setattr(nbd_eeo, "get", fake_get)
    result = await nbd_eeo.handle_route(_request("nbd-original"), no_cache=True)

    item = next(entry for entry in result.data if entry.id == "4596124")
    assert item.title == "截短标题前半段；高后续完整标题"  # 文章页 <title> 去掉" | 每经网"后缀
    assert result.message is None


@pytest.mark.asyncio
async def test_nbd_uncompletable_title_keeps_page_text_and_reports(monkeypatch):
    async def fake_get(url, no_cache=None, **kwargs):
        if url.startswith("https://m.nbd.com.cn"):
            return RequestResult(False, "t", "<div></div>")
        if "/articles/" in url:
            return RequestResult(False, "t", "<html><head><title>无标题页</title></head></html>")
        return RequestResult(False, "t", _nbd_column_html())

    monkeypatch.setattr(nbd_eeo, "get", fake_get)
    result = await nbd_eeo.handle_route(_request("nbd-original"), no_cache=True)

    item = next(entry for entry in result.data if entry.id == "4596124")
    assert item.title == "截短标题前半段；高"  # 补不上时照栏目页原样
    assert result.message is not None
    assert "1 条标题" in result.message


@pytest.mark.asyncio
async def test_eeo_channel_merges_top_region_with_api_list(monkeypatch):
    urls = []
    payload = {
        "code": 200,
        "data": [
            _eeo_api_row("1050721", "推荐区短标题（接口同篇）", "2026-09-30 10:00:00"),
            _eeo_api_row("1053778", "列表第一条", "2026-09-30 12:26:13"),
        ],
    }

    async def fake_get(url, no_cache=None, **kwargs):
        urls.append(url)
        if url.startswith("https://app.eeo.com.cn/"):
            return RequestResult(False, "t", payload)
        return RequestResult(False, "t", _eeo_channel_html())

    monkeypatch.setattr(nbd_eeo, "get", fake_get)
    result = await nbd_eeo.handle_route(_request("eeo-business"), no_cache=True)

    # 推荐区走频道页，列表走 getMoreArticle（不带 jsoncallback 直接返回 JSON）
    assert urls[0] == "https://www.eeo.com.cn/jg/chanye/"
    assert urls[1] == (
        "https://app.eeo.com.cn/?app=article&controller=index&action=getMoreArticle"
        "&uuid=317476ab2e7b4c34918b73f7d04e2e52&page=0&pageSize=10&prevUuid=&prevPublishDate="
    )
    assert result.total == 2  # 推荐区与列表同一篇按 id 去重
    first = result.data[0]
    assert first.id == "1050721"
    assert first.url == "http://www.eeo.com.cn/2026/0928/1050721.shtml"
    # 同一篇也在列表里时，用列表的发布时间（推荐区本身只有日期）
    assert first.timestamp == 1790733600000  # 2026-09-30 10:00:00 北京时间
    assert first.mobileUrl == "http://m.eeo.com.cn/2026/0928/1050721.shtml"  # 推荐区按链接日期拼手机站同路径
    assert first.desc == "推荐区导语"
    assert first.cover == "https://img.example/top.jpg"
    second = result.data[1]
    assert second.id == "1053778"
    assert second.hot == 221
    assert second.timestamp == 1790742373000  # 2026-09-30 12:26:13 北京时间


@pytest.mark.asyncio
async def test_eeo_channel_top_only_item_keeps_link_date_midnight(monkeypatch):
    payload = {
        "code": 200,
        "data": [_eeo_api_row("1053778", "列表第一条", "2026-09-30 12:26:13")],
    }

    async def fake_get(url, no_cache=None, **kwargs):
        if url.startswith("https://app.eeo.com.cn/"):
            return RequestResult(False, "t", payload)
        return RequestResult(False, "t", _eeo_channel_html())

    monkeypatch.setattr(nbd_eeo, "get", fake_get)
    result = await nbd_eeo.handle_route(_request("eeo-business"), no_cache=True)

    first = result.data[0]
    assert first.id == "1050721"
    # 推荐区没有时间：按链接日期（2026-09-28）当天 0 点
    assert first.timestamp == 1790524800000


@pytest.mark.asyncio
async def test_eeo_api_error_shell_and_ads_are_handled(monkeypatch):
    async def fake_get(url, no_cache=None, **kwargs):
        if url.startswith("https://app.eeo.com.cn/"):
            return RequestResult(False, "t", {"code": 500, "message": "server busy"})
        return RequestResult(False, "t", _eeo_channel_html())

    monkeypatch.setattr(nbd_eeo, "get", fake_get)
    with pytest.raises(RuntimeError, match="code=500"):
        await nbd_eeo.handle_route(_request("eeo-finance"), no_cache=True)

    ads_payload = {
        "code": 200,
        "data": [
            {"contentid": "0", "title": "光大证券 极速开户", "url": "https://ad.example/x", "published": "2026-09-30 10:00:00"},
            {"contentid": "1052064", "title": "没有发布时间的一行", "url": "https://www.eeo.com.cn/2026/0929/1052064.shtml"},
            _eeo_api_row("1053778", "换行 与连续  空白", "2026-09-30 12:26:13"),
        ],
    }

    async def fake_get_ok(url, no_cache=None, **kwargs):
        if url.startswith("https://app.eeo.com.cn/"):
            return RequestResult(False, "t", ads_payload)
        return RequestResult(False, "t", _eeo_channel_html(with_top=False))

    monkeypatch.setattr(nbd_eeo, "get", fake_get_ok)
    result = await nbd_eeo.handle_route(_request("eeo-finance"), no_cache=True)

    assert [entry.id for entry in result.data] == ["1053778"]  # contentid=0 / 没有 published 的都不算条目
    assert result.data[0].title == "换行 与连续 空白"  # 换行与连续空白压成一个空格


@pytest.mark.asyncio
async def test_eeo_daily_hot_reads_first_tab_only(monkeypatch):
    async def fake_get(url, no_cache=None, **kwargs):
        assert url == "https://www.eeo.com.cn/"
        return RequestResult(False, "t", _eeo_home_html())

    monkeypatch.setattr(nbd_eeo, "get", fake_get)
    result = await nbd_eeo.handle_route(_request("eeo-daily-hot"), no_cache=True)

    assert result.type == "经济观察网 · 每日热新闻"
    assert result.total == 2  # 第 2 个 tab 是每周热新闻，不取
    first = result.data[0]
    assert first.id == "1050830"
    assert first.title == "公考培训，全面肉搏"  # 标题取 title 属性，不用截短的链接文字
    assert first.timestamp == 1790524800000  # 链接日期 2026-09-28 北京时间 0 点
    second = result.data[1]
    assert second.title == "碳与硅的第一次握手 ——碳硅共生经济学导论"  # 换行压成一个空格


@pytest.mark.asyncio
async def test_unknown_type_is_rejected(monkeypatch):
    async def fake_get(url, no_cache=None, **kwargs):  # pragma: no cover - 不应触网
        raise AssertionError("unknown type must not trigger any request")

    monkeypatch.setattr(nbd_eeo, "get", fake_get)
    with pytest.raises(ValueError, match="Unknown board"):
        await nbd_eeo.handle_route(_request("nbd-other"), no_cache=True)


@pytest.mark.asyncio
async def test_empty_column_parse_is_an_error(monkeypatch):
    async def fake_get(url, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html><body>维护中</body></html>")

    monkeypatch.setattr(nbd_eeo, "get", fake_get)
    with pytest.raises(RuntimeError, match="no list rows"):
        await nbd_eeo.handle_route(_request("nbd-news"), no_cache=True)

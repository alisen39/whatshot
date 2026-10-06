"""stcn_channels 路由测试:fixtures 按证据目录 tmp/board_api/stcn_channels 净化(结构与字段一致,内容摘录)。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import stcn_channels
from whats_hot_api.utils.http_client import RequestResult

_BEIJING = timezone(timedelta(hours=8))
# 列表页响应生成时刻:2026-09-28 08:20 北京时间
_PAGE_DATE = "Mon, 28 Sep 2026 00:20:00 GMT"


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/stcn-channels",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _page(html: str, date: str = _PAGE_DATE, age: str = "0") -> dict:
    """origin_info=True 时共享 get 返回的包装结构。"""
    return {"data": html, "status": 200, "headers": {"date": date, "age": age}}


_LIST_LI = """
<li class="">
  <div class="content">
    <div class="tt"><a href="/article/detail/{id}.html" target="_blank">{title}</a></div>
    <div class="text ellipsis-2"><a href="/article/detail/{id}.html">{desc}</a></div>
    <div class="tags"><a href="/article/search.html?keyword=%E6%B9%96%E5%8C%97">湖北</a></div>
    <div class="info "><span>{source}</span><span>{author}</span><span>{time}</span></div>
  </div>
  <div class="side"><a href="/article/detail/{id}.html"><img src="{cover}"></a></div>
</li>
"""

_YW_PAGE = f"""
<html><body>
<div class="swiper-images"><a href="https://www.stcn.com/ad/track.html?id=241&goto=aHR0cHM6">
<img src="https://static-web.stcn.com/upload/ad.png"></a></div>
<ul class="list infinite-list" data-url="/article/list.html?type=yw" data-pagetime="2">
  {_LIST_LI.format(id=4200127, title="恩捷股份子公司拟11.5亿元收购湖北恩捷45%股权",
                   desc="恩捷股份27日晚间公告资产收购计划及多项担保合同。", source="证券时报·e公司",
                   author="毛军", time="08:05", cover="https://static-web.stcn.com/upload/a.png")}
  {_LIST_LI.format(id=4200080, title="年内外资调研A股公司近6000次",
                   desc="近日，为吸引更多境外中长期资金入市。", source="证券时报",
                   author="毛艺融", time="09-27 18:26", cover="")}
</ul>
</body></html>
"""

_COMPANY_PAGE = f"""
<html><body>
<div class="list-page-left-top">
  <div class="swiper-images"><a href="https://www.stcn.com/ad/track.html?id=241&goto=aHR0cHM6">
  <img src="https://static-web.stcn.com/upload/ad.png"></a></div>
  <div class="top-news-box">
    <div class="top-news"><div class="top ellipsis-2">
      <a href="/article/detail/4197315.html">网络招工频密、车间深夜亮灯 众泰汽车“复活”前景...</a></div></div>
    <div class="top-news"><div class="top ellipsis-2">
      <a href="/article/detail/4200127.html">恩捷股份子公司拟11.5亿元收购湖北恩捷45%...</a></div></div>
  </div>
</div>
<ul class="list infinite-list" data-url="/article/list.html?type=company">
  {_LIST_LI.format(id=4200127, title="恩捷股份子公司拟11.5亿元收购湖北恩捷45%股权",
                   desc="恩捷股份27日晚间公告资产收购计划。", source="证券时报·e公司",
                   author="毛军", time="08:05", cover="")}
  {_LIST_LI.format(id=4200080, title="年内外资调研A股公司近6000次",
                   desc="近日，为吸引更多境外中长期资金入市。", source="证券时报",
                   author="毛艺融", time="09-27 18:26", cover="")}
</ul>
</body></html>
"""

_DETAIL_PAGE = """
<html><body>
<div class="detail-title">网络招工频密、车间深夜亮灯 众泰汽车“复活”前景几何？</div>
<div class="detail-info">
  <span>来源：证券时报 2026-09-24 A004版</span><span>作者：李小平</span><span>2026-09-24 06:41</span>
</div>
</body></html>
"""

# 快讯接口:置顶的旧条目应排最前,广告位(isAdd)不输出
_KX_PAYLOAD = {
    "state": 1,
    "msg": "操作成功",
    "data": [
        {"id": "4200124", "url": "/article/detail/4200124.html", "web_url": "/article/detail/4200124.html",
         "title": "蔚来：与吉利控股集团就换电及充电业务战略交易达成正式协议", "source": "人民财讯",
         "time": 1790554148000, "show_time": "1790554148", "isTop": 0, "isAdd": 0,
         "content": "人民财讯9月28日电，蔚来在港交所公告。", "images": []},
        {"id": "4200100", "url": "/article/detail/4200100.html", "web_url": "/article/detail/4200100.html",
         "title": "<b>置顶快讯：下周可申购2只新股</b>", "source": "人民财讯",
         "time": 1790550000000, "show_time": "1790550000", "isTop": 1, "isAdd": 0,
         "content": "人民财讯9月28日电，下周可申购2只新股。",
         "images": [{"src": "https://static-web.stcn.com/upload/kx.png"}]},
        {"id": "4200090", "url": "/article/detail/4200090.html", "web_url": "/article/detail/4200090.html",
         "title": "广告位快讯", "source": "人民财讯",
         "time": 1790556000000, "show_time": "1790556000", "isTop": 0, "isAdd": 1, "content": "", "images": []},
    ],
}

# 人民财讯热榜:没有时间,hot 是"热"角标布尔值
_RANK_PAYLOAD = {
    "state": 1,
    "msg": "操作成功",
    "data": [
        {"title": "中信证券：建议港股投资者优先关注电力等防御属性较强行业", "url": "/article/detail/4199877.html",
         "red": False, "tag": "", "hot": False},
        {"title": "国产火箭总装周期缩至约15天", "url": "/article/detail/4199583.html",
         "red": False, "tag": "", "hot": True},
    ],
}


def _ok(data: Any) -> RequestResult:
    return RequestResult(False, "2026-09-28T00:20:00+00:00", data)


async def test_list_board_maps_fields_and_request(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok(_page(_YW_PAGE))

    monkeypatch.setattr(stcn_channels, "get", fake_get)
    result = await stcn_channels.handle_route(_request("yw"), no_cache=True)

    assert captured["url"] == "https://www.stcn.com/article/list/yw.html"
    assert "text/html" in captured["headers"]["Accept"]
    assert result.name == "stcn-channels"
    assert result.type == "要闻"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "4200127"
    assert first.title == "恩捷股份子公司拟11.5亿元收购湖北恩捷45%股权"
    assert first.url == "https://www.stcn.com/article/detail/4200127.html"
    assert first.author == "证券时报·e公司 毛军"
    assert first.cover == "https://static-web.stcn.com/upload/a.png"
    expected = int(datetime(2026, 9, 28, 8, 5, tzinfo=_BEIJING).timestamp() * 1000)
    assert first.timestamp == expected  # "08:05" 以页面生成时间(2026-09-28)补日期,毫秒
    second = result.data[1]
    assert second.cover is None  # 空封面转为 None
    assert second.timestamp == int(datetime(2026, 9, 27, 18, 26, tzinfo=_BEIJING).timestamp() * 1000)


def test_list_page_time_cross_year_uses_last_year():
    # 1 月看到 "12-31 09:00" 按去年算(以页面生成时间为基准)
    now = datetime(2026, 1, 5, 10, 0, tzinfo=_BEIJING)
    seconds = stcn_channels._parse_page_time("12-31 09:00", now)
    assert seconds == int(datetime(2025, 12, 31, 9, 0, tzinfo=_BEIJING).timestamp())
    assert stcn_channels._parse_page_time("作者：李小平", now) is None


async def test_company_board_prepends_top_news_and_dedupes(monkeypatch):
    urls: list[str] = []

    async def fake_get(**kwargs):
        url = kwargs["url"]
        urls.append(url)
        if "/article/detail/4197315.html" in url:
            return _ok(_DETAIL_PAGE)  # detail 请求不带 origin_info,共享 get 直接返回 HTML 字符串
        return _ok(_page(_COMPANY_PAGE))

    monkeypatch.setattr(stcn_channels, "get", fake_get)
    result = await stcn_channels.handle_route(_request("company"), no_cache=True)

    detail_calls = [url for url in urls if "/article/detail/" in url]
    assert len(detail_calls) == 2  # 证据口径:每个有栏目头条的子榜多 2 个文章页请求
    assert result.total == 3  # 栏目头条 2 条 + 列表 2 条,4200127 去重后共 3 条
    top = result.data[0]
    assert top.id == "4197315"
    assert top.title == "网络招工频密、车间深夜亮灯 众泰汽车“复活”前景几何？"  # 文章页完整标题
    assert top.author == "证券时报 2026-09-24 A004版 李小平"  # 来源 / 作者 span 去"来源：/作者："前缀后空格连接
    assert top.timestamp == int(datetime(2026, 9, 24, 6, 41, tzinfo=_BEIJING).timestamp() * 1000)
    assert [item.id for item in result.data[1:]] == ["4200127", "4200080"]


async def test_top_news_detail_failure_falls_back_to_truncated_title(monkeypatch):
    async def fake_get(**kwargs):
        if "/article/detail/4197315.html" in kwargs["url"]:
            raise RuntimeError("upstream boom")
        return _ok(_page(_COMPANY_PAGE))

    monkeypatch.setattr(stcn_channels, "get", fake_get)
    result = await stcn_channels.handle_route(_request("company"), no_cache=True)

    top = result.data[0]
    assert top.id == "4197315"
    assert top.title == "网络招工频密、车间深夜亮灯 众泰汽车“复活”前景"  # 退回列表页截断标题


async def test_kx_orders_top_first_drops_ads_and_maps_fields(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok(dict(_KX_PAYLOAD))

    monkeypatch.setattr(stcn_channels, "get", fake_get)
    result = await stcn_channels.handle_route(_request("kx"), no_cache=True)

    assert captured["url"] == "https://www.stcn.com/article/list.html?type=kx"
    assert captured["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert result.type == "快讯"
    assert result.total == 2  # isAdd 广告位不算条目
    first = result.data[0]
    assert first.id == "4200100"  # 置顶在前
    assert first.title == "置顶快讯：下周可申购2只新股"  # 去标签
    assert first.cover == "https://static-web.stcn.com/upload/kx.png"
    assert first.author == "人民财讯"
    assert first.timestamp == 1790550000000  # show_time 秒级 → 毫秒
    assert result.data[1].id == "4200124"  # 其余按时间倒序


async def test_kx_rejects_error_shell(monkeypatch):
    async def fake_get(**kwargs):
        return _ok({"state": 0, "msg": "系统繁忙"})

    monkeypatch.setattr(stcn_channels, "get", fake_get)
    with pytest.raises(RuntimeError, match="unexpected payload"):
        await stcn_channels.handle_route(_request("kx"), no_cache=True)


async def test_rank_maps_items_without_timestamp(monkeypatch):
    async def fake_get(**kwargs):
        assert kwargs["url"] == "https://www.stcn.com/article/category-news-rank.html?type=kx"
        return _ok(dict(_RANK_PAYLOAD))

    monkeypatch.setattr(stcn_channels, "get", fake_get)
    result = await stcn_channels.handle_route(_request("kx-rank"), no_cache=True)

    assert result.type == "人民财讯热榜"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "4199877"  # id 从 url 取,与名次无关
    assert first.title == "中信证券：建议港股投资者优先关注电力等防御属性较强行业"
    assert first.url == "https://www.stcn.com/article/detail/4199877.html"
    assert first.timestamp is None  # 热榜接口没有时间
    assert first.hot is None  # "热"角标布尔值不是热度,不映射


async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await stcn_channels.handle_route(_request("nonsense"), no_cache=True)


async def test_broken_list_page_is_an_error(monkeypatch):
    async def fake_get(**kwargs):
        return _ok(_page("<html><body>维护中</body></html>"))

    monkeypatch.setattr(stcn_channels, "get", fake_get)
    with pytest.raises(RuntimeError, match="infinite-list"):
        await stcn_channels.handle_route(_request("yw"), no_cache=True)


async def test_empty_parse_is_an_error_not_empty_board(monkeypatch):
    # ul.infinite-list 存在但一条都解析不出时,必须报错而不是返回空榜
    async def fake_get(**kwargs):
        return _ok(_page('<html><body><ul class="list infinite-list"></ul></body></html>'))

    monkeypatch.setattr(stcn_channels, "get", fake_get)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await stcn_channels.handle_route(_request("yw"), no_cache=True)

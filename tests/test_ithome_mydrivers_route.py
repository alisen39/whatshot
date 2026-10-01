"""ithome-mydrivers 路由测试：mock 共享 get，fixtures 从 board_api 证据净化。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import ithome_mydrivers as route
from whats_hot_api.utils.http_client import RequestResult

_CHINA_TZ = timezone(timedelta(hours=8))
_UPDATE_TIME = "2026-09-30T13:44:51+00:00"
# 页面生成时刻（模拟响应 Date 头）：2026-09-30 21:44:51 北京时间
_PAGE_NOW = datetime(2026, 9, 30, 21, 44, 51, tzinfo=_CHINA_TZ)


def _request(board_type: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/ithome-mydrivers",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )


def _page_result(html: str, from_cache: bool = False) -> RequestResult:
    wrapped = {
        "data": html,
        "status": 200,
        "headers": {"date": "Wed, 30 Sep 2026 13:44:51 GMT"},
    }
    return RequestResult(from_cache, _UPDATE_TIME, wrapped)


RANKM_HTML = """
<div class="rank">
  <div class="rank-name" data-rank-type="day-rank">日榜</div>
  <div class="rank-box"><div class="placeholder" data-news-id="1008471"><a href="https://m.ithome.com/html/1008471.htm">
    <img data-original="https://img.ithome.com/newsuploadfiles/thumbnail/2026/9/1008471_240.jpg" />
    <p class="plc-title">日榜文章（本路由不用）</p>
    <span class="post-time">昨日 20:36</span><span class="review-num">423评</span></a></div></div>
  <div class="rank-name" data-rank-type="week-rank">周榜</div>
  <div class="rank-box">
    <div class="placeholder" data-news-id="1008151"><a href="https://m.ithome.com/html/1008151.htm" role="option">
      <img data-original="https://img.ithome.com/newsuploadfiles/thumbnail/2026/9/1008151_240.jpg" />
      <p class="plc-title">华为 Mate 90 系列手机线下展出：三折态形态再进化</p>
      <p class="plc-footer"><span class="post-time">09月27日</span><span class="review-num">670评</span></p></a></div>
    <div class="placeholder" data-news-id="1008471"><a href="https://m.ithome.com/html/1008471.htm" role="option">
      <img src="https://img.ithome.com/newsuploadfiles/thumbnail/2026/9/1008471_240.jpg" />
      <p class="plc-title">iQOO 16 手机发布：首批搭载高通第六代骁龙 8 超级至尊版</p>
      <p class="plc-footer"><span class="post-time">昨日 20:36</span><span class="review-num">423评</span></p></a></div>
  </div>
</div>
"""

CHANNEL_HTML = """
<div id="list"><ul class="bl">
  <li>
    <a href="https://www.ithome.com/1/008/914.htm" class="img"><img class="lazy"
       data-original="https://img.ithome.com/newsuploadfiles/thumbnail/2026/9/1008914_240.jpg" /></a>
    <div class="c" data-ot="2026-09-30T21:24:53.6630000+08:00">
      <h2><a title="B站开源 Index-Translate 多语言翻译模型家族" href="https://www.ithome.com/1/008/914.htm" class="title">B站开源</a></h2>
      <div class="m">哔哩哔哩 Index LLM 团队今日正式发布 Index-Translate 模型。</div>
    </div>
  </li>
</ul></div>
"""

OFFICE_HTML = """
<ul class="bar">
  <li data-id="4" class="sel">Office热榜</li>
  <li data-id="1">日榜</li>
  <li data-id="2">周榜</li>
  <li data-id="3">月榜</li>
</ul>
<ul class="bd order sel" id="d-4">
  <li><a title="微软 10 月终止 Office 2021 支持" target="_blank" href="https://www.ithome.com/0/998/998.htm">微软 10 月终止 Office 2021 支持</a></li>
  <li><a title="Excel 2016 等用户反馈微软 9 月更新导致复制粘贴功能失效" target="_blank" href="https://www.ithome.com/1/000/704.htm">Excel 2016 等用户反馈微软 9 月更新导致复制粘贴功能失效</a></li>
</ul>
"""

XIJIAYI_HTML = """
<ol class="newslist col-xs-12">
  <li>
    <div class="newspic"><a href="https://www.ithome.com/1/007/340.htm" title="">
      <img class="lazy" data-original="https://img.ithome.com/newsuploadfiles/thumbnail/2026/9/1007340_240.jpg" /></a></div>
    <div class="newsbody">
      <a href="https://www.ithome.com/1/007/340.htm" title=""><h2>科乐美《恶魔城》系列 IP 迎 40 周年，FC 初代游戏限时免费喜加一</h2></a>
      <p class="hidden-xs">同时全系列开启多平台特惠，部分作品低至 2 折。</p>
      <div class="newsbottom">
        <div class="editor">漾仔 <span class="dot">·</span>
          <span class="time"><script>jsDateDiff('2026/9/26 13:26:07')</script></span></div>
        <div class="comment">11评</div>
      </div>
    </div>
  </li>
</ol>
"""

MYDRIVERS_HTML = """
<ul class="phhot_lb" id="newlist_3_2">
  <li><h5><i>1</i> <a href="https://news.mydrivers.com/1/1154/1154872.htm">最强麒麟芯 + 展翼新折叠！华为 Mate XT 2 评测</a></h5>
    <div class="phhot_lb_left"><a href="https://news.mydrivers.com/1/1154/1154872.htm">
      <img class="lazy" data-original="https://img1.mydrivers.com/img/20260930/abc.png" src="//icons.mydrivers.com/news/2018/load.gif" /></a></div>
    <div class="phhot_lb_right"><p><a href="https://news.mydrivers.com/1/1154/1154872.htm">一、前言：最强麒麟芯片上机</a></p>
    <div class="readnumber"> 15774人阅读 </div></div></li>
</ul>
"""

ITHOME_RSS_XML = """<rss version="2.0"><channel><title>IT之家</title>
<item><title>三星 Galaxy Tab S12 系列平板发布</title>
<link>https://www.ithome.com/1/008/916.htm</link>
<pubDate>Wed, 30 Sep 2026 12:30:00 GMT</pubDate>
<description>&lt;p&gt;IT之家 9 月 30 日消息&lt;/p&gt;</description>
<guid>https://www.ithome.com/1/008/916.htm</guid></item>
</channel></rss>"""


# ---------------------------------------------------------------- rankm 排行


@pytest.mark.asyncio
async def test_rankm_week_parses_box_by_type_with_page_time(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "kwargs": kwargs})
        return _page_result(RANKM_HTML)

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("ithome-week"), no_cache=True)

    assert captured["url"] == "https://m.ithome.com/rankm/"
    assert captured["kwargs"]["response_type"] == "text"
    assert captured["kwargs"]["origin_info"] is True
    assert result.total == 2
    first = result.data[0]
    assert first.id == "1008151"
    assert first.title == "华为 Mate 90 系列手机线下展出：三折态形态再进化"
    assert first.url == "https://www.ithome.com/1/008/151.htm"
    assert first.mobileUrl == "https://m.ithome.com/html/1008151.htm"
    assert first.hot == 670  # 「670评」
    assert first.cover == "https://img.ithome.com/newsuploadfiles/thumbnail/2026/9/1008151_240.jpg"
    # 「09月27日」以页面生成时刻（响应 Date 头）为基准 → 当年 9 月 27 日 0 点北京时间
    assert first.timestamp == int(datetime(2026, 9, 27, tzinfo=_CHINA_TZ).timestamp()) * 1000
    second = result.data[1]
    # 「昨日 20:36」= 2026-09-29 20:36 北京时间
    assert second.timestamp == int(datetime(2026, 9, 29, 20, 36, tzinfo=_CHINA_TZ).timestamp()) * 1000


def test_rankm_time_uses_page_generation_base_and_cross_midnight_guard():
    # 「今天 06:09」相对页面生成时刻（基准确认点：不用本机当前时间）
    assert route.rankm_time("06:09", _PAGE_NOW) == int(datetime(2026, 9, 30, 6, 9, tzinfo=_CHINA_TZ).timestamp())
    assert route.rankm_time("昨日 23:15", _PAGE_NOW) == int(datetime(2026, 9, 29, 23, 15, tzinfo=_CHINA_TZ).timestamp())
    assert route.rankm_time("前天 08:00", _PAGE_NOW) == int(datetime(2026, 9, 28, 8, 0, tzinfo=_CHINA_TZ).timestamp())
    # 跨零点保险：页面生成在 00:05，「23:58」其实是昨天的
    base = datetime(2026, 10, 1, 0, 5, tzinfo=_CHINA_TZ)
    assert route.rankm_time("23:58", base) == int(datetime(2026, 9, 30, 23, 58, tzinfo=_CHINA_TZ).timestamp())
    # 只有日期取 0 点；未来日期（跨年）退一年
    assert route.rankm_time("09月27日", _PAGE_NOW) == int(datetime(2026, 9, 27, tzinfo=_CHINA_TZ).timestamp())
    assert route.rankm_time("2025年12月31日", _PAGE_NOW) == int(datetime(2025, 12, 31, tzinfo=_CHINA_TZ).timestamp())
    assert route.rankm_time("乱写的", _PAGE_NOW) is None


def test_ithome_id_accepts_million_plus_links():
    # 需修点：id 过百万后链接是 /1/xxx/xxx.htm，whatshot 既有正则只认 /0/
    assert route.ithome_id("https://www.ithome.com/1/007/340.htm") == "1007340"
    assert route.ithome_id("https://www.ithome.com/0/998/998.htm") == "998998"
    assert route.ithome_id("https://m.ithome.com/html/1008151.htm") == "1008151"
    assert route.ithome_pc_url("1007340") == "https://www.ithome.com/1/007/340.htm"
    assert route.ithome_m_url("998998") == "https://m.ithome.com/html/998998.htm"


# ---------------------------------------------------------------- 频道页 / Office / 喜加一


@pytest.mark.asyncio
async def test_channel_maps_data_ot_and_desc(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://next.ithome.com/"
        return _page_result(CHANNEL_HTML)

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("ithome-ai"), no_cache=True)

    item = result.data[0]
    assert item.id == "1008914"
    assert item.title == "B站开源 Index-Translate 多语言翻译模型家族"  # a[title] 优先
    assert item.url == "https://www.ithome.com/1/008/914.htm"
    assert item.desc == "哔哩哔哩 Index LLM 团队今日正式发布 Index-Translate 模型。"
    assert item.timestamp == int(datetime(2026, 9, 30, 21, 24, 53, tzinfo=_CHINA_TZ).timestamp()) * 1000


@pytest.mark.asyncio
async def test_office_rank_selects_tab_by_name(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://www.ithome.com/block/rank.html?d=office"
        return _page_result(OFFICE_HTML)

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("ithome-office-hot"), no_cache=True)

    assert [item.id for item in result.data] == ["998998", "1000704"]  # d-4（Office热榜），不是日榜 d-1
    assert result.data[0].url == "https://www.ithome.com/0/998/998.htm"
    assert result.data[0].timestamp is None  # Office热榜只有标题和链接


@pytest.mark.asyncio
async def test_xijiayi_parses_million_plus_links_editor_and_jsdate(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://www.ithome.com/zt/xijiayi"
        return _page_result(XIJIAYI_HTML)

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("ithome-xijiayi"), no_cache=True)

    item = result.data[0]
    assert item.id == "1007340"  # 需修点：/1/ 链接正确解析出 id
    assert item.title.startswith("科乐美《恶魔城》系列 IP 迎 40 周年")
    assert item.author == "漾仔"  # .editor「·」前
    assert item.hot == 11  # 「11评」
    assert item.desc == "同时全系列开启多平台特惠，部分作品低至 2 折。"
    assert item.timestamp == int(datetime(2026, 9, 26, 13, 26, 7, tzinfo=_CHINA_TZ).timestamp()) * 1000


# ---------------------------------------------------------------- RSS 与快科技


@pytest.mark.asyncio
async def test_ithome_rss_remaps_id_and_mobile_url(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://www.ithome.com/rss/"
        return RequestResult(True, _UPDATE_TIME, ITHOME_RSS_XML)

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("ithome-latest"), no_cache=False)

    assert result.fromCache is True
    item = result.data[0]
    assert item.id == "1008916"  # RSS 链接里解析出的文章 id
    assert item.url == "https://www.ithome.com/1/008/916.htm"
    assert item.mobileUrl == "https://m.ithome.com/html/1008916.htm"
    assert item.timestamp == int(datetime(2026, 9, 30, 12, 30, tzinfo=UTC).timestamp()) * 1000


@pytest.mark.asyncio
async def test_mydrivers_parses_tab_list_with_read_count(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://www.mydrivers.com/"
        return _page_result(MYDRIVERS_HTML)

    monkeypatch.setattr(route, "get", fake_get)
    result = await route.handle_route(_request("mydrivers-week"), no_cache=True)

    item = result.data[0]
    assert item.id == "1154872"
    assert item.title == "最强麒麟芯 + 展翼新折叠！华为 Mate XT 2 评测"
    assert item.url == "https://news.mydrivers.com/1/1154/1154872.htm"
    assert item.mobileUrl == "https://m.mydrivers.com/newsview/1154872.html"
    assert item.hot == 15774  # 「15774人阅读」
    assert item.cover == "https://img1.mydrivers.com/img/20260930/abc.png"  # data-original，// 补 https
    assert item.timestamp is None  # 快科技三个 tab 的条目页面不显示时间


# ---------------------------------------------------------------- 错误路径


@pytest.mark.asyncio
async def test_unknown_board_and_broken_page_rejected(monkeypatch):
    with pytest.raises(ValueError, match="Unknown board 'nope'"):
        await route.handle_route(_request("nope"), no_cache=True)

    async def fake_broken(url, headers=None, params=None, no_cache=None, **kwargs):
        return _page_result("<div>改版后的页面</div>")

    monkeypatch.setattr(route, "get", fake_broken)
    with pytest.raises(RuntimeError, match="rank-box"):
        await route.handle_route(_request("ithome-month"), no_cache=True)

    async def fake_empty(url, headers=None, params=None, no_cache=None, **kwargs):
        # rank-box 在但没有任何条目：严格拒绝空榜，不降级
        return _page_result('<div class="rank-name" data-rank-type="week-rank">周榜</div><div class="rank-box"></div>')

    monkeypatch.setattr(route, "get", fake_empty)
    with pytest.raises(RuntimeError, match="no items"):
        await route.handle_route(_request("ithome-week"), no_cache=True)

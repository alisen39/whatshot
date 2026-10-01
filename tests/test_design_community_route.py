"""design-community 路由测试（fixtures 依据 board_api design_community 证据净化内联）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import design_community as mod
from whats_hot_api.utils.http_client import RequestResult

# 2026-09-27 19:00:28 UTC,与 board_api 留档 Last-Modified 同型
_LAST_MODIFIED = "Sun, 27 Sep 2026 19:00:28 GMT"


def _request(board_type: str | None) -> Request:
    query = f"type={board_type}".encode() if board_type else b""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/design-community",
            "query_string": query,
            "headers": [],
        }
    )


def _mock_get(body, *, capture: dict | None = None):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        if capture is not None:
            capture.update({"url": url, "headers": headers, "kwargs": kwargs})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", body)

    return fake_get


@pytest.mark.asyncio
async def test_zcool_discover_parses_next_data(monkeypatch):
    """站酷 discover:__NEXT_DATA__ -> listResult.data;idStr 作 id,浏览数作 hot,
    publishTime(毫秒)->timestamp;缺标题/链接的行跳过,同 idStr 去重。"""
    rows = [
        {"content": {"idStr": "ZNzQxOTkyOTY=", "title": "作品一", "pageUrl": "https://www.zcool.com.cn/work/ZNzQxOTkyOTY=.html",
                     "cover": "https://img.zcool.cn/a.png", "creatorObj": {"username": "万鱼鱼"}, "publishTime": 1790493084000, "viewCount": 658}},
        {"content": {"idStr": "ZNzQxOTkyOTY=", "title": "重复作品", "pageUrl": "https://www.zcool.com.cn/work/DUP.html"}},  # 同 id 去重
        {"content": {"title": "缺链接", "idStr": "B"}},
        {"other": {}},  # 无 content
        {"content": {"idStr": "ZNzQ4", "title": "首页推荐里的文章", "pageUrl": "https://www.zcool.com.cn/article/ZNzQ4.html",
                     "publishTime": 0, "viewCount": 3}},
    ]
    html = (
        "<html><head><script id=\"__NEXT_DATA__\" type=\"application/json\">"
        + __import__("json").dumps({"props": {"pageProps": {"listResult": {"data": rows}}}})
        + "</script></head><body></body></html>"
    )
    capture: dict = {}
    monkeypatch.setattr(mod, "get", _mock_get(html, capture=capture))
    result = await mod.handle_route(_request("zcool-editor-picks"), no_cache=True)

    assert capture["url"] == "https://www.zcool.com.cn/discover?recommendLevel=2"
    assert capture["headers"]["User-Agent"].startswith("Mozilla/5.0")  # 站酷对程序 UA 出阿里云 WAF,必须浏览器 UA
    assert result.type == "站酷 · 编辑精选"
    assert result.link == "https://www.zcool.com.cn/discover?recommendLevel=2"
    first, article = result.data[0], result.data[1]
    assert [item.id for item in result.data] == ["ZNzQxOTkyOTY=", "ZNzQ4"]  # 缺链接与重复行跳过
    assert first.author == "万鱼鱼"
    assert first.hot == 658
    assert first.timestamp == 1790493084000  # publishTime 已是毫秒,原样保留
    assert article.url == "https://www.zcool.com.cn/article/ZNzQ4.html"  # 首页推荐夹的文章照样输出
    assert article.timestamp is None  # publishTime=0 无效,留空


@pytest.mark.asyncio
async def test_zcool_rank_maps_datas_and_period(monkeypatch):
    """站酷总榜:type=3/8 接口 datas;链接文件名作 id;只有日期按北京 0 点;期数进 type 标签;
    非 SUCCESS 业务壳报错。"""
    payload = {
        "resultCode": "SUCCESS",
        "tdk": {"title": "站酷总榜设计_创意作品榜_第491期-站酷ZCOOL"},
        "datas": [
            {"rank": 1, "rankingTitle": "数字人民币游戏棋", "pageUrl": "https://www.zcool.com.cn/work/ZNzQxNTMwMDQ=.html",
             "rankingCoverImage": "https://img.zcool.cn/c.png", "member": {"name": "万鱼鱼"},
             "rankingPublishTime": "2026-09-16", "view": 6758},
            {"rank": 2, "rankingTitle": "文章榜条目", "pageUrl": "https://www.zcool.com.cn/article/ZNzQ5.html",
             "rankingPublishTime": "2026/9/15", "view": 120},
        ],
    }
    capture: dict = {}
    monkeypatch.setattr(mod, "get", _mock_get(payload, capture=capture))
    result = await mod.handle_route(_request("zcool-work-rank"), no_cache=True)

    assert capture["url"] == "https://www.zcool.com.cn/p1/ranking/list?p=1&ps=10&type=3"
    assert capture["kwargs"].get("cache_key") == "design-community:zcool-work-rank"
    assert capture["headers"]["Accept"] == mod._ACCEPT_JSON
    assert result.type == "站酷 · 作品总榜 · 第491期"  # 期数来自 tdk.title
    first, second = result.data
    assert first.id == "ZNzQxNTMwMDQ="  # 链接文件名(去 .html)
    assert first.hot == 6758  # 本期浏览数
    expected_ms = int(datetime(2026, 9, 16, tzinfo=mod._BEIJING).timestamp() * 1000)
    assert first.timestamp == expected_ms  # 只有日期,按北京时间 0 点
    assert second.timestamp == int(datetime(2026, 9, 15, tzinfo=mod._BEIJING).timestamp() * 1000)

    async def fake_bad(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"resultCode": "FAIL", "msg": "error"})

    monkeypatch.setattr(mod, "get", fake_bad)
    with pytest.raises(RuntimeError, match="non-SUCCESS"):
        await mod.handle_route(_request("zcool-article-rank"), no_cache=True)


@pytest.mark.asyncio
async def test_uisdc_archives_relative_time_uses_last_modified(monkeypatch):
    """优设所有文章:"N分钟前"以页面生成时刻(Last-Modified)倒推,不用本机当前时间;
    "YYYY/MM/DD"按北京 0 点;"N天前"推不出日期留空;"优设情报"小组件跳过。"""
    html = """
    <html><body>
    <div class="c-items">
      <div class="category-list-item list-item-post">
        <div class="item-thumb item-thumb-post"><i class="thumb"><img src="https://image.uisdc.com/a.webp"/></i></div>
        <div is="meta-read-later" pid="685231"></div>
        <h2 class="item-title"><a title="新文章标题" href="https://www.uisdc.com/design-with-agents">新文章标题</a></h2>
        <i class="meta-time">13分钟前</i>
        <a class="u-info"><i class="u-name">你丫才美工</i></a>
      </div>
      <div class="category-list-item">
        <h2 class="item-title"><a href="https://www.uisdc.com/older-post">日期文章</a></h2>
        <i class="meta-time">2026/09/21</i>
      </div>
      <div class="category-list-item">
        <h2 class="item-title"><a href="https://www.uisdc.com/days-ago">天前文章</a></h2>
        <i class="meta-time">2天前</i>
      </div>
      <div class="category-list-item-news"><h2 class="item-title"><a href="https://www.uisdc.com/news-x">优设情报小组件</a></h2></div>
    </div>
    </body></html>
    """
    wrapped = {"data": html, "status": 200, "headers": {"last-modified": _LAST_MODIFIED, "date": "Sun, 27 Sep 2026 19:20:28 GMT"}}
    monkeypatch.setattr(mod, "get", _mock_get(wrapped))
    result = await mod.handle_route(_request("uisdc-latest"), no_cache=True)

    assert result.type == "优设网 · 所有文章（最新）"
    first, dated, days_ago = result.data
    assert first.id == "685231"  # [pid] 属性作 id
    assert first.title == "新文章标题"
    assert first.author == "你丫才美工"
    assert first.cover == "https://image.uisdc.com/a.webp"
    # 13分钟前:页面生成时刻(19:00:28Z) - 13 分钟,不是本机当前时间
    base = datetime(2026, 9, 27, 19, 0, 28, tzinfo=UTC)
    assert first.timestamp == int(base.timestamp() * 1000) - 13 * 60 * 1000
    assert dated.timestamp == int(datetime(2026, 9, 21, tzinfo=mod._BEIJING).timestamp() * 1000)
    assert days_ago.timestamp is None  # "N天前"只知道 N~N+1 天前,留空不编
    assert len(result.data) == 3  # "优设情报"小组件不算条目


@pytest.mark.asyncio
async def test_uisdc_hot_posts_maps_views_and_date(monkeypatch):
    """优设热文榜单:"2.8w 阅读"->28000;日期按北京 0 点;封面取 .thumb 的 background-image。"""
    html = """
    <html><body><div class="p-items">
      <div class="p-item">
        <h2 class="item-title"><a href="https://www.uisdc.com/hot-one">热文一</a></h2>
        <p class="item-entry">摘要一</p>
        <span class="meta-author"><a href="/u/1">作者甲</a></span>
        <span class="meta-views">2.8w 阅读</span>
        <span class="meta-date">2026-09-15</span>
        <div class="item-thumb"><div class="thumb" style="background-image:url(https://image.uisdc.com/hot.png);"></div></div>
      </div>
      <div class="p-item">
        <h2 class="item-title"><a href="https://www.uisdc.com/hot-two">热文二</a></h2>
        <span class="meta-views">956 阅读</span>
      </div>
    </div></body></html>
    """
    monkeypatch.setattr(mod, "get", _mock_get(html))
    result = await mod.handle_route(_request("uisdc-hot-posts"), no_cache=True)

    assert result.type == "优设网 · 热文榜单"
    first, second = result.data
    assert first.id == "hot-one"
    assert first.hot == 28000  # "2.8w 阅读" -> 28000
    assert first.author == "作者甲"
    assert first.desc == "摘要一"
    assert first.cover == "https://image.uisdc.com/hot.png"  # background-image
    assert first.timestamp == int(datetime(2026, 9, 15, tzinfo=mod._BEIJING).timestamp() * 1000)
    assert second.hot == 956  # 无 w 后缀按原数
    assert second.timestamp is None and second.cover is None


@pytest.mark.asyncio
async def test_uisdc_hunter_uses_title_attr_and_strips_prefix(monkeypatch):
    """细节猎人:标题取 a 的 title 属性(链接文字前多分类标签);作者去"猎人 - "前缀;
    data-pid 作 id;列表不显示时间 timestamp 留空;"产品榜"小组件(无 h2.item-title)跳过。"""
    html = """
    <html><body><div class="hunter-list"><div class="items">
      <div class="hunter-list-item" data-pid="99001">
        <div class="item-thumb"><img src="https://image.uisdc.com/h1.png"/></div>
        <h2 class="item-title"><a title="猎人文案标题" href="https://www.uisdc.com/hunter/99001"><span class="tag">用户体验</span>猎人文案标题</a></h2>
        <div class="hunter-entry"><p>细节摘要</p></div>
        <div class="meta-author"><span class="prefix">猎人 - </span>猎人甲</div>
      </div>
      <div class="hunter-list-item"><div>产品榜小组件没有标题链接</div></div>
    </div></div></body></html>
    """
    monkeypatch.setattr(mod, "get", _mock_get(html))
    result = await mod.handle_route(_request("uisdc-hunter-hot"), no_cache=True)

    assert result.type == "优设网 · 细节猎人 · 最热门"
    assert len(result.data) == 1
    item = result.data[0]
    assert item.id == "99001"  # data-pid
    assert item.title == "猎人文案标题"  # title 属性,不带"用户体验"标签
    assert item.desc == "细节摘要"
    assert item.author == "猎人甲"  # "猎人 - "前缀去掉
    assert item.cover == "https://image.uisdc.com/h1.png"
    assert item.timestamp is None and item.hot is None  # 列表不显示时间,评分不是热度


@pytest.mark.asyncio
async def test_itsnicethat_props_edges(monkeypatch):
    """It's Nice That:props 的 data.page.items.edges[].node;slug 作 id;standfirst 去 HTML;
    publicationDate 转毫秒。props 缺失报错(页面改版,不静默降级)。"""
    node_html = "<p>standfirst <b>bold</b></p>"
    props = {
        "data": {
            "page": {
                "items": {
                    "edges": [
                        {"node": {"title": "Mestiza Estudio built this", "url": "/articles/mestiza-studio-canica-240926",
                                  "publicationDate": "2026-09-24T09:00:00+00:00", "standfirst": node_html,
                                  "listingImage": {"url": "https://www.itsnicethat.com/img.jpg"}}},
                        {"node": {"title": "无链接的不算", "url": ""}},
                    ]
                }
            }
        }
    }
    import json as jsonlib

    html = f'<html><head><script id="props" type="application/json">{jsonlib.dumps(props)}</script></head><body></body></html>'
    monkeypatch.setattr(mod, "get", _mock_get(html))
    result = await mod.handle_route(_request("itsnicethat-articles"), no_cache=True)

    assert result.type == "It's Nice That · Work"
    item = result.data[0]
    assert item.id == "mestiza-studio-canica-240926"  # url 最后一段 slug
    assert item.url == "https://www.itsnicethat.com/articles/mestiza-studio-canica-240926"
    assert item.desc == "standfirst bold"
    assert item.cover == "https://www.itsnicethat.com/img.jpg"
    assert item.timestamp == int(datetime(2026, 9, 24, 9, 0, tzinfo=UTC).timestamp() * 1000)

    async def fake_no_props(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html><body>改版了</body></html>")

    monkeypatch.setattr(mod, "get", fake_no_props)
    with pytest.raises(RuntimeError, match="no <script id=props>"):
        await mod.handle_route(_request("itsnicethat-articles"), no_cache=True)


@pytest.mark.asyncio
async def test_feed_boards_use_rss_and_browser_headers(monkeypatch):
    """Behance/designboom/数英 3 个 RSS 榜:浏览器 UA + feed Accept;保留 feed 原顺序。"""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        "<item><title>旧条目</title><link>https://www.behance.net/gallery/1/x</link><guid>https://www.behance.net/gallery/1/x</guid>"
        "<pubDate>Mon, 21 Sep 2026 08:00:00 GMT</pubDate></item>"
        "<item><title>新条目</title><link>https://www.behance.net/gallery/2/y</link>"
        "<pubDate>Tue, 22 Sep 2026 08:00:00 GMT</pubDate></item>"
        "</channel></rss>"
    )
    capture: dict = {}
    monkeypatch.setattr(mod, "get", _mock_get(xml, capture=capture))
    result = await mod.handle_route(_request("behance-featured"), no_cache=True)

    assert capture["url"] == "https://www.behance.net/feeds/projects"
    assert capture["headers"]["Accept"] == mod._ACCEPT_FEED
    assert capture["headers"]["User-Agent"].startswith("Mozilla/5.0")  # Behance 对程序 UA 403
    assert result.type == "Behance · Featured Projects"
    assert [item.title for item in result.data] == ["旧条目", "新条目"]  # feed 原顺序
    assert result.data[0].id == "https://www.behance.net/gallery/1/x"  # guid 作 id


@pytest.mark.asyncio
async def test_default_board_unknown_type_and_aliyun_waf(monkeypatch):
    """默认榜 = 声明序第一个 zcool-editor-picks;未知 type 拒绝;阿里云 WAF 挑战壳报错不绕。"""
    async def fake_waf(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", '<html><form name="aliyun_waf_aa">challenge</form></html>')

    async def fake_ok(url, headers=None, no_cache=None, **kwargs):
        html = (
            "<script id=\"__NEXT_DATA__\" type=\"application/json\">"
            + __import__("json").dumps({"props": {"pageProps": {"listResult": {"data": [
                {"content": {"idStr": "A", "title": "默认榜条目", "pageUrl": "https://www.zcool.com.cn/work/A.html"}}
            ]}}}})
            + "</script>"
        )
        return RequestResult(False, "t", html)

    monkeypatch.setattr(mod, "get", fake_ok)
    result = await mod.handle_route(_request(None), no_cache=True)
    assert next(iter(mod.type_map)) == "zcool-editor-picks"  # 声明序第一个是默认榜
    assert result.type == "站酷 · 编辑精选" and result.total == 1

    with pytest.raises(ValueError, match="Unknown board"):
        await mod.handle_route(_request("dribbble-popular"), no_cache=True)  # Dribbble 是不做的榜

    monkeypatch.setattr(mod, "get", fake_waf)
    with pytest.raises(RuntimeError, match="Aliyun WAF"):
        await mod.handle_route(_request("zcool-home-picks"), no_cache=True)

"""chinanews-channels 路由测试:fixtures 依据 board_api 证据目录 tmp/board_api/chinanews_channels 净化。

- RSS:evidence/01_rss_sports.response.body(item 只有 title/link/description/pubDate,无 guid)
- 滚动列表页:evidence/03_china_shtml.response.body(.content_list li / .dd_bt / .dd_time)
- 首页区块:evidence/02_home.response.body.gz(div.lmtitle + div.rdph-list2,title 属性)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import chinanews_channels
from whats_hot_api.utils.http_client import RequestResult

_BEIJING = timezone(timedelta(hours=8))
_UPDATE_TIME = "2026-09-28T00:00:00+00:00"


def _request(board_type: str | None = None) -> Request:
    query = f"type={board_type}" if board_type else ""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/chinanews-channels",
        "query_string": query.encode(),
        "headers": [],
    })


def _ok(data: Any) -> RequestResult:
    return RequestResult(False, _UPDATE_TIME, data)


def _ms(y: int, m: int, d: int, hour: int = 0, minute: int = 0, second: int = 0) -> int:
    return int(datetime(y, m, d, hour, minute, second, tzinfo=_BEIJING).timestamp() * 1000)


# 官方 RSS:两条文章 + 一条指向频道页自身的导航条目(life.xml 曾出现)
_SPORTS_RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<title>中新网体育新闻</title><link>http://www.chinanews.com/sportchannel/index.shtml</link>
<item><title>2026中俄国际足球邀请赛在沪开赛</title>
<link>https://www.chinanews.com.cn/ty/2026/09-27/10704633.shtml</link>
<description>
　　中新社上海9月27日电 (记者 缪璐)2026中俄国际足球邀请赛27日晚间在上海市金山体育中心打响。</description>
<pubDate>Sun, 27 Sep 2026 23:56:05 +0800</pubDate></item>
<item><title>捷克队夺2026比利·简·金杯女网团体冠军</title>
<link>https://www.chinanews.com.cn/ty/2026/09-27/10704620.shtml</link>
<description>&lt;p&gt;中新社深圳9月27日电 捷克队以2:0战胜乌克兰队,夺得冠军。&lt;/p&gt;</description>
<pubDate>Sun, 27 Sep 2026 23:11:53 +0800</pubDate></item>
<item><title>体育频道首页</title><link>https://www.chinanews.com.cn/sports/</link>
<description>频道页自身,不算条目</description>
<pubDate>Sun, 27 Sep 2026 20:00:00 +0800</pubDate></item>
</channel></rss>
"""

# 国内新闻滚动页:两条条目 + 一条分隔线空 li + 一条重复链接
_CHINA_PAGE = """<html><body><div class="content_list"><ul>
<li><div class="dd_lm">[国内]</div> <div class="dd_bt"><a href="/gn/2026/09-27/10704546.shtml">韩正在第81届联大一般性辩论上的讲话(全文)</a></div><div class="dd_time">9-27 22:20</div></li>
<li id="konge"></li>
<li><div class="dd_lm">[国内]</div> <div class="dd_bt"><a href="/gn/2026/09-27/10704600.shtml">良法善治·回响|何以"跟进一步"</a></div><div class="dd_time">9-27 22:15</div></li>
<li><div class="dd_lm">[国内]</div> <div class="dd_bt"><a href="https://www.chinanews.com.cn/gn/2026/09-27/10704546.shtml">韩正在第81届联大一般性辩论上的讲话(全文)</a></div><div class="dd_time">9-27 22:20</div></li>
</ul></div></body></html>
"""

# 首页:中新热榜区块 + 热门图片区块(链接文字被截断,完整标题在 title 属性)
_HOME_PAGE = """<html><body>
<div class="rdph-title lmtitle" id="zxrb"><span class="mt10">中新热榜</span></div>
<div class="rdph-list rdph-list2"><ul>
<li><a href="//www.chinanews.com.cn/gj/2026/09-27/10704315.shtml" target="_blank" title="欧盟承诺向撒哈拉以南非洲及巴勒斯坦等国提供逾7亿欧元援助">欧盟承诺向撒哈拉以南非洲及巴勒斯坦等国...</a></li>
<li><a href="//www.chinanews.com.cn/sh/2026/09-27/10704320.shtml" target="_blank" title="华西至黄淮江淮多降水 中东部地区将有大风降温过程">华西至黄淮江淮多降水 中东部地区将有大...</a></li>
</ul></div>
<div class="rdph-title lmtitle" id="rmtp"><span>热门图片</span></div>
<div class="rdph-list rdph-list2"><ul>
<li><a href="//www.chinanews.com.cn/tp/hd2011/2026/09-27/1206069.shtml" target="_blank" title="(爱知·名古屋亚运会)林诗栋蒯曼夺得乒乓球混双冠军">(爱知·名古屋亚运会)林诗栋蒯曼夺得乒...</a></li>
</ul></div>
</body></html>
"""


async def test_rss_board_maps_fields(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _ok(_SPORTS_RSS)

    monkeypatch.setattr(chinanews_channels, "get", fake_get)
    result = await chinanews_channels.handle_route(_request("sports"), no_cache=True)

    assert captured["url"] == "https://www.chinanews.com.cn/rss/sports.xml"
    assert captured["kwargs"]["no_cache"] is True
    assert result.type == "体育新闻"
    assert result.total == 2  # 指向频道页自身的条目被过滤
    first = result.data[0]
    assert first.id == "https://www.chinanews.com.cn/ty/2026/09-27/10704633.shtml"  # 无 guid,id 取 link
    assert first.title == "2026中俄国际足球邀请赛在沪开赛"
    assert first.url == first.mobileUrl == first.id
    assert first.timestamp == _ms(2026, 9, 27, 23, 56, 5)  # pubDate +0800,毫秒
    assert first.desc == "中新社上海9月27日电 (记者 缪璐)2026中俄国际足球邀请赛27日晚间在上海市金山体育中心打响。"
    second = result.data[1]
    assert second.desc == "中新社深圳9月27日电 捷克队以2:0战胜乌克兰队,夺得冠军。"  # 描述里的 HTML 已去掉
    assert second.timestamp == _ms(2026, 9, 27, 23, 11, 53)
    assert result.updateTime == _UPDATE_TIME
    assert result.fromCache is False


async def test_china_page_maps_timestamp_and_dedupes(monkeypatch):
    async def fake_get(url, **kwargs):
        assert url == "https://www.chinanews.com.cn/china.shtml"
        return _ok(_CHINA_PAGE)

    monkeypatch.setattr(chinanews_channels, "get", fake_get)
    result = await chinanews_channels.handle_route(_request("china"), no_cache=False)

    assert result.type == "国内新闻"
    assert result.total == 2  # 分隔线空 li 跳过;重复链接只留第一次
    first = result.data[0]
    assert first.title == "韩正在第81届联大一般性辩论上的讲话(全文)"
    assert first.url == "https://www.chinanews.com.cn/gn/2026/09-27/10704546.shtml"
    assert first.timestamp == _ms(2026, 9, 27, 22, 20)  # 地址年月日 + .dd_time 时:分,北京时间
    assert first.desc is None  # 页面列表没有摘要
    assert result.data[1].timestamp == _ms(2026, 9, 27, 22, 15)


async def test_home_block_targets_requested_block(monkeypatch):
    async def fake_get(url, **kwargs):
        assert url == "https://www.chinanews.com.cn/"
        return _ok(_HOME_PAGE)

    monkeypatch.setattr(chinanews_channels, "get", fake_get)
    result = await chinanews_channels.handle_route(_request("photo-hot"), no_cache=True)

    assert result.type == "热门图片"
    assert result.total == 1  # 只取"热门图片"区块,不串到"中新热榜"
    item = result.data[0]
    assert item.id == "https://www.chinanews.com.cn/tp/hd2011/2026/09-27/1206069.shtml"
    assert item.title == "(爱知·名古屋亚运会)林诗栋蒯曼夺得乒乓球混双冠军"  # title 属性,不是截断文字
    assert item.timestamp == _ms(2026, 9, 27)  # 只有地址日期,北京时间当天 0 点


async def test_home_missing_block_is_error(monkeypatch):
    async def fake_get(url, **kwargs):
        return _ok("<html><body>改版后的首页,没有右栏热榜区块</body></html>")

    monkeypatch.setattr(chinanews_channels, "get", fake_get)
    with pytest.raises(RuntimeError, match="中新热榜"):
        await chinanews_channels.handle_route(_request("hot"), no_cache=True)


async def test_empty_parse_is_error(monkeypatch):
    # RSS 结构正常但全部条目都指向频道页自身 -> 解析结果为空,报错而不是空榜
    channel_only_rss = (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
        "<title>中新网体育新闻</title>"
        "<item><title>体育频道首页</title>"
        "<link>https://www.chinanews.com.cn/sports/</link>"
        "<description>频道页自身,不算条目</description></item>"
        "</channel></rss>"
    )

    async def fake_get_no_items(url, **kwargs):
        return _ok(channel_only_rss)

    monkeypatch.setattr(chinanews_channels, "get", fake_get_no_items)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await chinanews_channels.handle_route(_request("sports"), no_cache=True)

    # 滚动页结构被改掉(.content_list 没了)同样报错
    async def fake_get_broken(url, **kwargs):
        return _ok("<html><body>维护中</body></html>")

    monkeypatch.setattr(chinanews_channels, "get", fake_get_broken)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await chinanews_channels.handle_route(_request("scroll"), no_cache=True)


async def test_unknown_type_is_rejected(monkeypatch):
    async def fake_get(url, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("unknown type 不应发起上游请求")

    monkeypatch.setattr(chinanews_channels, "get", fake_get)
    with pytest.raises(ValueError, match="Unknown board"):
        await chinanews_channels.handle_route(_request("ent"), no_cache=True)


def test_board_table_matches_board_api():
    """16 个子榜与 board_api 同构;声明序第一个(hot,中新热榜)是默认榜。"""
    assert list(chinanews_channels._BOARDS) == [
        "hot", "photo-hot", "video-hot", "importnews", "scroll", "scroll-rss",
        "china", "china-rss", "world", "society", "finance", "life",
        "dwq", "chinese", "culture", "sports",
    ]
    assert chinanews_channels._DEFAULT_TYPE == "hot"
    assert next(iter(chinanews_channels.type_map)) == "hot"
    # 取数方式:3 个首页区块、2 个滚动页、11 个 RSS
    kinds = [board[1] for board in chinanews_channels._BOARDS.values()]
    assert kinds.count("home") == 3
    assert kinds.count("page") == 2
    assert kinds.count("rss") == 11

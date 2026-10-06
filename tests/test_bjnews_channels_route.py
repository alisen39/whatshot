"""bjnews-channels 路由测试:fixtures 依据 board_api 证据目录 tmp/board_api/bjnews_channels 净化。

- 首页三区块:evidence/01_home(推荐瀑布流 / 排行 / 热评,HTML 注释定位)
- 频道页:evidence/02_channel_beijing(#waterfall-container 瀑布流)
- 手机版数据接口:evidence/10_m_api_beijing(uuid -> publish_time)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import bjnews_channels
from whats_hot_api.utils.http_client import RequestResult

_BEIJING = timezone(timedelta(hours=8))
_UPDATE_TIME = "2026-09-28T00:00:00+00:00"


def _request(board_type: str | None = None) -> Request:
    query = f"type={board_type}" if board_type else ""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/bjnews-channels",
        "query_string": query.encode(),
        "headers": [],
    })


def _ok(data: Any) -> RequestResult:
    return RequestResult(False, _UPDATE_TIME, data)


def _pin(url: str, title: str, *, cover: str = "", desc: str = "", see: str = "", badge: bool = False) -> str:
    badge_html = '<span class="zt_tit">专题</span>' if badge else ""
    cover_html = f'<div class="imgBor"><a href="{url}"><img src="{cover}"></a></div>' if cover else ""
    desc_html = f'<div class="pin_tips"><a class="noPadd" href="{url}">{desc} <i>[全文]</i></a></div>' if desc else ""
    see_html = f'<div class="bom"><span class="source">北京快闻</span><span class="see">{see}</span></div>'
    return f'<div class="pin_demo"><a href="{url}"><div class="pin_tit">{badge_html}{title}</div></a>{cover_html}{desc_html}{see_html}</div>'


# 首页:推荐瀑布流 + 右栏排行(带热度)+ 热评(com 是相对时间)
_HOME_PAGE = f"""<html><body>
<!-- 推荐s --><div class="fl recommend"><div id="waterfall-container">
{_pin("https://www.bjnews.com.cn/detail/1790518660129966.html", "41金11银4铜,中国创参加世界技能大赛最好成绩",
      cover="https://media.bjnews.com.cn/cover/2026/09/27/a.png", see="5571")}
{_pin("https://m.bjnews.com.cn/h5special/1789790866129405.html", "开学第一课专题", badge=True,
      cover="https://media.bjnews.com.cn/image/2026/09/19/b.jpg", desc="36位产业一线科技人才将走进近30所在京高校。")}
{_pin("https://www.bjnews.com.cn/detail/1790518660129966.html", "重复链接的卡片")}
</div></div><!-- 推荐e -->
<!-- 排行s --><div class="hotComment ranking"><ul class="list1">
<li class="active"><h3><a class="link" href="https://www.bjnews.com.cn/detail/1790506284129874.html">
<span class="num">1</span> 战胜日本队,黄友政/林诗栋夺得亚运会乒乓球男双冠军</a></h3>
<div class="img"><a href="https://www.bjnews.com.cn/detail/1790506284129874.html">
<img src="https://media.bjnews.com.cn/cover/2026/09/27/c.jpeg"></a></div>
<div class="tips"><span class="source">第一看点</span><span class="com"><i class="pai"></i>11.5万</span></div></li>
</ul></div><!-- 排行e -->
<!-- 热评s --><div class="hotComment"><ul class="list1">
<li><h3><a class="link" href="https://www.bjnews.com.cn/detail/1790464474129671.html">
<span class="num">1</span> 大熊猫"平平""福双"已启程赴美</a></h3>
<div class="img"><img src="https://media.bjnews.com.cn/cover/2026/09/27/d.jpeg"></div>
<div class="tips"><span class="source">第一看点</span><span class="com"><i class="time"></i>20小时前</span></div></li>
</ul></div><!-- 热评e -->
</body></html>
"""

# 北京频道页:两条卡片
_BEIJING_PAGE = f"""<html><body><div id="waterfall-container">
{_pin("https://www.bjnews.com.cn/detail/1790510651129912.html", "中秋假期北京127家重点商企入账40.4亿元,同比增长20%",
      cover="https://media.bjnews.com.cn/cover/2026/09/27/e.jpeg", see="1.5万")}
{_pin("https://www.bjnews.com.cn/detail/1790491858129793.html", "北京发布中秋假期交通提示", see="1.0万")}
</div></body></html>
"""

# 手机版数据接口(uuid 是数字,key 与北京频道页对应,外加一条串频道的缓存)
_M_API_PAYLOAD = {
    "status": 1,
    "info": "ok",
    "data": [
        {"uuid": "1790518660129966", "title": "41金11银4铜,中国创参加世界技能大赛最好成绩",
         "publish_time": "2026-09-27 20:32:43", "column_info": {"channel_id": ""}},
        {"uuid": 1790510651129912, "title": "中秋假期北京127家重点商企入账40.4亿元,同比增长20%",
         "publish_time": "2026-09-27 20:32:43", "column_info": {"channel_id": "4"}},
        {"uuid": "1790999999999999", "title": "别的频道的缓存稿", "publish_time": "2026-09-27 19:00:00",
         "column_info": {"channel_id": "10"}},
    ],
}


async def test_home_recommend_maps_fields_and_supplements_time(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(url, **kwargs):
        if url.startswith("https://m.bjnews.com.cn/"):
            captured["m_api"] = url
            return _ok(_M_API_PAYLOAD)
        captured["url"] = url
        return _ok(_HOME_PAGE)

    monkeypatch.setattr(bjnews_channels, "get", fake_get)
    result = await bjnews_channels.handle_route(_request("home-recommend"), no_cache=True)

    assert captured["url"] == "https://www.bjnews.com.cn/"
    # 首页推荐对应手机版首页推荐:channel_id 为空串
    assert captured["m_api"] == "https://m.bjnews.com.cn/bwnew/index-tj?page=1&size=20&channel_id=&wz_id=1"
    assert result.type == "首页推荐"
    assert result.total == 2  # 重复链接的卡片去重
    first = result.data[0]
    assert first.id == "1790518660129966"  # 链接里的 16 位 uuid
    assert first.title == "41金11银4铜,中国创参加世界技能大赛最好成绩"
    assert first.url == "https://www.bjnews.com.cn/detail/1790518660129966.html"
    assert first.cover == "https://media.bjnews.com.cn/cover/2026/09/27/a.png"
    assert first.hot == 5571  # .bom .see 阅读量
    expected = int(datetime(2026, 9, 27, 20, 32, 43, tzinfo=_BEIJING).timestamp() * 1000)
    assert first.timestamp == expected  # m 接口 publish_time(北京时间),毫秒

    second = result.data[1]
    assert second.id == "1789790866129405"  # H5 专题链接的 uuid
    assert second.title == "开学第一课专题"  # "专题"角标(.zt_tit)不进标题
    assert second.url == "https://m.bjnews.com.cn/h5special/1789790866129405.html"  # 专题照页面链接
    assert second.desc == "36位产业一线科技人才将走进近30所在京高校。"  # 去掉"[全文]"
    assert second.timestamp is None  # 接口里没有这条(手机版首页推荐 15 里 14 条相同)


async def test_channel_board_maps_fields_and_filters_foreign_cache(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(url, **kwargs):
        if url.startswith("https://m.bjnews.com.cn/"):
            return _ok(_M_API_PAYLOAD)
        captured["url"] = url
        return _ok(_BEIJING_PAGE)

    monkeypatch.setattr(bjnews_channels, "get", fake_get)
    result = await bjnews_channels.handle_route(_request("beijing"), no_cache=True)

    assert captured["url"] == "https://www.bjnews.com.cn/beijing"
    assert result.type == "北京"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "1790510651129912"
    assert first.hot == 15000  # "1.5万" → 15000
    assert first.timestamp == int(datetime(2026, 9, 27, 20, 32, 43, tzinfo=_BEIJING).timestamp() * 1000)
    second = result.data[1]
    assert second.timestamp is None  # 接口里没有(串频道的缓存稿按 uuid 对不上)
    assert "1 条没有对上手机版数据接口的发布时间" in (result.message or "")


async def test_ranking_maps_hot_and_drops_rank_number(monkeypatch):
    urls: list[str] = []

    async def fake_get(url, **kwargs):
        urls.append(url)
        return _ok(_HOME_PAGE)

    monkeypatch.setattr(bjnews_channels, "get", fake_get)
    result = await bjnews_channels.handle_route(_request("ranking"), no_cache=True)

    assert urls == ["https://www.bjnews.com.cn/"]  # 排行、热评没有对应接口,不请求 m 站
    assert result.total == 1
    item = result.data[0]
    assert item.id == "1790506284129874"
    assert item.title == "战胜日本队,黄友政/林诗栋夺得亚运会乒乓球男双冠军"  # span.num 名次已去掉
    assert item.hot == 115000  # "11.5万" → 115000
    assert item.cover == "https://media.bjnews.com.cn/cover/2026/09/27/c.jpeg"
    assert item.timestamp is None  # 排行没有时间


async def test_hot_comment_relative_time_is_not_hot(monkeypatch):
    async def fake_get(url, **kwargs):
        return _ok(_HOME_PAGE)

    monkeypatch.setattr(bjnews_channels, "get", fake_get)
    result = await bjnews_channels.handle_route(_request("hot-comment"), no_cache=True)

    item = result.data[0]
    assert item.title == "大熊猫\"平平\"\"福双\"已启程赴美"
    assert item.hot is None  # 热评的 span.com 是"20小时前",不是热度
    assert result.message is None  # 没有 channel_id,不补时间也就没有缺时间提示


async def test_m_api_failure_degrades_without_times(monkeypatch):
    async def fake_get(url, **kwargs):
        if url.startswith("https://m.bjnews.com.cn/"):
            raise RuntimeError("upstream boom")
        return _ok(_BEIJING_PAGE)

    monkeypatch.setattr(bjnews_channels, "get", fake_get)
    result = await bjnews_channels.handle_route(_request("beijing"), no_cache=True)

    assert result.total == 2  # 接口失败只是不补时间,条目照常输出(证据口径)
    assert all(item.timestamp is None for item in result.data)
    assert "2 条没有对上" in (result.message or "")


async def test_home_missing_block_is_error(monkeypatch):
    async def fake_get(url, **kwargs):
        return _ok("<html><body>改版后的首页,没有推荐区块注释</body></html>")

    monkeypatch.setattr(bjnews_channels, "get", fake_get)
    with pytest.raises(RuntimeError, match="推荐"):
        await bjnews_channels.handle_route(_request("home-recommend"), no_cache=True)


async def test_broken_channel_page_and_empty_parse_are_errors(monkeypatch):
    async def fake_get(url, **kwargs):
        if "waterfall" in kwargs.get("marker", ""):  # pragma: no cover
            pass
        return _ok("<html><body>维护中</body></html>")

    monkeypatch.setattr(bjnews_channels, "get", fake_get)
    with pytest.raises(RuntimeError, match="waterfall-container"):
        await bjnews_channels.handle_route(_request("news"), no_cache=True)

    async def fake_get_empty(url, **kwargs):
        return _ok('<html><body><div id="waterfall-container"></div></body></html>')

    monkeypatch.setattr(bjnews_channels, "get", fake_get_empty)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await bjnews_channels.handle_route(_request("news"), no_cache=True)


async def test_unknown_type_is_rejected(monkeypatch):
    async def fake_get(url, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("unknown type 不应发起上游请求")

    monkeypatch.setattr(bjnews_channels, "get", fake_get)
    with pytest.raises(ValueError, match="Unknown board"):
        await bjnews_channels.handle_route(_request("life"), no_cache=True)


def test_board_table_matches_board_api():
    """10 个子榜与 board_api 同构;声明序第一个(home-recommend)是默认榜。"""
    assert list(bjnews_channels.BOARDS) == [
        "home-recommend", "ranking", "hot-comment", "news", "zhengshi", "beijing",
        "guoji", "entertainment", "education", "technology",
    ]
    assert bjnews_channels._DEFAULT_TYPE == "home-recommend"
    assert next(iter(bjnews_channels.type_map)) == "home-recommend"
    # 只有排行、热评没有手机版数据接口
    assert [k for k, v in bjnews_channels.BOARDS.items() if v[3] is None] == ["ranking", "hot-comment"]

"""zaobao 路由测试:fixtures 依据 board_api 证据目录 tmp/board_api/zaobao_channels 净化。

- 栏目页:evidence/01_realtime_china、01_news_china(<main> article 卡片、HotNews 岛、
  LoadMoreList 岛 props、卡片时间位几种写法)
- 详情页:evidence/04_detail_9746073(JSON-LD datePublished)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import zaobao
from whats_hot_api.utils.http_client import RequestResult

_SGT = timezone(timedelta(hours=8))
_UPDATE_TIME = "2026-09-28T00:00:00+00:00"
# 页面渲染时刻的估计(测试固定,替代 _now_sgt)
_NOW = datetime(2026, 9, 28, 7, 59, 0, tzinfo=_SGT)


def _request(board_type: str | None = None) -> Request:
    query = f"type={board_type}" if board_type else ""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/zaobao",
        "query_string": query.encode(),
        "headers": [],
    })


def _ok(data: Any) -> RequestResult:
    return RequestResult(False, _UPDATE_TIME, data)


def _ms(y: int, m: int, d: int, hour: int = 0, minute: int = 0, second: int = 0) -> int:
    return int(datetime(y, m, d, hour, minute, second, tzinfo=_SGT).timestamp() * 1000)


def _card(href: str, title: str, *, span: str = "9月27日", img: str = "", article_link: bool = True) -> str:
    link_cls = "article-link " if article_link else ""
    img_html = f'<div class="picture"><img src="{img}"></div>' if img else ""
    return (
        f'<article class="relative"><div class="flex"><div class="flex-1">'
        f'<a class="{link_cls}text-lg" href="{href}" title="{title}">{title[:12]}…</a>'
        f'{img_html}</div><div class="text-xs"><span>{span}</span></div></div></article>'
    )


def _island(component: str, props: str, inner: str) -> str:
    return f'<astro-island component-url="https://dss0.zbstatic5.com/web2/_astro/{component}" props=\'{props}\'>{inner}</astro-island>'


_LOADMORE_PROPS = (
    '{"pageType":[0,"sitemap"],"list":[1,[[0,'
    '{"id":[0,9742894],"title":[0,"报告：韩中自贸协定贡献不及预期"],'
    '"publicationDate":[0,"2026-09-27 12:28:00"],'
    '"url":[0,"/news/china/story20260927-9742894"]}]]]}'
)

# /realtime/china:3 张静态卡片("M月D日"、"HH:MM"、"N分钟前")+ 侧栏热门岛 +
# LoadMoreList 岛(岛里 1 张服务端渲染的卡片,props 带 publicationDate)
_REALTIME_CHINA_PAGE = f"""<html><body><main class="mx-auto"><h1>中国</h1>
<div data-testid="article-list">
{_card("/news/china/story20260927-9745158", "世界技能大赛上海闭幕 中国41金创参赛最好成绩", img="https://dss0.zbstatic5.com/image/a.jpg")}
{_card("/news/china/story20260928-9745502", "新加坡部长访谈录", span="05:00")}
{_card("/news/china/story20260928-9746188", "美联储主席表态", span="15分钟前")}
</div>
{_island("HotNews.CSPtXRlS.js", '{"className":[0,"order-4"]}',
          _card("/news/china/story20260901-9700001", "侧栏热门:全站热榜,应排除", article_link=False))}
{_island("LoadMoreList.UMwZWXg-.js", _LOADMORE_PROPS,
          _card("/news/china/story20260927-9742894", "报告：韩中自贸协定贡献不及预期"))}
</main></body></html>
"""

# /finance/china:2 张带图卡片
_FINANCE_CHINA_PAGE = f"""<html><body><main class="mx-auto"><h1>中国财经新闻</h1>
<div data-testid="article-list">
{_card("/finance/china/story20260927-9745001", "人民币中间价上调", span="9月26日", img="https://dss0.zbstatic5.com/image/b.jpg")}
{_card("/finance/china/story20260927-9745002", "A股节后前瞻", span="06:30")}
</div>
</main></body></html>
"""

_DETAIL_PAGE = '<html><head><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-09-28T07:41:00+08:00","author":{"name":"联合早报"}}</script></head><body>正文</body></html>'
_DETAIL_MS = _ms(2026, 9, 28, 7, 41, 0)


def _stub_upstream(monkeypatch, html: str, captured: dict[str, Any] | None = None, *, detail: str | Exception = _DETAIL_PAGE) -> None:
    async def fake_get(url, **kwargs):
        if captured is not None:
            captured.setdefault("urls", []).append(url)
        if "/story" in url:  # 详情页
            if isinstance(detail, Exception):
                raise detail
            return _ok(detail)
        return _ok(html)

    monkeypatch.setattr(zaobao, "get", fake_get)
    monkeypatch.setattr(zaobao, "_now_sgt", lambda: _NOW)


async def test_default_realtime_china_maps_fields(monkeypatch):
    """缺省(无 type)= 即时中国,仍是旧路由的 /realtime/china 页面;字段映射与排除逻辑。"""
    captured: dict[str, Any] = {}
    _stub_upstream(monkeypatch, _REALTIME_CHINA_PAGE, captured)
    result = await zaobao.handle_route(_request(), no_cache=True)

    assert captured["urls"][0] == "https://www.zaobao.com/realtime/china"
    assert result.type == "即时中国"
    assert result.total == 4  # 3 张静态卡片 + 岛里 1 张;侧栏热门已排除
    first = result.data[0]
    assert first.id == "/news/china/story20260927-9745158"  # id 是站内路径
    assert first.title == "世界技能大赛上海闭幕 中国41金创参赛最好成绩"  # title 属性,不是截断文字
    assert first.url == first.mobileUrl == "https://www.zaobao.com/news/china/story20260927-9745158"
    assert first.cover == "https://dss0.zbstatic5.com/image/a.jpg"
    assert first.timestamp == _ms(2026, 9, 27)  # "M月D日" -> 该日 0 点(新加坡时间)
    second = result.data[1]
    assert second.timestamp == _ms(2026, 9, 28, 5, 0)  # "HH:MM" -> 渲染当天该时刻
    third = result.data[2]
    assert third.timestamp == _DETAIL_MS  # "N分钟前" -> 详情页 datePublished
    island_row = result.data[3]
    assert island_row.id == "/news/china/story20260927-9742894"
    assert island_row.timestamp == _ms(2026, 9, 27, 12, 28, 0)  # LoadMoreList 岛 props,精确到秒
    assert result.message is None  # 详情页取到了,没有缺时间提示


async def test_relative_card_fetches_detail_page(monkeypatch):
    captured: dict[str, Any] = {}
    _stub_upstream(monkeypatch, _REALTIME_CHINA_PAGE, captured)
    await zaobao.handle_route(_request("realtime-china"), no_cache=False)

    # 只有"N分钟前"那张卡片补了详情页请求
    assert captured["urls"] == [
        "https://www.zaobao.com/realtime/china",
        "https://www.zaobao.com/news/china/story20260928-9746188",
    ]


async def test_relative_fallback_keeps_estimate_and_sets_message(monkeypatch):
    async def fake_get(url, **kwargs):
        if "/story" in url:
            raise RuntimeError("detail page boom")  # 详情页失败
        return _ok(_REALTIME_CHINA_PAGE)

    monkeypatch.setattr(zaobao, "get", fake_get)
    monkeypatch.setattr(zaobao, "_now_sgt", lambda: _NOW)
    result = await zaobao.handle_route(_request("realtime-china"), no_cache=True)

    assert result.total == 4  # 条目照常输出
    third = result.data[2]
    assert third.timestamp == int((_NOW - timedelta(minutes=15)).timestamp() * 1000)  # 保留渲染时刻估计值
    assert "1 条「N分钟前」的稿没有取到详情页发布时间" in (result.message or "")


async def test_finance_board_maps_cover_and_clock(monkeypatch):
    _stub_upstream(monkeypatch, _FINANCE_CHINA_PAGE)
    result = await zaobao.handle_route(_request("finance-china"), no_cache=True)

    assert result.type == "中国财经"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "/finance/china/story20260927-9745001"
    assert first.cover == "https://dss0.zbstatic5.com/image/b.jpg"
    assert first.timestamp == _ms(2026, 9, 26)
    second = result.data[1]
    assert second.timestamp == _ms(2026, 9, 28, 6, 30)  # "HH:MM"早于渲染时刻,取渲染当天


async def test_clock_after_render_time_rolls_back_one_day(monkeypatch):
    """"HH:MM"落到估计的渲染时刻之后(跨午夜渲染)时退回前一天。"""
    page = f"""<html><body><main class="mx-auto"><h1>中国财经新闻</h1>
<div data-testid="article-list">
{_card("/finance/china/story20260927-9745002", "跨午夜渲染的当天稿", span="23:10")}
</div>
</main></body></html>
"""
    _stub_upstream(monkeypatch, page)
    result = await zaobao.handle_route(_request("finance-china"), no_cache=True)

    assert result.data[0].timestamp == _ms(2026, 9, 27, 23, 10)


async def test_broken_page_and_empty_parse_are_errors(monkeypatch):
    async def fake_no_main(url, **kwargs):
        return _ok("<html><body>维护中</body></html>")

    monkeypatch.setattr(zaobao, "get", fake_no_main)
    monkeypatch.setattr(zaobao, "_now_sgt", lambda: _NOW)
    with pytest.raises(RuntimeError, match="no <main>"):
        await zaobao.handle_route(_request("news-china"), no_cache=True)

    async def fake_empty(url, **kwargs):
        return _ok("<html><body><main><div>改版后的页面,没有文章卡片</div></main></body></html>")

    monkeypatch.setattr(zaobao, "get", fake_empty)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await zaobao.handle_route(_request("news-china"), no_cache=True)


async def test_unknown_type_is_rejected(monkeypatch):
    async def fake_get(url, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("unknown type 不应发起上游请求")

    monkeypatch.setattr(zaobao, "get", fake_get)
    with pytest.raises(ValueError, match="Unknown board"):
        await zaobao.handle_route(_request("global"), no_cache=True)


def test_board_table_matches_board_api():
    """10 个子榜与 board_api 同构;声明序第一个(realtime-china)是默认榜。"""
    assert list(zaobao._BOARDS) == [
        "realtime-china", "realtime-world", "realtime-singapore",
        "news-china", "news-world", "news-singapore",
        "finance-china", "finance-world", "finance-singapore", "xia-wu-cha",
    ]
    assert zaobao._DEFAULT_TYPE == "realtime-china"
    assert next(iter(zaobao.type_map)) == "realtime-china"
    assert [board[1] for board in zaobao._BOARDS.values()] == [
        "realtime/china", "realtime/world", "realtime/singapore",
        "news/china", "news/world", "news/singapore",
        "finance/china", "finance/world", "finance/singapore", "keywords/xia-wu-cha",
    ]

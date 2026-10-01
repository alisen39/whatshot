"""banyuetan-channels 路由测试:fixtures 依据 board_api 证据目录 tmp/board_api/banyuetan_channels 净化。

- 栏目页(首屏轮播 + 列表):evidence/01_shizhengjiangjie、01_wenhua、01_jinritan
- 要闻页(要闻top10 区块 + 要闻列表):evidence/02_yaowen
- 首页(截断标题补全来源):evidence/03_home
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import banyuetan_channels
from whats_hot_api.utils.http_client import RequestResult

_BEIJING = timezone(timedelta(hours=8))
_UPDATE_TIME = "2026-09-28T00:00:00+00:00"


def _request(board_type: str | None = None) -> Request:
    query = f"type={board_type}" if board_type else ""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/banyuetan-channels",
        "query_string": query.encode(),
        "headers": [],
    })


def _ok(data: Any) -> RequestResult:
    return RequestResult(False, _UPDATE_TIME, data)


def _ms(*args: int) -> int:
    return int(datetime(*args, tzinfo=_BEIJING).timestamp() * 1000)


def _li(url: str, title: str, *, desc: str = "", tag3: str = "", img: str = "") -> str:
    img_html = f'<a href="{url}"><img src="{img}"></a>' if img else ""
    desc_html = f"<p>{desc}</p>" if desc else ""
    tag_html = f'<span class="tag3">{tag3}</span>' if tag3 else ""
    return f"<li>{img_html}<h3><a href=\"{url}\">{title}</a></h3>{desc_html}{tag_html}</li>"


def _event(url: str, title: str, *, img: str = "") -> str:
    img_html = f'<a class="banner_img" href="{url}"><img src="{img}"></a>' if img else ""
    return (
        f'<div class="event-item">{img_html}'
        f'<div class="banner_title"><a href="{url}"> {title}</a></div></div>'
    )


# 时政讲解样式:轮播 2 条本栏目稿 + 1 条全站头条(dyp,不取);列表 4 条:
# 与轮播同 id、与轮播同标题同日期(不同 id)、正常、日期不符
_COLUMN_PAGE = f"""<html><body>
<div class="first_screen"><div class="dyp_lbt">
{_event("http://www.banyuetan.org/szjj/detail/20260920/1000200033135991789871712518721210_1.html",
        "新能源加速发展,油气仍然重要", img="http://img4.banyuetan.org/a.jpg")}
{_event("http://www.banyuetan.org/szjj/detail/20260904/1000200033135991788489439040493823_1.html",
        "解锁'知识产权+'")}
{_event("http://www.banyuetan.org/dyp/detail/20260924/1000200033137441790211000000000001_1.html",
        "全站头条不是本栏目稿")}
</div></div>
<div class="bty_tbtj_list js-tbtj"><ul>
{_li("http://www.banyuetan.org/szjj/detail/20260920/1000200033135991789871712518721210_1.html",
     "新能源加速发展,油气仍然重要", desc="列表导语A", tag3="2026-09-20")}
{_li("http://www.banyuetan.org/szjj/detail/20260904/1000200033135991788489421782492283_1.html",
     "解锁'知识产权+'", desc="列表导语B", tag3="2026-09-04")}
{_li("http://www.banyuetan.org/szjj/detail/20260924/1000200033135991790239738143742437_1.html",
     "北京香山论坛每一次对话倾听都为和平增添一分希望", desc="9月24日下午,国防部举行例行记者会。",
     tag3="2026-09-24", img="http://img9.banyuetan.org/b.jpeg")}
{_li("http://www.banyuetan.org/szjj/detail/20260923/1000200033135991788888888888888_1.html",
     "日期不符条目", tag3="2026-09-01")}
</ul></div>
</body></html>
"""

# 今日谈样式:轮播全是全站头条(xxjxs/dyp),与本栏目列表目录(jrt)不同,不取
_JINRITAN_PAGE = f"""<html><body>
<div class="first_screen"><div class="dyp_lbt">
{_event("http://www.banyuetan.org/xxjxs/detail/20260924/1000200033137441790211000000000002_1.html", "全站头条一")}
{_event("http://www.banyuetan.org/dyp/detail/20260924/1000200033137441790211000000000003_1.html", "全站头条二")}
</div></div>
<div class="bty_tbtj_list js-tbtj"><ul>
{_li("http://www.banyuetan.org/jrt/detail/20260924/1000200033134991790214224290782358_1.html",
     '"投资于老"是淘金风口吗', desc="客源不足,是市场化养老机构普遍面临的困难。", tag3="2026-09-24")}
{_li("http://www.banyuetan.org/jrt/detail/20260923/1000200033134991790214224290782359_1.html",
     "第二条今日谈")}
</ul></div>
</body></html>
"""

# 要闻页:右侧要闻top10(标题被截成以".."结尾)+ 要闻列表(补全来源)
_DYP_URL = "http://www.banyuetan.org/dyp/detail/20260924/1000200033137441790211999999999999_1.html"
_YAOWEN_PAGE = f"""<html><body>
<ul class="title2_box">
<li class="special"><em class="two-1">1、</em><a class="special1" href="http://www.banyuetan.org/yw/detail/20260924/1000200033137441790211048999726383_1.html">技能逐梦 共创未来——习近平主席贺..</a></li>
<li class="special"><em class="two-2">2、</em><a class="special1" href="http://www.banyuetan.org/yw/detail/20260924/1000200033137441790211155854774539_1.html">学习快评丨共赴技能之约,汇聚技能..</a></li>
<li class="special"><em class="two-3">3、</em><a class="special1" href="{_DYP_URL}">中共中央政治局召开会议 讨论拟提..</a></li>
</ul>
<div class="js-tbtj byt_tbtj_list_card"><ul>
<li><div class="byt_xxjxs_content"><h3><a href="http://www.banyuetan.org/yw/detail/20260924/1000200033137441790211048999726383_1.html">技能逐梦 共创未来——习近平主席贺信激励青年走技能成才之路并为世界技能运动发展指明方向</a></h3></div></li>
<li><div class="byt_xxjxs_content"><h3><a href="http://www.banyuetan.org/yw/detail/20260924/1000200033137441790211155854774539_1.html">学习快评丨共赴技能之约,汇聚技能成才的青春力量</a></h3></div></li>
</ul></div>
</body></html>
"""

# 首页:/dyp/ 稿的完整标题(同链接出现两次,一次文字无关、一次 title 属性正确,前缀必须匹配才用)
_HOME_PAGE = f"""<html><body>
<div class="hot_tt"><a href="{_DYP_URL}">完全不同的标题</a></div>
<div class="carousel"><a href="{_DYP_URL}" title="中共中央政治局召开会议 讨论拟提请审议的文件">占位</a>
<a href="http://www.banyuetan.org/yw/detail/20260924/1000200033137441790211048999726383_1.html" title="无关标题不采用">占位</a>
</div></body></html>
"""

_HOME_WITHOUT_DYP = "<html><body><p>首页头条已换,没有那条 /dyp/ 稿</p></body></html>"


def _route(responder: Any, monkeypatch) -> dict[str, Any]:
    captured: dict[str, Any] = {"urls": [], "kwargs": []}

    async def fake_get(url, **kwargs):
        captured["urls"].append(url)
        captured["kwargs"].append(kwargs)
        return responder(url)

    monkeypatch.setattr(banyuetan_channels, "get", fake_get)
    return captured


async def test_column_carousel_first_then_dedup(monkeypatch):
    captured = _route(lambda url: _ok(_COLUMN_PAGE), monkeypatch)
    result = await banyuetan_channels.handle_route(
        _request("shizhengjiangjie"), no_cache=True
    )

    assert captured["urls"] == [
        "http://www.banyuetan.org/byt/shizhengjiangjie/index.html"
    ]
    assert result.type == "时政讲解"
    # 轮播 2 条(全站头条那条目录不同不取)+ 列表 2 条新增;全站头条不出现
    ids = [item.id for item in result.data]
    assert ids == [
        "1000200033135991789871712518721210",  # 轮播:同 id 去重保留先出现的轮播那条
        "1000200033135991788489439040493823",  # 轮播:同标题同日期去掉列表那条
        "1000200033135991790239738143742437",
        "1000200033135991788888888888888",
    ]
    first = result.data[0]
    assert first.title == "新能源加速发展,油气仍然重要"
    assert first.cover == "http://img4.banyuetan.org/a.jpg"  # 轮播大图
    assert first.desc == "列表导语A"  # 轮播条目没有导语时借用列表那条的
    assert first.timestamp == _ms(2026, 9, 20)  # 列表日期(北京时间 0 点,毫秒)
    second = result.data[1]
    assert second.id == "1000200033135991788489439040493823"
    assert second.desc == "列表导语B"  # 同标题同日去重时借用被去掉那条的导语
    third = result.data[2]
    assert third.desc == "9月24日下午,国防部举行例行记者会。"
    assert third.cover == "http://img9.banyuetan.org/b.jpeg"
    assert third.timestamp == _ms(2026, 9, 24)
    assert result.data[3].timestamp is None  # tag3 与链接日期对不上,留空


async def test_jinritan_drops_foreign_carousel(monkeypatch):
    _route(lambda url: _ok(_JINRITAN_PAGE), monkeypatch)
    result = await banyuetan_channels.handle_route(_request("jinritan"), no_cache=True)

    # 轮播是全站头条(xxjxs/dyp),与列表目录 jrt 不同,不取
    assert result.total == 2
    assert [item.id for item in result.data] == [
        "1000200033134991790214224290782358",
        "1000200033134991790214224290782359",
    ]
    first = result.data[0]
    assert first.title == '"投资于老"是淘金风口吗'
    assert first.desc == "客源不足,是市场化养老机构普遍面临的困难。"
    assert first.timestamp == _ms(2026, 9, 24)
    assert result.data[1].timestamp == _ms(2026, 9, 23)  # 没有 tag3 时用链接里的日期


async def test_top10_completes_truncated_titles_from_list_and_home(monkeypatch):
    captured = _route(
        lambda url: _ok(_YAOWEN_PAGE if "yaowen" in url else _HOME_PAGE), monkeypatch
    )
    result = await banyuetan_channels.handle_route(_request("top10"), no_cache=True)

    assert captured["urls"] == [
        "http://www.banyuetan.org/byt/yaowen/index.html",
        "http://www.banyuetan.org/",  # 有补不全的截断标题时才取首页
    ]
    assert result.total == 3
    titles = [item.title for item in result.data]
    assert titles == [
        "技能逐梦 共创未来——习近平主席贺信激励青年走技能成才之路并为世界技能运动发展指明方向",
        "学习快评丨共赴技能之约,汇聚技能成才的青春力量",
        "中共中央政治局召开会议 讨论拟提请审议的文件",  # 首页 title 属性,前缀匹配
    ]
    assert all(not title.endswith("..") for title in titles)
    assert result.message is None
    assert result.data[0].timestamp == _ms(2026, 9, 24)  # 链接里的日期,0 点
    assert result.data[2].id == "1000200033137441790211999999999999"


async def test_top10_unmatched_title_stays_truncated_with_message(monkeypatch):
    _route(lambda url: _ok(_YAOWEN_PAGE if "yaowen" in url else _HOME_WITHOUT_DYP), monkeypatch)
    result = await banyuetan_channels.handle_route(_request("top10"), no_cache=True)

    assert result.data[2].title == "中共中央政治局召开会议 讨论拟提.."  # 照区块原样(截断的)
    assert "1 条标题在要闻列表和首页都没找到完整标题" in (result.message or "")


async def test_broken_and_empty_pages_are_errors(monkeypatch):
    # 页面改版,没有列表容器
    _route(lambda url: _ok("<html><body>改版后的栏目页</body></html>"), monkeypatch)
    with pytest.raises(RuntimeError, match="bty_tbtj_list"):
        await banyuetan_channels.handle_route(_request("wenhua"), no_cache=True)

    # 容器在但解析不到条目(空解析不静默降级为空榜)
    _route(
        lambda url: _ok('<html><body><div class="bty_tbtj_list js-tbtj"><ul></ul></div></body></html>'),
        monkeypatch,
    )
    with pytest.raises(RuntimeError, match="parsed no items"):
        await banyuetan_channels.handle_route(_request("wenhua"), no_cache=True)


async def test_unknown_type_is_rejected(monkeypatch):
    async def fake_get(url, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("unknown type 不应发起上游请求")

    monkeypatch.setattr(banyuetan_channels, "get", fake_get)
    with pytest.raises(ValueError, match="Unknown board"):
        await banyuetan_channels.handle_route(_request("quyufengcai"), no_cache=True)


def test_board_table_matches_board_api():
    """12 个子榜与 board_api 同构;声明序第一个(top10)是默认榜。"""
    assert list(banyuetan_channels._BOARDS) == [
        "top10", "jinritan", "shizhengjiangjie", "pinglun", "difangguancha",
        "jicengzhili", "minshenghuati", "guoji", "wenhua", "keji", "jiankang",
        "qiyezixun",
    ]
    assert banyuetan_channels._DEFAULT_TYPE == "top10"
    assert banyuetan_channels.ROUTE_NAME == "banyuetan-channels"
    # 只有 http(https 连不上,证据 verify/https_check.txt)
    assert banyuetan_channels.BASE == "http://www.banyuetan.org/"
    # 停更的 3 个栏目(区域风采/改革创新/脱贫攻坚)不在子榜里
    assert "quyufengcai" not in banyuetan_channels._BOARDS
    assert "gaigechuangxin" not in banyuetan_channels._BOARDS
    assert "fupingongjian" not in banyuetan_channels._BOARDS

"""douban-charts 路由测试：fixture 从 board_api 证据 captured_data/ 净化为最小结构样本，
只保留字段与形状，全部 mock 共享 http_client，不触网（pytest --disable-socket）。"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import douban_charts
from whats_hot_api.utils.http_client import RequestResult

UPDATE_TIME = "2026-10-01T00:00:00+00:00"

REXXAR_COLLECTION_URL = (
    "https://m.douban.com/rexxar/api/v2/subject_collection/movie_weekly_best/items"
)


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/douban-charts",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _result(data: object, from_cache: bool = False) -> RequestResult:
    return RequestResult(from_cache, UPDATE_TIME, data)


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    # 采集口径是同站 2.1 秒一个请求,单测里关掉以免拖慢
    monkeypatch.setattr(douban_charts, "_MIN_SPACING_SECONDS", 0)


COLLECTION_PAYLOAD = {
    "start": 0,
    "count": 50,
    "total": 2,
    "subject_collection_items": [
        {
            "id": "35322132",
            "title": "样例片A",
            "type": "movie",
            "subtype": "movie",
            "url": "https://www.douban.com/doubanapp/dispatch/movie/35322132",
            "rating": {"count": 15710, "max": 10, "star_count": 4.5, "value": 8.5},
            "cover_url": "https://img3.doubanio.com/view/photo/m_ratio_poster/public/p1.jpg",
            "card_subtitle": "2026 / 奥地利 德国 / 剧情",
            "description": "剧情简介A",
            "null_rating_reason": "",
        },
        {
            "id": "36828393",
            "title": "样例剧B",
            "type": "tv",
            "rating": {"count": 0, "max": 10, "star_count": 0, "value": 0},
            "null_rating_reason": "尚未上映",
            "pic": {"normal": "https://img9.doubanio.com/view/photo/p2.jpg"},
            "card_subtitle": "2026 / 中国大陆 / 剧情",
            "description": "",
        },
    ],
    "subject_collection": {
        "id": "movie_weekly_best",
        "name": "一周口碑电影榜",
        "description": "每周五更新",
        "updated_at": "2026-09-25 16:30:02",
    },
}


@pytest.mark.asyncio
async def test_collection_board_url_params_and_field_mapping(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers, "params": params, "no_cache": no_cache})
        return _result(COLLECTION_PAYLOAD)

    monkeypatch.setattr(douban_charts, "get", fake_get)
    result = await douban_charts.handle_route(_request("movie-weekly-best"), no_cache=True)

    # rexxar 榜单 URL / 翻页参数 / Referer 非空 / 浏览器 UA(python 默认 UA 会 418)
    assert captured["url"] == REXXAR_COLLECTION_URL
    assert captured["params"] == {"start": 0, "count": 50}
    assert captured["headers"]["Referer"] == (
        "https://m.douban.com/subject_collection/movie_weekly_best"
    )
    assert captured["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert captured["no_cache"] is True

    assert result.type == "一周口碑榜"
    assert result.total == 2
    assert result.fromCache is False
    assert result.updateTime == UPDATE_TIME
    # message = 榜单名 · 说明 · 更新时间
    assert "一周口碑电影榜" in (result.message or "")
    assert "更新于 2026-09-25 16:30:02" in (result.message or "")

    first = result.data[0]
    assert first.id == "35322132"
    # rexxar 的 url 多是 App 分发页,换成站点详情页
    assert first.url == "https://movie.douban.com/subject/35322132/"
    assert first.mobileUrl == "https://m.douban.com/movie/subject/35322132/"
    assert first.hot == 15710  # 非实时榜的 hot 是评价人数
    assert first.cover == "https://img3.doubanio.com/view/photo/m_ratio_poster/public/p1.jpg"
    assert first.desc == "评分 8.5 · 2026 / 奥地利 德国 / 剧情 · 剧情简介A"

    second = result.data[1]
    assert second.hot is None  # 无评分人数
    assert second.desc == "尚未上映 · 2026 / 中国大陆 / 剧情"
    assert second.cover == "https://img9.doubanio.com/view/photo/p2.jpg"  # pic.normal 兜底


@pytest.mark.asyncio
async def test_collection_short_page_is_refetched_once(monkeypatch):
    """实测偶发残缺响应(条目明显少于 total),页不满时重取一次,不输出半榜。"""
    calls: list[dict] = []

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        calls.append({"url": url, "params": params})
        if len(calls) == 1:
            short = dict(COLLECTION_PAYLOAD, total=2,
                         subject_collection_items=COLLECTION_PAYLOAD["subject_collection_items"][:1])
            return _result(short)
        return _result(COLLECTION_PAYLOAD)

    monkeypatch.setattr(douban_charts, "get", fake_get)
    result = await douban_charts.handle_route(_request("movie-weekly-best"), no_cache=True)

    assert len(calls) == 2
    assert calls[1] == calls[0]  # 同参数重取
    assert result.total == 2


@pytest.mark.asyncio
async def test_real_time_hotest_hot_is_heat_score(monkeypatch):
    payload = {
        "total": 2,
        "subject_collection_items": [
            {"id": "35322132", "title": "实时热门片", "type": "movie",
             "rating": {"count": 15710, "value": 8.5}, "score": 81234},
            {"id": "38681100", "title": "样例单曲", "type": "music",
             "singer": ["ROSÉ", "歌手B"], "comment": "发行于2026", "score": 51000},
        ],
        "subject_collection": {"name": "实时热门书影音", "updated_at": "2026-09-27 10:00:00"},
    }

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert "subject_real_time_hotest" in url
        assert no_cache is False
        return _result(payload, from_cache=True)

    monkeypatch.setattr(douban_charts, "get", fake_get)
    result = await douban_charts.handle_route(_request("subject-real-time-hotest"), no_cache=False)

    assert result.data[0].hot == 81234  # 实时热门榜的 hot 是热度值 score,不是评价人数
    assert result.fromCache is True  # 未禁缓存时走 mock 的 from_cache=True
    music = result.data[1]
    assert music.url == "https://music.douban.com/subject/38681100/"
    assert music.mobileUrl == "https://m.douban.com/music/subject/38681100/"
    assert music.author == "ROSÉ / 歌手B"
    assert music.desc == "发行于2026"  # comment 兜底进 desc


@pytest.mark.asyncio
async def test_hot_search_board_maps_name_to_id_and_search_url(monkeypatch):
    payload = [
        {"name": "样例讨论词", "score": 179178, "uri": "douban://douban.com/search/result?q=%23样例讨论词%23"},
        {"name": "", "score": 1, "uri": "douban://x"},  # 空词丢弃
    ]

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://m.douban.com/rexxar/api/v2/chart/hot_search_board"
        assert headers["Referer"] == "https://www.douban.com/gallery/"
        return _result(payload)

    monkeypatch.setattr(douban_charts, "get", fake_get)
    result = await douban_charts.handle_route(_request("hot-search-board"), no_cache=True)

    assert result.type == "实时热门讨论"
    assert result.total == 1  # 接口没有独立 ID,空讨论词的条目被丢弃
    item = result.data[0]
    assert item.id == "样例讨论词"
    assert item.url == "https://www.douban.com/search?q=" + quote("#样例讨论词#")
    assert item.hot == 179178


REVIEW_RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>豆瓣最受欢迎的影评</title>
<item>
    <title>样例影评 (评论: 样例剧集)</title>
    <link>https://movie.douban.com/review/17831126/</link>
    <description><![CDATA[
样例作者评论: 样例剧集 (https://movie.douban.com/subject/35445834/)
评价: 力荐

{&#34;blocks&#34;:[{&#34;key&#34;:&#34;6npq6&#34;,&#34;text&#34;:&#34;重看了样例剧集。&#34;,&#34;type&#34;:&#34;unstyled&#34;}],...]]></description>
    <content:encoded><![CDATA[
<img src="https://img3.doubanio.com/view/photo/s_ratio_poster/public/p3.jpg" style="float:right"/><a href="https://www.douban.com/people/sample/">样例作者</a>评论: 样例剧集<br/>
]]></content:encoded>
    <dc:creator>样例作者</dc:creator>
    <pubDate>Sat, 26 Sep 2026 14:50:34 GMT</pubDate>
    <guid isPermaLink="true">https://movie.douban.com/review/17831126/</guid>
</item>
</channel></rss>
"""


@pytest.mark.asyncio
async def test_review_feed_timestamp_is_unix_milliseconds(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://www.douban.com/feed/review/movie"
        # www.douban.com 必须带 User-Agent(不带 403),且不需要 Referer
        assert headers["User-Agent"].startswith("Mozilla/5.0")
        assert "Referer" not in headers
        return _result(REVIEW_RSS)

    monkeypatch.setattr(douban_charts, "get", fake_get)
    result = await douban_charts.handle_route(_request("review-best"), no_cache=True)

    item = result.data[0]
    assert item.id == "17831126"
    assert item.url == "https://movie.douban.com/review/17831126/"
    assert item.mobileUrl == "https://m.douban.com/movie/review/17831126/"
    assert item.author == "样例作者"
    assert item.cover == "https://img3.doubanio.com/view/photo/s_ratio_poster/public/p3.jpg"
    # 秒级 pubDate 统一换算为 13 位毫秒
    assert item.timestamp == 1790434234000
    assert item.timestamp > 10**12
    # desc = RSS 头部(作者+作品+评价) + Draft.js 截断 JSON 里的正文
    assert item.desc == "样例作者评论: 样例剧集 评价: 力荐 · 重看了样例剧集。"


BOX_OFFICE_HTML = """
<html><body><div class="movie_top" id="ranking">
    <h2>北美票房榜· · · · · · <span class="box_chart_num color-gray">9月18日 更新 / 美元</span></h2>
    <ul class="content" id="listCont1">
        <li class="clearfix">
            <div class="name"><span class="box_chart_top">1</span>
                <a href="https://movie.douban.com/subject/37068446/">样例票房片A</a></div>
            <span class="box_chart_num color-gray">6000万</span>
        </li>
        <li class="clearfix">
            <div class="name"><span class="box_chart_new box_new">新</span>
                <a href="https://movie.douban.com/subject/37193887/">样例票房片B</a></div>
            <span class="box_chart_num color-gray">1200万</span>
        </li>
    </ul>
</div></body></html>
"""


@pytest.mark.asyncio
async def test_us_box_office_html_mapping(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://movie.douban.com/chart"
        assert headers["User-Agent"].startswith("Mozilla/5.0")
        assert "Referer" not in headers  # movie.douban.com 不要求 Referer
        return _result(BOX_OFFICE_HTML)

    monkeypatch.setattr(douban_charts, "get", fake_get)
    result = await douban_charts.handle_route(_request("us-box-office"), no_cache=True)

    assert result.type == "北美票房榜"
    assert result.message == "北美票房榜 9月18日 更新 / 美元"
    first = result.data[0]
    assert first.id == "37068446"
    assert first.hot == 60000000  # '6000万' 换算为整数美元
    assert first.desc == "票房 6000万美元"
    second = result.data[1]
    assert second.hot == 12000000
    assert second.desc == "票房 1200万美元 · 新上榜"  # box_new 图标 -> 新上榜


NOWPLAYING_HTML = """
<html><body>
<div id="nowplaying"><div class="mod-bd"><ul class="lists">
    <li id="35244246" class="list-item" data-title="样例上映片" data-score="6.0" data-star="30"
        data-release="2026" data-duration="123分钟" data-region="中国大陆"
        data-director="样例导演" data-actors="演员甲 / 演员乙" data-category="nowplaying"
        data-enough="True" data-votecount="7793" data-subject="35244246">
        <ul><li class="poster"><a href="https://movie.douban.com/subject/35244246/?from=playing_poster"
            class="ticket-btn"><img src="https://img3.doubanio.com/view/photo/s_ratio_poster/public/p4.jpg" /></a></li></ul>
    </li>
    <li id="37000001" class="list-item" data-title="即将上映样例" data-score="0"
        data-category="upcoming" data-votecount="10"></li>
</ul></div></div>
<div id="upcoming"></div>
</body></html>
"""


@pytest.mark.asyncio
async def test_nowplaying_takes_only_nowplaying_block(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://movie.douban.com/cinema/nowplaying/beijing/"
        return _result(NOWPLAYING_HTML)

    monkeypatch.setattr(douban_charts, "get", fake_get)
    result = await douban_charts.handle_route(_request("nowplaying"), no_cache=True)

    # 只取"正在上映"区块(data-category=nowplaying),不混入同页"即将上映"
    assert result.total == 1
    item = result.data[0]
    assert item.id == "35244246"
    assert item.title == "样例上映片"
    assert item.hot == 7793  # data-votecount 字符串转整数
    assert item.cover == "https://img3.doubanio.com/view/photo/s_ratio_poster/public/p4.jpg"
    assert item.desc == "评分 6.0 · 2026 · 123分钟 · 中国大陆 · 导演 样例导演 · 主演 演员甲 / 演员乙"
    assert "城市：beijing" in (result.message or "")


class _FixedDatetime(datetime):
    """固定 now(),让月度片单回退行为离线可测。"""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 15, tzinfo=UTC)


@pytest.mark.asyncio
async def test_monthly_board_resolves_playlist_by_title(monkeypatch):
    """先查 skynet/new_playlists 按标题找片单 ID,再按普通榜单取条目;
    当月(10月)片单缺席时回退列表里第一个月度片单,找不到则报错。"""
    skynet_payload = {
        "data": [{
            "items": [
                {"id": "ECCJAIBPA", "title": "第31届上海电视节白玉兰奖获奖名单"},
                {"id": "ECOLDTEST", "title": "2025年12月定档热门新剧推荐"},
                {"id": "EC2ZBUUKA", "title": "2026年09月定档热门新剧推荐"},
            ],
        }],
        "total": 25,
    }
    playlist_payload = dict(COLLECTION_PAYLOAD, subject_collection={"id": "ECOLDTEST"})
    calls: list[str] = []

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        calls.append(url)
        if "skynet/new_playlists" in url:
            assert params == {"subject_type": "tv"}
            assert headers["Referer"] == "https://m.douban.com/movie/"
            return _result(skynet_payload)
        assert "subject_collection/ECOLDTEST/items" in url  # 回退到 2025年12月 片单
        return _result(playlist_payload)

    monkeypatch.setattr(douban_charts, "get", fake_get)
    monkeypatch.setattr(douban_charts, "datetime", _FixedDatetime)
    result = await douban_charts.handle_route(_request("monthly-tv"), no_cache=True)

    assert calls[0].endswith("/rexxar/api/v2/skynet/new_playlists")
    assert result.message == "2025年12月定档热门新剧推荐"  # message 是片单标题
    assert result.type == "本月热门新剧推荐"
    assert result.total == 2


@pytest.mark.asyncio
async def test_monthly_board_errors_when_no_monthly_playlist(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        return _result({"data": [{"items": [{"id": "ECCJAIBPA", "title": "获奖名单"}]}]})

    monkeypatch.setattr(douban_charts, "get", fake_get)
    monkeypatch.setattr(douban_charts, "datetime", _FixedDatetime)
    with pytest.raises(RuntimeError, match="热门新剧推荐"):
        await douban_charts.handle_route(_request("monthly-tv"), no_cache=True)


@pytest.mark.asyncio
async def test_empty_parse_and_error_shell_raise_instead_of_empty_board(monkeypatch):
    # 空榜(total=0 / 无条目):不允许静默降级为空榜
    async def fake_get_empty(url, headers=None, params=None, no_cache=None, **kwargs):
        return _result({"total": 0, "subject_collection_items": []})

    monkeypatch.setattr(douban_charts, "get", fake_get_empty)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await douban_charts.handle_route(_request("movie-weekly-best"), no_cache=True)

    # 错误页 / 登录跳转(HTTP 200 的 HTML):拒绝 JSON 对象外壳
    async def fake_get_html(url, headers=None, params=None, no_cache=None, **kwargs):
        return _result("<html>accounts.douban.com/passport/login ...</html>")

    monkeypatch.setattr(douban_charts, "get", fake_get_html)
    with pytest.raises(RuntimeError, match="instead of a JSON object"):
        await douban_charts.handle_route(_request("movie-weekly-best"), no_cache=True)

    # 业务错误壳(顶层数组之外的意外形状):recent_hot items 不是列表
    async def fake_get_shell(url, headers=None, params=None, no_cache=None, **kwargs):
        return _result({"code": 124, "msg": "invalid_request"})

    monkeypatch.setattr(douban_charts, "get", fake_get_shell)
    with pytest.raises(RuntimeError, match="not a list"):
        await douban_charts.handle_route(_request("tv-hot"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_board_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await douban_charts.handle_route(_request("no-such-board"), no_cache=True)

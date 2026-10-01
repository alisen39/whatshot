"""magazine_sites 路由测试:fixtures 按证据目录 tmp/board_api/magazine_sites 净化(结构与字段一致,内容摘录)。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import magazine_sites
from whats_hot_api.utils.http_client import RequestResult

_BEIJING = timezone(timedelta(hours=8))


def _ms(*parts: int) -> int:
    return int(datetime(*parts, tzinfo=_BEIJING).timestamp() * 1000)


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/magazine-sites",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _ok(data: Any) -> RequestResult:
    return RequestResult(False, "2026-09-28T00:20:00+00:00", data)


def _status_error(url: str, status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", url)
    return httpx.HTTPStatusError(f"{status} error", request=req, response=httpx.Response(status, request=req))


# ---- FT:首页右栏两个 div.mps,标题文字区分"热门文章"与"热门付费文章" ----

_FT_HOME = """
<html><body>
<div class="mps">
  <h2 class="list-title"><a href="/channel/weekly.html">热门付费文章</a></h2>
  <ul class="top10">
    <li><span>1. </span><a target="_blank" href="/story/001110982">付费榜不该出现</a></li>
  </ul>
</div>
<div class="mps">
  <h2 class="list-title"><a href="/channel/weekly.html">热门文章</a></h2>
  <ul class="top10">
    <li><span>1. </span><a target="_blank" href="/story/001110958">强劲出口数据背后的中国隐忧</a></li>
    <li><span>2. </span><a target="_blank" href="/interactive/295900">一周新闻小测：2026年9月27日</a></li>
    <li><span>3. </span><a target="_blank" href="/story/001110945">山姆•沃顿的飞机与低空经济的逻辑</a></li>
  </ul>
</div>
</body></html>
"""

_FT_HOT_RSS = """
<rss version="2.0"><channel><title>FTChinese RSS - Hot Weekly</title>
<item><title>一周新闻小测：2026年9月27日</title>
  <link>https://www.ftchinese.com/interactive/295900</link>
  <guid>https://www.ftchinese.com/interactive/295900</guid>
  <pubDate>Sat, 26 Sep 2026 16:00:00 GMT</pubDate>
  <description>您对本周的全球重大新闻了解如何？</description></item>
<item><title>强劲出口数据背后的中国隐忧</title>
  <link>https://www.ftchinese.com/story/001110958</link>
  <guid>https://www.ftchinese.com/story/001110958</guid>
  <pubDate>Mon, 21 Sep 2026 16:00:00 GMT</pubDate>
  <description>沈建光：8月出口同比增速为何回升？</description></item>
</channel></rss>
"""


async def test_ft_hot_prefers_homepage_order_and_enriches_from_rss(monkeypatch):
    calls: list[str] = []

    async def fake_get(**kwargs):
        url = kwargs["url"]
        calls.append(url)
        return _ok(_FT_HOT_RSS if "/rss/" in url else _FT_HOME)

    monkeypatch.setattr(magazine_sites, "get", fake_get)
    result = await magazine_sites.handle_route(_request("ft-hot-weekly"), no_cache=True)

    assert len(calls) == 2  # RSS(补摘要/日期) + 首页区块
    assert any(url.endswith("/rss/hotstoryby7day") for url in calls)
    assert result.type == "FT中文网 · 十大热门文章（一周）"
    assert result.message is None
    # 条目与顺序以首页区块为准(RSS 里 295900 排前面)
    assert [item.id for item in result.data] == [
        "https://www.ftchinese.com/story/001110958",
        "https://www.ftchinese.com/interactive/295900",
        "https://www.ftchinese.com/story/001110945",
    ]
    first = result.data[0]
    assert first.title == "强劲出口数据背后的中国隐忧"
    assert first.desc == "沈建光：8月出口同比增速为何回升？"  # RSS 补摘要
    assert first.timestamp == int(datetime(2026, 9, 21, 16, 0, 0, tzinfo=UTC).timestamp() * 1000)
    assert result.data[2].timestamp is None  # 不在 RSS 里的条目不补
    assert "付费榜不该出现" not in [item.title for item in result.data]  # 热门付费文章区块不取


async def test_ft_hot_falls_back_to_rss_on_homepage_429(monkeypatch):
    async def fake_get(**kwargs):
        url = kwargs["url"]
        if "/rss/" in url:
            return _ok(_FT_HOT_RSS)
        raise _status_error(url, 429)

    monkeypatch.setattr(magazine_sites, "get", fake_get)
    result = await magazine_sites.handle_route(_request("ft-hot-weekly"), no_cache=True)

    assert result.total == 2  # RSS 前 10( fixture 只有 2 条)
    assert result.message and "429" in result.message and "hotstoryby7day" in result.message
    assert result.data[0].id == "https://www.ftchinese.com/interactive/295900"


async def test_ft_news_parses_official_rss(monkeypatch):
    rss = """
    <rss version="2.0"><channel><title>FTChinese RSS - News</title>
    <item><title>今日焦点第一条</title>
      <link>https://www.ftchinese.com/story/001111025</link>
      <guid>https://www.ftchinese.com/story/001111025</guid>
      <pubDate>Sun, 27 Sep 2026 16:00:00 GMT</pubDate>
      <description>焦点摘要</description></item>
    </channel></rss>
    """

    async def fake_get(**kwargs):
        assert kwargs["url"] == "https://www.ftchinese.com/rss/news"
        return _ok(rss)

    monkeypatch.setattr(magazine_sites, "get", fake_get)
    result = await magazine_sites.handle_route(_request("ft-news"), no_cache=True)

    assert result.type == "FT中文网 · 今日焦点"
    assert result.total == 1
    first = result.data[0]
    assert first.id == "https://www.ftchinese.com/story/001111025"
    assert first.timestamp == int(datetime(2026, 9, 27, 16, 0, 0, tzinfo=UTC).timestamp() * 1000)


# ---- 三联生活周刊 ----

_LIFEWEEK_PAYLOAD = {
    "resultCode": "0",
    "model": {
        "tagList": [{"level": 1, "name": "封面故事", "id": 1, "type": 3}],
        "articleResponseList": [
            {
                "id": 273658,
                "title": "在古道消失之前，把它重新走出来",
                "summary": "复原一条古道乃至整套古道系统，是非常困难的事。",
                "pic": "http://zdimg.lifeweek.com.cn/bg/20260925/pic.jpg!pdPic",
                "pubTime": "2026-09-25 17:00:00",
                "hotNumber": 1651,
                "teacherList": [{"name": "薛芃", "id": 57}, {"name": "邢海洋", "id": 12}],
            },
            {
                "id": 273657,
                "title": "古蜀道上的驿站",
                "summary": "",
                "pic": "",
                "pubTime": "2026-09-25 10:30:00",
                "hotNumber": 94,
                "teacherList": [],
            },
        ],
    },
}


async def test_lifeweek_maps_fields(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok(dict(_LIFEWEEK_PAYLOAD))

    monkeypatch.setattr(magazine_sites, "get", fake_get)
    result = await magazine_sites.handle_route(_request("lifeweek-cover"), no_cache=True)

    assert captured["url"].startswith(
        "https://www.lifeweek.com.cn/api/userWebFollow/getFollowTagContentList?pgNo=1&tagId=1&type=3&sort=2&pgSize=20"
    )
    assert result.type == "三联生活周刊 · 封面故事"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "273658"
    assert first.url == "https://www.lifeweek.com.cn/article/273658"
    assert first.author == "薛芃、邢海洋"  # teacherList 顿号连接
    assert first.hot == 1651  # 页面带"hot"图标显示的数
    assert first.timestamp == _ms(2026, 9, 25, 17, 0, 0)  # 北京时间
    second = result.data[1]
    assert second.cover is None and second.author is None and second.desc is None


async def test_lifeweek_error_shell_is_rejected(monkeypatch):
    async def fake_get(**kwargs):
        return _ok({"resultCode": "500", "resultMsg": "系统错误"})

    monkeypatch.setattr(magazine_sites, "get", fake_get)
    with pytest.raises(RuntimeError, match="articleResponseList"):
        await magazine_sites.handle_route(_request("lifeweek-cover"), no_cache=True)


# ---- 國家地理雜誌中文網 ----

_NATGEO_LATEST = """
<html><body>
<section class="lastest">
  <div class="artcle-btn-large"><div class="art-btn-large"><div class="art-btn-la-content">
    <a href="https://www.natgeomedia.com/science/article/content-19420.html" aria-label="行星一定需要恆星嗎？">
      <div class="art-btn-la-img"><picture><img class="lazy" data-src="https://img.natgeomedia.com/userfiles/sm/sm1/19420/a.jpg" alt="x"></picture></div>
      <div class="art-btn-text art-btn-la-text text-white">
        <h5 class="text-yellow"><a href="https://www.natgeomedia.com/science/" aria-label="科學與新知">科學與新知｜</a></h5>
        <h6>Sep. 24 2026</h6>
        <h4><a href="https://www.natgeomedia.com/science/article/content-19420.html" class="text-white">行星一定需要恆星嗎？</a></h4>
      </div>
    </a>
  </div></div></div>
  <div class="artile-btn-small"><div class="art-btn-s-content">
    <a href="https://www.natgeomedia.com/science/article/content-19397.html" aria-label="中子星「吞噬」巨星恆星風">
      <div class="art-btn-s-img"><img src="https://img.natgeomedia.com/userfiles/sm/sm2/19397/b.jpg" alt="y"></div>
      <div class="art-btn-text art-btn-s-text text-white">
        <h5 class="text-yellow"><a aria-label="科學與新知">科學與新知｜</a></h5>
        <h6>Sep. 22 2026</h6>
        <h4><a href="https://www.natgeomedia.com/science/article/content-19397.html">中子星「吞噬」巨星恆星風</a></h4>
      </div>
    </a>
  </div></div>
  <h4><a href="https://www.natgeomedia.com/magazine/">電子雜誌推廣位(没有文章链接)</a></h4>
</section>
</body></html>
"""

_NATGEO_ENV = """
<html><body>
<section class="content-all">
  <div class="article-link-content">
    <h4><a href="https://www.natgeomedia.com/environment/article/content-19395.html">短短40年間，珊瑚減少了多少？</a></h4>
    <h4><a href="https://www.natgeomedia.com/environment/article/content-19387.html">加拿大驚見「森林浮島」</a></h4>
  </div>
  <div class="article-link-right">
    <h4><a href="https://www.natgeomedia.com/ph/article/content-7967.html">熱門精選(右栏,不算)</a></h4>
  </div>
</section>
</body></html>
"""


@pytest.mark.parametrize("board,url_part,fixture", [
    ("natgeo-latest", "natgeomedia.com/", _NATGEO_LATEST),
    ("natgeo-env-articles", "/environment/article/index.html", _NATGEO_ENV),
])
async def test_natgeo_maps_cards_and_drops_right_rail(monkeypatch, board, url_part, fixture):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok(fixture)

    monkeypatch.setattr(magazine_sites, "get", fake_get)
    result = await magazine_sites.handle_route(_request(board), no_cache=True)

    assert url_part in captured["url"]
    if board == "natgeo-latest":
        assert result.total == 2  # 推广位 h4 没有文章链接,跳过
        first = result.data[0]
        assert first.id == "19420"
        assert first.title == "行星一定需要恆星嗎？"
        assert first.cover == "https://img.natgeomedia.com/userfiles/sm/sm1/19420/a.jpg"  # data-src 优先
        assert first.desc == "科學與新知"  # h5 分类名去掉尾部"｜"
        assert first.timestamp == _ms(2026, 9, 24)  # UTC+8 当天 0 点
        assert result.data[1].cover == "https://img.natgeomedia.com/userfiles/sm/sm2/19397/b.jpg"  # 无 data-src 退 src
    else:
        assert result.total == 2
        assert [item.id for item in result.data] == ["19395", "19387"]  # 右栏 7967 已去掉
        assert result.data[0].desc is None  # 文章總匯卡片没有 h5 分类


# ---- 日经中文网 ----

_NIKKEI_RSS = """
<rss version=""><channel><title>日经中文网</title>
<item><title>美联储加息周期下，该如何做全球资产配置？</title>
  <link>http://cn.nikkei.com/columnviewpoint/column/64153-2026-09-28-05-00-05.html</link>
  <guid>http://cn.nikkei.com/columnviewpoint/column/64153-2026-09-28-05-00-05.html</guid>
  <pubDate>Sun, 27 Sep 2026 23:56:55 +0000</pubDate></item>
<item><title>中国参与巴基斯坦电力业务意愿下降</title>
  <link>http://cn.nikkei.com/columnviewpoint/column/64086-2026-09-28-05-00-10.html</link>
  <guid>http://cn.nikkei.com/columnviewpoint/column/64086-2026-09-28-05-00-10.html</guid>
  <pubDate>Sun, 27 Sep 2026 23:56:55 +0000</pubDate></item>
</channel></rss>
"""


async def test_nikkei_sends_browser_ua_rewrites_https_and_uses_url_time(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok(_NIKKEI_RSS)

    monkeypatch.setattr(magazine_sites, "get", fake_get)
    result = await magazine_sites.handle_route(_request("nikkei-latest"), no_cache=True)

    # CloudFront 对非浏览器 UA 返回缓存的 403 维护页,必须带浏览器 UA(header_matrix 实测)
    assert captured["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert result.total == 2
    first = result.data[0]
    assert first.id == "https://cn.nikkei.com/columnviewpoint/column/64153-2026-09-28-05-00-05.html"
    assert first.url == first.id  # RSS 的 http 改成 https(HSTS)
    assert first.timestamp == _ms(2026, 9, 28, 5, 0, 5)  # 链接里的时刻按北京时间;pubDate(生成时间)不用
    assert result.message is None


async def test_nikkei_retries_with_timestamp_query_on_maintenance_403(monkeypatch):
    calls: list[str] = []

    async def fake_get(**kwargs):
        url = kwargs["url"]
        calls.append(url)
        if "?_=" not in url:
            raise _status_error(url, 403)
        assert "?_=" in url
        return _ok(_NIKKEI_RSS)

    monkeypatch.setattr(magazine_sites, "get", fake_get)
    result = await magazine_sites.handle_route(_request("nikkei-latest"), no_cache=True)

    assert len(calls) == 2
    assert result.total == 2
    assert result.message and "维护页" in result.message


# ---- 科学网 ----

_SCIENCENET_HOME = """
<html><body>
<div class="main01">
  <div class="left">
    <div class="ltitbg"><table><tr>
      <td width="82%" class="white">头 条</td>
      <td class="more"><a href="/topnews.aspx">更多&gt;&gt;</a></td>
    </tr></table></div>
    <div class="Black"><a href="https://news.cn/x.html" target="_blank">外链头条:某招待会在京举行</a></div>
    <div class="summary"><a href="https://news.cn/x.html" target="_blank">头条摘要内容。</a></div>
    <div class="Black"><a href="/htmlnews/2026/9/572150.shtm" target="_blank">拖延≠懒惰，真相也许是这样</a></div>
    <div class="summary"><a href="/htmlnews/2026/9/572150.shtm">近日，中国科学院心理研究所等团队证实…</a></div>
  </div>
  <div class="center">
    <div class="ltitbg"><table><tr>
      <td width="82%" class="white">要 闻</td>
      <td class="more"><a href="/indexyaowen.aspx">更多&gt;&gt;</a></td>
    </tr></table></div>
    <div class="boxm"><ul>
      <li>·<a href="/htmlnews/2026/9/571990.shtm" target="_blank">封面文章 | 效应蛋白TseMt的毒性机制及递送通路</a></li>
      <li>·<a href="https://weibo.com/l/wblive/p/show/1022:xxx" target="_blank">直播回放｜软体机器人(外链)</a></li>
      <li>·<a href="/htmlnews/2026/9/572192.shtm" target="_blank">中国工程院院士、能源矿业领域著名科...</a></li>
    </ul></div>
  </div>
</div>
</body></html>
"""

# "更多"页:主列表行 = 标题 + 作者 + 时间;右栏 #topnews 一周排行不算
_SCIENCENET_MORE = """
<html><body>
<div id="topnews"><table><tr>
  <td><a href="/htmlnews/2026/9/579999.shtm">一周排行第一条(右栏)</a></td><td>某某</td><td>2026/9/30 9:00:00</td>
</tr></table></div>
<div id="mleft3">
  <table>
    <tr><td><table><tr>
      <td><a href="/htmlnews/2026/9/572150.shtm">拖延≠懒惰，真相也许是这样</a></td>
      <td>扈原源</td>
      <td>2026/9/27 8:26:42</td>
    </tr></table></td></tr>
    <tr><td><table><tr>
      <td><a href="/htmlnews/2026/9/572192.shtm">中国工程院院士、能源矿业领域著名科学家钮院士逝世</a></td>
      <td>高雅丽</td>
      <td>2026/9/27 10:15:00</td>
    </tr></table></td></tr>
  </table>
</div>
</body></html>
"""


async def test_sciencenet_top_maps_block_and_more_page(monkeypatch):
    urls: list[str] = []

    async def fake_get(**kwargs):
        urls.append(kwargs["url"])
        if kwargs["url"].endswith("topnews.aspx"):
            return _ok(_SCIENCENET_MORE)
        return _ok(_SCIENCENET_HOME)

    monkeypatch.setattr(magazine_sites, "get", fake_get)
    result = await magazine_sites.handle_route(_request("sciencenet-top"), no_cache=True)

    assert result.type == "科学网 · 首页头条"
    assert result.total == 2
    first = result.data[0]
    # 头条区块是编辑挑的,站外链接没有作者和时间(adversarial_review #14)
    assert first.id == "https://news.cn/x.html"
    assert first.desc == "头条摘要内容。"
    assert first.author is None and first.timestamp is None
    second = result.data[1]
    assert second.id == "572150"
    assert second.url == "https://news.sciencenet.cn/htmlnews/2026/9/572150.shtm"
    assert second.author == "扈原源"
    assert second.timestamp == _ms(2026, 9, 27, 8, 26, 42)
    # 右栏 #topnews 的一周排行(579999)不能进 meta
    assert any(url.endswith("topnews.aspx") for url in urls)


async def test_sciencenet_yaowen_replaces_truncated_title(monkeypatch):
    async def fake_get(**kwargs):
        if kwargs["url"].endswith("indexyaowen.aspx"):
            return _ok(_SCIENCENET_MORE)
        return _ok(_SCIENCENET_HOME)

    monkeypatch.setattr(magazine_sites, "get", fake_get)
    result = await magazine_sites.handle_route(_request("sciencenet-yaowen"), no_cache=True)

    assert result.type == "科学网 · 首页要闻"
    assert result.total == 3
    third = result.data[2]
    # 首页截断标题"…..."替换成"更多"页完整标题,并带上作者与时间
    assert third.title == "中国工程院院士、能源矿业领域著名科学家钮院士逝世"
    assert third.author == "高雅丽"
    assert third.timestamp == _ms(2026, 9, 27, 10, 15, 0)
    assert result.data[1].timestamp is None  # 微博外链没有 meta


# ---- 第一财经杂志 ----

_CBN_PAYLOAD = {
    "code": 0,
    "msg": "success",
    "data": [
        {"type": "normal_article", "data": [{
            "id": 34822, "title": "一生只能参加一次的比赛，到底在比什么？｜世赛特别报道",
            "cover_url": "https://imgcdn.cbnweek.com/2026/09/a.jpg", "visit_times": 5424,
            "display_time": "2026-09-27T09:25:00.949Z"}]},
        {"type": "theme", "data": [{
            "id": 900, "name": "世赛特别报道(专题)", "cover_url": "https://imgcdn.cbnweek.com/2026/09/b.jpg",
            "display_time": "2026-09-26T00:00:00.000Z"}]},
        {"type": "sound_article", "data": [{
            "id": 901, "title": "音频:一周编辑精选", "cover_url": "", "visit_times": 800,
            "display_time": "2026-09-25T08:00:00.000Z"}]},
    ],
}


async def test_cbnweek_signature_and_block_routes(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok(dict(_CBN_PAYLOAD))

    monkeypatch.setattr(magazine_sites, "get", fake_get)
    result = await magazine_sites.handle_route(_request("cbnweek-home"), no_cache=True)

    assert captured["url"] == "https://api.cbnweek.com/v5/first_page_infos?per=8&page=1"
    # 前端 getRequest 算法本地复现值(header_matrix 基线)
    assert captured["headers"]["X-Signature"] == "NzMyMjA4MTk0M2ZlYzQ3MzUzMTU5NDNjYWRhNGQxMzU="
    assert captured["headers"]["Origin"] == "https://www.cbnweek.com"
    assert result.type == "第一财经杂志 · 首页推荐"
    assert result.total == 3
    first = result.data[0]
    assert first.id == "34822"
    assert first.url == "https://www.cbnweek.com/article_detail/34822"
    assert first.hot == 5424  # normal_article 显示"N 阅读"
    assert first.timestamp == int(datetime(2026, 9, 27, 9, 25, 0, 949000, tzinfo=UTC).timestamp() * 1000)
    theme = result.data[1]
    assert theme.url == "https://www.cbnweek.com/read_free/900"  # 专题走 read_free
    assert theme.title == "世赛特别报道(专题)"  # 专题用 name
    assert theme.hot is None  # 页面不对专题显示阅读数
    sound = result.data[2]
    assert sound.url == "https://www.cbnweek.com/hot_detail/901"  # 音频走 hot_detail
    assert sound.hot == 800


# ---- 哈佛商业评论中文版 ----

_HBR_PAYLOAD = {
    "code": 200,
    "msg": "成功",
    "data": {
        "focus_articles": [{
            "last_id": "103317882293800000481998", "type": 20,
            "article": {
                "id": 481998, "title": "AI把创新效率拉满，为什么好想法却越来越少？",
                "description": "同样手握大模型，不同团队的创新输出却天差地别。",
                "author": "朱利安·德弗雷塔斯（Julian De Freitas）、阿耶莱特·伊斯雷利（Ayelet Israeli）| 文",
                "publish_time": "2026 年 09 月 01 日",
                "image_url": "http://res.hbrcitic.com/images/2026/09/01/a.png",
            }}],
        "normal_articles": [{
            "type": 22,
            "article": {"id": 481900, "title": "播客:管理者的注意力", "description": "",
                        "author": "哈佛商业评论", "publish_time": "", "image_url": ""},
        }],
    },
}


async def test_hbr_maps_focus_first_and_podcast_link(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok(dict(_HBR_PAYLOAD))

    monkeypatch.setattr(magazine_sites, "get", fake_get)
    result = await magazine_sites.handle_route(_request("hbr-home"), no_cache=True)

    # client_type 必需:不带或 0 返回停在 2025-09 的另一份列表(header_matrix 实测)
    assert "client_type=1" in captured["url"]
    assert captured["headers"]["Referer"] == "https://www.hbrcitic.com/"
    assert result.type == "哈佛商业评论 · 首页推荐"
    assert result.total == 2  # 焦点第 1 条 + 普通列表
    first = result.data[0]
    assert first.id == "481998"
    assert first.url == "https://www.hbrcitic.com/#/article/detail?id=481998"
    assert first.author == "朱利安·德弗雷塔斯（Julian De Freitas）、阿耶莱特·伊斯雷利（Ayelet Israeli）"  # 去"| 文"
    assert first.timestamp == _ms(2026, 9, 1)  # "2026 年 09 月 01 日"当天 0 点
    second = result.data[1]
    assert second.url == "https://www.hbrcitic.com/#/podcast/detail?id=481900"  # type=22 音频
    assert second.timestamp is None


async def test_hbr_error_shell_is_rejected(monkeypatch):
    async def fake_get(**kwargs):
        return _ok({"code": 401, "msg": "unauthorized"})

    monkeypatch.setattr(magazine_sites, "get", fake_get)
    with pytest.raises(RuntimeError, match="unexpected payload"):
        await magazine_sites.handle_route(_request("hbr-home"), no_cache=True)


# ---- 环球科学 ----

_HQKX_HOME = """
<html><body>
<div class="mg-posts-sec mg-posts-modul-6"><div class="mg-posts-sec-inner">
  <article class="d-md-flex mg-posts-sec-post align-items-center">
    <div class="mg-post-thumb back-img md" style="background-image: url('https://www.huanqiukexue.com/wp-content/uploads/2026/09/wechat_image_1-11.jpg');">
      <a class="link-div" href="https://www.huanqiukexue.com/?p=4646"></a></div>
    <div class="mg-sec-top-post py-3 col">
      <h4 class="entry-title title"><a href="https://www.huanqiukexue.com/?p=4646">几点吃和吃什么都会影响你的寿命，经常12点之后吃第一餐很危险!</a></h4>
      <div class="mg-blog-meta">
        <span class="mg-blog-date"><i class="fas fa-clock"></i><a href="https://www.huanqiukexue.com/?m=202609">2026年9月15日</a></span>
        <a class="auth" href="https://www.huanqiukexue.com/?author=3"><i class="fas fa-user-circle"></i>环球科学</a>
      </div>
      <div class="mg-content"><p>每一餐都别太晚</p></div>
    </div>
  </article>
  <article class="d-md-flex mg-posts-sec-post align-items-center">
    <div class="mg-post-thumb back-img md" style="background-image: url('https://www.huanqiukexue.com/wp-content/uploads/2026/09/b.png');"></div>
    <div class="mg-sec-top-post py-3 col">
      <h4 class="entry-title title"><a href="https://www.huanqiukexue.com/?p=4639">第二篇标题</a></h4>
    </div>
  </article>
</div></div>
</body></html>
"""


async def test_huanqiukexue_maps_posts(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok(_HQKX_HOME)

    monkeypatch.setattr(magazine_sites, "get", fake_get)
    result = await magazine_sites.handle_route(_request("huanqiukexue-home"), no_cache=True)

    assert captured["url"] == "https://www.huanqiukexue.com/"
    assert result.type == "环球科学 · 首页推荐"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "4646"  # ?p= 的数字,与名次无关
    assert first.cover == "https://www.huanqiukexue.com/wp-content/uploads/2026/09/wechat_image_1-11.jpg"
    assert first.author == "环球科学"
    assert first.desc == "每一餐都别太晚"
    assert first.timestamp == _ms(2026, 9, 15)  # "2026年9月15日"当天 0 点
    second = result.data[1]
    assert second.id == "4639"
    assert second.author is None and second.timestamp is None


# ---- 入口 ----


async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await magazine_sites.handle_route(_request("aisixiang-top"), no_cache=True)


async def test_default_board_is_ft_hot_weekly():
    assert next(iter(magazine_sites.type_map)) == "ft-hot-weekly"
    assert len(magazine_sites.type_map) == 12

"""tech_blog_feeds 路由测试:fixtures 按证据目录 tmp/board_api/tech_blog_feeds 净化(结构与字段一致,内容摘录)。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import tech_blog_feeds
from whats_hot_api.utils.http_client import RequestResult

_BEIJING = timezone(timedelta(hours=8))
_JST = timezone(timedelta(hours=9))


def _ms(*parts: int) -> int:
    return int(datetime(*parts, tzinfo=_BEIJING).timestamp() * 1000)


def _utc_ms(*parts: int) -> int:
    return int(datetime(*parts, tzinfo=UTC).timestamp() * 1000)


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/tech-blog-feeds",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _ok(data: Any) -> RequestResult:
    return RequestResult(False, "2026-10-01T00:20:00+00:00", data)


# ---- dev.to 公开接口(默认榜 Week / Month / Year) ----

_DEVTO_API_ROWS = [
    {
        "id": 4701626,
        "title": "Clean Code Is Not the Same as Clear Code: Comments Were Never the Problem",
        "url": "https://dev.to/georgekobaidze/clean-code-is-not-the-same-as-clear-code-comments-were-never-the-problem-42n",
        "description": "Table of Contents    A Line That Does Nothing...",
        "tag_list": ["programming", "discuss", "documentation"],
        "comments_count": 109,
        "reading_time_minutes": 9,
        "public_reactions_count": 133,
        "cover_image": "https://media2.dev.to/dynamic/image/width=1000/a.jpeg",
        "social_image": "https://media2.dev.to/dynamic/image/width=1200/a.jpeg",
        "published_at": "2026-09-21T18:07:10Z",
        "user": {"username": "georgekobaidze", "name": "Giorgi Kobaidze"},
    },
    {"id": 1, "title": "", "url": "https://dev.to/x"},  # 缺标题,跳过
    {
        "id": 4701555,
        "title": "Second article",
        "url": "https://dev.to/user2/second-article",
        "description": "",
        "tag_list": "",
        "comments_count": None,
        "reading_time_minutes": None,
        "public_reactions_count": 8,
        "cover_image": None,
        "published_at": "2026-09-20T10:00:00Z",
        "user": {"username": "user2"},
    },
]


@pytest.mark.parametrize("board,days", [("devto-top-week", "7"), ("devto-top-month", "30"), ("devto-top-year", "365")])
async def test_devto_top_maps_api_fields(monkeypatch, board, days):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok([dict(_DEVTO_API_ROWS[0]), _DEVTO_API_ROWS[1], dict(_DEVTO_API_ROWS[2])])

    monkeypatch.setattr(tech_blog_feeds, "get", fake_get)
    result = await tech_blog_feeds.handle_route(_request(board), no_cache=True)

    assert captured["url"] == "https://dev.to/api/articles"
    assert captured["params"] == {"top": days}  # top=1(既有 devto/top)与 top=7 不是同一个榜
    assert result.total == 2
    first = result.data[0]
    assert first.id == "4701626"
    assert first.title.startswith("Clean Code Is Not the Same")
    assert first.url == first.mobileUrl
    assert first.author == "georgekobaidze"
    assert first.hot == 133
    assert first.cover == "https://media2.dev.to/dynamic/image/width=1000/a.jpeg"  # cover_image 优先
    # desc 拼法与 whatshot devto 路由 _article_item 一致
    assert first.desc == (
        "Table of Contents    A Line That Does Nothing... · 标签：programming、discuss、documentation"
        " · 评论：109 · 阅读：9 分钟"
    )
    assert first.timestamp == _utc_ms(2026, 9, 21, 18, 7, 10)
    second = result.data[1]
    assert second.desc is None  # 空摘要 + 无标签 + 无评论/阅读 → None
    assert second.cover is None and second.author == "user2"


# ---- dev.to Infinity(页面同源接口) ----

_DEVTO_STORIES_ROWS = [
    {
        "id": 185402,
        "title": "9 Projects you can do to become a Frontend Master",
        # 接口可能没有 url 字段,只有 path
        "path": "/simonholdorf/9-projects-you-can-do-to-become-a-frontend-master-in-2020-n2h",
        "user": {"username": "simonholdorf", "name": "Simon Holdorf"},
        "main_image": "https://media2.dev.to/dynamic/image/width=1000/b.jpeg",
        "public_reactions_count": 4720,
        "comments_count": 244,
        "reading_time": 7,
        "tag_list": ["react", "vue", "angular"],
        "published_at_int": 1570393193,  # 接口给的就是秒
    },
    {
        "id": 185999,
        "title": "Has absolute url",
        "path": "/someone/has-absolute-url",
        "url": "https://dev.to/someone/has-absolute-url",
        "user": {"username": "someone"},
        "main_image": None,
        "public_reactions_count": 1,
        "comments_count": 0,
        "reading_time": 3,
        "tag_list": [],
        "published_at_int": 1600000000,
    },
]


async def test_devto_infinity_maps_stories_fields(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok([dict(row) for row in _DEVTO_STORIES_ROWS])

    monkeypatch.setattr(tech_blog_feeds, "get", fake_get)
    result = await tech_blog_feeds.handle_route(_request("devto-top-infinity"), no_cache=True)

    assert captured["url"] == "https://dev.to/stories/feed/infinity"
    assert captured["params"] == {"page": "1"}  # 页面首屏滚动加载的第 1 页
    assert result.type == "DEV Community · Top · Infinity"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "185402"
    assert first.url == "https://dev.to/simonholdorf/9-projects-you-can-do-to-become-a-frontend-master-in-2020-n2h"
    assert first.desc == "标签：react、vue、angular · 评论：244 · 阅读：7 分钟"  # 接口没有摘要
    assert first.cover == "https://media2.dev.to/dynamic/image/width=1000/b.jpeg"  # main_image
    assert first.hot == 4720
    assert first.timestamp == 1570393193000  # published_at_int 秒 → 毫秒
    assert result.data[1].url == "https://dev.to/someone/has-absolute-url"  # 有 url 时原样


# ---- 官方 RSS / Atom 子榜 ----

_NODEWEEKLY_RSS = """
<rss version="2.0"><channel><title>Node Weekly</title>
<item><title>Node.js 24 is now LTS</title>
  <link>https://nodeweekly.com/issues/561</link>
  <guid>https://nodeweekly.com/issues/561</guid>
  <pubDate>Thu, 24 Sep 2026 11:00:00 GMT</pubDate>
  <description>This week read and subscribe.</description></item>
<item><title>Older issue</title>
  <link>https://nodeweekly.com/issues/560</link>
  <guid>https://nodeweekly.com/issues/560</guid>
  <pubDate>Thu, 17 Sep 2026 11:00:00 GMT</pubDate>
  <description>Previous week.</description></item>
</channel></rss>
"""


async def test_feed_board_parses_rss_keep_order(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok(_NODEWEEKLY_RSS)

    monkeypatch.setattr(tech_blog_feeds, "get", fake_get)
    result = await tech_blog_feeds.handle_route(_request("nodeweekly"), no_cache=True)

    assert captured["url"] == "https://nodeweekly.com/rss/"  # 其余站点程序 UA 即可,无需特殊头
    assert result.type == "Node Weekly · Issues"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "https://nodeweekly.com/issues/561"  # guid
    assert first.url == "https://nodeweekly.com/issues/561"  # link 原样
    assert first.timestamp == _utc_ms(2026, 9, 24, 11, 0, 0)  # pubDate → 毫秒


_JMLR_RSS = """
<rss version="2.0"><channel><title>JMLR</title>
<item><title>Paper Alpha</title>
  <link>https://jmlr.org/papers/v27/26-001.html</link>
  <guid>https://jmlr.org/papers/v27/26-001.html</guid>
  <description>We study alpha.</description></item>
<item><title>Paper Beta</title>
  <link>https://jmlr.org/papers/v27/26-002.html</link>
  <guid>https://jmlr.org/papers/v27/26-002.html</guid>
  <description>We study beta.</description></item>
</channel></rss>
"""


async def test_jmlr_feed_keeps_order_without_dates(monkeypatch):
    async def fake_get(**kwargs):
        assert kwargs["url"] == "https://jmlr.org/jmlr.xml"  # = 首页 Latest papers
        return _ok(_JMLR_RSS)

    monkeypatch.setattr(tech_blog_feeds, "get", fake_get)
    result = await tech_blog_feeds.handle_route(_request("jmlr"), no_cache=True)

    assert result.total == 2
    assert [item.title for item in result.data] == ["Paper Alpha", "Paper Beta"]  # 无日期,保持 feed 原顺序
    assert all(item.timestamp is None for item in result.data)  # item 没有 pubDate


# ---- anond 人気記事アーカイブ ----

_ANOND_HTML = """
<html lang="ja"><body>
<div class="day">
  <h2><a href="/archive"><span class="title">最近の人気記事</span></a></h2>
  <div class="body"><div class="section">
    <ul class="archives">
      <li>
        <a href="/archive/20260926"><span class="date">2026年09月26日</span></a>
        <ol>
          <li><a href="/20260926093047">世界中の自動車メーカーがもう中国製のEVに太刀打ちできないという事実</a>
            <span class="note"><a href="/20260926093047#tb" class="trackback"><img src="/assets/images/replies.gif" alt="記事への反応" class="pixelated-icon">24</a></span>
            <a href="https://b.hatena.ne.jp/entry/s/anond.hatelabo.jp/20260926093047" class="users"><img src="https://b.hatena.ne.jp/entry/image/https://anond.hatelabo.jp/20260926093047" class="users-image" alt="はてなブックマーク件数" loading="lazy"></a></li>
          <li><a href="/20260926101532">反AIの社会的な居場所が潰されててすげーわ</a></li>
        </ol>
      </li>
    </ul>
  </div></div>
</div>
</body></html>
"""


async def test_anond_maps_diary_ids_and_jst_timestamps(monkeypatch):
    async def fake_get(**kwargs):
        assert kwargs["url"] == "https://anond.hatelabo.jp/archive"
        return _ok(_ANOND_HTML)

    monkeypatch.setattr(tech_blog_feeds, "get", fake_get)
    result = await tech_blog_feeds.handle_route(_request("anond-popular"), no_cache=True)

    assert result.type == "はてな匿名ダイアリー · 人気記事アーカイブ"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "20260926093047"  # 日记 id 就是日本时间发布时刻
    assert first.url == "https://anond.hatelabo.jp/20260926093047"
    assert first.title == "世界中の自動車メーカーがもう中国製のEVに太刀打ちできないという事実"
    assert first.timestamp == int(datetime(2026, 9, 26, 9, 30, 47, tzinfo=_JST).timestamp() * 1000)
    assert result.data[1].hot is None  # はてなブックマーク数是图片,hot 留空


# ---- Product Hunt 首页 Apollo SSR ----

# undefined 是 Apollo SSR 字面量里真实存在的(board_api _js_array_after 处理)
_PH_HTML = """<html><body><script>
(window[Symbol.for("ApolloSSRDataTransport")] ??= []).push({
"corbid":"7ab39196b88458983be2b51aa42d4c48","title":"Top Products Launching Today",
"date":"2026-09-27T11:12:29-07:00","randomization":false,"period":"daily","items":[
{"__typename":"Post","id":"1258630","name":"GPT-6 Sol & Luna","slug":"gpt-6-sol-luna",
 "tagline":"Frontier AI intelligence, now at half the price",
 "product":{"__typename":"Product","id":"594550","slug":"openai"},
 "thumbnailImageUuid":"f904aec8-e324-4aed-ae3b-ff68795ce44f.png",
 "featuredAt":"2026-09-27T00:01:00-07:00","createdAt":"2026-09-27T00:01:00-07:00",
 "latestScore":232,"dailyRank":"1"},
{"__typename":"Ad","id":"ad-1","name":"Sponsored Thing","tagline":"ad"},
{"__typename":"Post","id":"1258701","name":"Second Product","slug":"second-product","tagline":"",
 "product":null,"thumbnailImageUuid":null,"featuredAt":undefined,
 "createdAt":"2026-09-27T01:02:03-07:00","latestScore":12}
]});
</script></body></html>"""


async def test_producthunt_parses_apollo_block_and_skips_ads(monkeypatch):
    async def fake_get(**kwargs):
        assert kwargs["url"] == "https://www.producthunt.com/"
        return _ok(_PH_HTML)

    monkeypatch.setattr(tech_blog_feeds, "get", fake_get)
    result = await tech_blog_feeds.handle_route(_request("producthunt-today"), no_cache=True)

    assert result.total == 2  # __typename=Ad 的广告跳过
    first = result.data[0]
    assert first.id == "1258630"
    assert first.title == "GPT-6 Sol & Luna"
    assert first.url == "https://www.producthunt.com/products/openai"  # /products/<slug>,与页面链接同形
    assert first.desc == "Frontier AI intelligence, now at half the price"
    assert first.cover == "https://ph-files.imgix.net/f904aec8-e324-4aed-ae3b-ff68795ce44f.png"
    assert first.hot == 232  # latestScore 票数
    assert first.timestamp == int(datetime(2026, 9, 27, 0, 1, 0, tzinfo=timezone(timedelta(hours=-7))).timestamp() * 1000)
    second = result.data[1]
    assert second.url == "https://www.producthunt.com/posts/second-product"  # 没有 product 时退 /posts/<slug>
    assert second.timestamp == int(datetime(2026, 9, 27, 1, 2, 3, tzinfo=timezone(timedelta(hours=-7))).timestamp() * 1000)  # featuredAt 是 undefined → 退 createdAt
    assert second.hot == 12


async def test_producthunt_missing_block_is_rejected(monkeypatch):
    async def fake_get(**kwargs):
        return _ok("<html><body>Just a moment...</body></html>")

    monkeypatch.setattr(tech_blog_feeds, "get", fake_get)
    with pytest.raises(RuntimeError, match="Top Products Launching Today"):
        await tech_blog_feeds.handle_route(_request("producthunt-today"), no_cache=True)


# ---- Indie Hackers 首页默认列表 ----

_IH_HOME = """
<html><body>
<div class="homepage">
  <div class="organic" style="grid-area: organic;">
    <div class="story homepage-post normal story--no-image">
      <a class="story__text-link story__link-element" href="/post/how-you-can-save-fx-fees-713528b1c6">
        <h3 class="story__title">How you can save 2-3% of revenue on FX fees</h3></a>
      <div class="story__byline"><div class="user-link story__user-link">
        <a class="user-link__link" href="/Product_Delights"><span class="user-link__name user-link__name--username">Product_Delights</span></a>
      </div></div>
      <div class="story__counts">
        <a class="story__count story__count--likes" title="Like" href="/sign-up"><svg></svg><span class="story__count-number">13</span></a>
        <a class="story__count story__count--comments" href="#"><span class="story__count-number">31</span><span class="story__count-text">comments</span></a>
      </div>
    </div>
    <div class="story homepage-post normal story--no-image">
      <a class="story__text-link story__link-element" href="/product/launchnest-ln-15?post=JDd2mfcugAQRrn8vqBvE#post-JDd2mfcugAQRrn8vqBvE">
        <h3 class="story__title">LaunchNest LN: Where Great Products Get Discovered</h3></a>
      <div class="story__byline"><div class="user-link story__user-link">
        <a class="user-link__link" href="/Launchnest"><span class="user-link__name user-link__name--username">Launchnest</span></a>
      </div></div>
      <div class="story__counts">
        <a class="story__count story__count--likes" title="Like" href="/sign-up"><svg></svg><span class="story__count-number">7</span></a>
      </div>
    </div>
  </div>
  <div class="newest">
    <div class="story"><a class="story__text-link" href="/post/newest-post-abc123"><h3 class="story__title">最新帖(不算)</h3></a></div>
  </div>
</div>
</body></html>
"""


async def test_indiehackers_maps_organic_list_only(monkeypatch):
    async def fake_get(**kwargs):
        assert kwargs["url"] == "https://www.indiehackers.com/"
        return _ok(_IH_HOME)

    monkeypatch.setattr(tech_blog_feeds, "get", fake_get)
    result = await tech_blog_feeds.handle_route(_request("indiehackers-home"), no_cache=True)

    assert result.type == "Indie Hackers · 首页热门"
    assert result.total == 2  # div.newest 不算
    first = result.data[0]
    assert first.id == "713528b1c6"  # 链接末段
    assert first.url == "https://www.indiehackers.com/post/how-you-can-save-fx-fees-713528b1c6"
    assert first.author == "Product_Delights"
    assert first.hot == 13  # 点赞数,评论数 31 不取
    second = result.data[1]
    assert second.id == "JDd2mfcugAQRrn8vqBvE"  # 产品帖取 ?post=
    assert second.hot == 7


# ---- 数据库内核月报目录页 ----

_MYSQL_MONTHLY_HTML = """
<html><body><div class="content typo">
  <ul class="posts"><li>
    <h3><a target="_top" class="main" href="/monthly/2026/08">
        数据库内核月报 － 2026/08
        </a></a></h3>
  </li><li>
    <h3><a target="_top" class="main" href="/monthly/2026/07/">数据库内核月报 － 2026/07</a></h3>
  </li><li>
    <h3><a href="https://unrelated.example.com/page">不是期刊的链接</a></h3>
  </li></ul>
</div></body></html>
"""


async def test_mysql_monthly_maps_issue_index(monkeypatch):
    async def fake_get(**kwargs):
        assert kwargs["url"] == "http://mysql.taobao.org/monthly/"
        return _ok(_MYSQL_MONTHLY_HTML)

    monkeypatch.setattr(tech_blog_feeds, "get", fake_get)
    result = await tech_blog_feeds.handle_route(_request("mysql-monthly"), no_cache=True)

    assert result.type == "数据库内核月报 · 全部期刊"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "2026/08"  # 期号,新的在前(页面顺序)
    assert first.title == "数据库内核月报 － 2026/08"
    assert first.url == "http://mysql.taobao.org/monthly/2026/08"
    assert first.timestamp is None  # 只有年月,timestamp 留空


async def test_empty_parse_is_rejected(monkeypatch):
    async def fake_get(**kwargs):
        return _ok("<html><body><ul class='posts'><li><h3><a href='/x'>y</a></h3></li></ul></body></html>")

    monkeypatch.setattr(tech_blog_feeds, "get", fake_get)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await tech_blog_feeds.handle_route(_request("mysql-monthly"), no_cache=True)


# ---- JavaScript Weekly(RSS 找期号 → 期刊页) ----

_JSWEEKLY_RSS = """
<rss version="2.0"><channel><title>JavaScript Weekly</title>
<item><title>JavaScript desktop apps in under 10MB</title>
  <link>https://javascriptweekly.com/issues/803</link>
  <guid>https://javascriptweekly.com/issues/803</guid>
  <pubDate>Tue, 22 Sep 2026 09:00:00 GMT</pubDate></item>
<item><title>Older issue</title>
  <link>https://javascriptweekly.com/issues/802</link>
  <guid>https://javascriptweekly.com/issues/802</guid>
  <pubDate>Tue, 15 Sep 2026 09:00:00 GMT</pubDate></item>
</channel></rss>
"""

_JSWEEKLY_ISSUE_HTML = """
<html><body>
<table><tr><td>
  <p class="desc"><span class="mainlink"><a href="https://tinyjs.app/" title="tinyjs.app">tinyjs: Build JavaScript Desktop Apps in &lt;10MB</a></span> — I built an app with this and was impressed.</p>
  <p class="name">Tarwin Stroh-Spijer</p>
</td></tr></table>
<table><tr><td>
  <p class="desc"><span class="mainlink"><a href="https://sponsor.example/drizzle">Sponsored Tool</a></span> — Try the official integration.</p>
  <p class="name">ParadeDB <span class="tag-sponsor">sponsor</span></p>
</td></tr></table>
<table><tr><td>
  <p class="desc"><span class="mainlink"><a href="/link/190694/web">Relative link</a></span> — 非外链,跳过。</p>
  <p class="name">Editor</p>
</td></tr></table>
</body></html>
"""


async def test_jsweekly_two_step_skips_sponsor_and_labels_issue(monkeypatch):
    calls: list[str] = []

    async def fake_get(**kwargs):
        calls.append(kwargs["url"])
        if kwargs["url"].endswith("/rss/"):
            return _ok(_JSWEEKLY_RSS)
        return _ok(_JSWEEKLY_ISSUE_HTML)

    monkeypatch.setattr(tech_blog_feeds, "get", fake_get)
    result = await tech_blog_feeds.handle_route(_request("jsweekly-latest"), no_cache=True)

    assert calls == [
        "https://javascriptweekly.com/rss/",  # /issues/latest 返回 400,期号取自 RSS 第一条
        "https://javascriptweekly.com/issues/803",
    ]
    assert result.type == "JavaScript Weekly · 最新一期 · #803（2026-09-22）"  # 期号和日期写进 type
    assert result.total == 1  # sponsor 与站内相对链接跳过
    first = result.data[0]
    assert first.id == "https://tinyjs.app/"  # 外链即 id
    assert first.title == "tinyjs: Build JavaScript Desktop Apps in <10MB"
    assert first.desc == "I built an app with this and was impressed."  # 去掉标题及其前面的部分
    assert first.author == "Tarwin Stroh-Spijer"
    assert first.timestamp is None  # 条目日期即期刊日期,留空


# ---- 遥感学报(猜当月 → 以菜单"当期目录"为准) ----

_YGXB_FUTURE_PAGE = """
<html><body>
<div class="el-menu-item second-menu main-color"><a href="/cn/issue/2026/9" class="link-a main-color">当期目录</a></div>
</body></html>
"""

_YGXB_ISSUE_HTML = """
<html><body>
<li class="backIssueType_two label-content"><div>
  <h3 class="resName" title="高分辨率植被覆盖度遥感产品及算法研究进展">
    <a href="/cn/article/doi/10.11834/jrs.20265237" onclick="toDetails({});return false;">高分辨率植被覆盖度遥感产品及算法研究进展</a>
  </h3>
  <span class="authors clearfix"><em title="杜晓铮, 赵祥" class="authors-text">杜晓铮, 赵祥, 贾坤, 赵嘉诚</em></span>
  <div class="left-right-box"><img class="backIssueType_img" src="https://founder-journal-product.example/img/f001.jpg" alt="配图"></div>
  <em class="em-summary">摘要：植被覆盖度FVC是地表植被覆盖的重要参数。</em>
</div></li>
<li class="backIssueType_two label-content"><div>
  <h3 class="resName"><a href="https://www.ygxb.ac.cn/cn/article/doi/10.11834/jrs.20265238">第二篇论文</a></h3>
</div></li>
</body></html>
"""


class _FixedNow(datetime):
    """固定 _fetch_ygxb 里的北京时间当月猜测(2026-10)。"""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 1, tzinfo=tz or UTC)


async def test_ygxb_follows_menu_current_link(monkeypatch):
    monkeypatch.setattr(tech_blog_feeds, "datetime", _FixedNow)
    calls: list[str] = []

    async def fake_get(**kwargs):
        calls.append(kwargs["url"])
        if kwargs["url"].endswith("/cn/issue/2026/10"):
            return _ok(_YGXB_FUTURE_PAGE)  # 还没出的期次页也 200,0 篇,菜单仍指向 2026/9
        return _ok(_YGXB_ISSUE_HTML)

    monkeypatch.setattr(tech_blog_feeds, "get", fake_get)
    result = await tech_blog_feeds.handle_route(_request("ygxb-latest"), no_cache=True)

    assert calls == [
        "https://www.ygxb.ac.cn/cn/issue/2026/10",  # 先猜当月
        "https://www.ygxb.ac.cn/cn/issue/2026/9",  # 以菜单"当期目录"为准
    ]
    assert result.type == "遥感学报 · 当期目次 · 2026 年第 9 期"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "10.11834/jrs.20265237"  # DOI
    assert first.url == "https://www.ygxb.ac.cn/cn/article/doi/10.11834/jrs.20265237"
    assert first.author == "杜晓铮, 赵祥, 贾坤, 赵嘉诚"
    assert first.desc == "植被覆盖度FVC是地表植被覆盖的重要参数。"  # 去掉"摘要："
    assert first.cover == "https://founder-journal-product.example/img/f001.jpg"
    assert first.timestamp is None  # "更新时间"不一定是发布日期,留空
    assert result.data[1].id == "10.11834/jrs.20265238"  # 绝对链接同样取 DOI
    assert result.data[1].author is None


# ---- 阮一峰科技爱好者周刊(whatshot 需修点:改抓周刊栏目页) ----

_RUANYIFENG_HTML = """
<html><body><div id="content-inner"><div id="alpha"><div id="alpha-inner">
  <h1 id="page-title" class="archive-title"><a href="https://www.ruanyifeng.com/blog/archives.html">分类</a>： 周刊 （共413篇文章）</h1>
  <div class="module-categories module"><div class="module-content">
    <h3 style="font-size:2em;margin-top:1.5em;">2026年</h3>
    <ul class="module-list">
      <li class="module-list-item">
        <a href="https://www.ruanyifeng.com/blog/2026/09/weekly-issue-413.html">科技爱好者周刊（第 413 期）：再见了，React Native</a><span class="RankBar"><span class="hint">（<a href="/cdn-cgi/l/email-protection" class="__cf_email__" data-cfemail="34010674060406021a040d1a050c">[email&#160;protected]</a>）</span></span>
      </li>
      <li class="module-list-item">
        <a href="https://www.ruanyifeng.com/blog/2026/08/weekly-issue-409.html">科技爱好者周刊（第 409 期）：程序员的职业未来</a><span class="RankBar"><span class="hint">（<a href="/cdn-cgi/l/email-protection" class="__cf_email__" data-cfemail="281d1d681a181a1e061810061a19">[email&#160;protected]</a>）</span></span>
      </li>
    </ul>
    <ul class="module-list">
      <li class="module-list-item"><a href="https://www.ruanyifeng.com/blog/network/"><b>Web 杂谈</b></a>（侧栏分类,不算）</li>
    </ul>
  </div></div>
</div></div></div></body></html>
"""


async def test_ruanyifeng_weekly_uses_browser_ua_cfemail_dates_and_issue_ids(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok(_RUANYIFENG_HTML)

    monkeypatch.setattr(tech_blog_feeds, "get", fake_get)
    result = await tech_blog_feeds.handle_route(_request("ruanyifeng-weekly"), no_cache=True)

    # Cloudflare 按 UA 封 curl(min_request.log:curl UA 403、Chrome UA 200),必须带浏览器 UA
    assert captured["url"] == "https://www.ruanyifeng.com/blog/weekly/index.html"  # 周刊栏目页,不是全博客 atom.xml
    assert captured["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert "Chrome" in captured["headers"]["User-Agent"]

    assert result.type == "阮一峰的网络日志 · 科技爱好者周刊"
    assert result.total == 2  # 侧栏"分类"module-list 的非文章链接不算
    first = result.data[0]
    assert first.id == "413"  # 期号
    assert first.url == "https://www.ruanyifeng.com/blog/2026/09/weekly-issue-413.html"
    assert first.title == "科技爱好者周刊（第 413 期）：再见了，React Native"
    # data-cfemail="34010674060406021a040d1a050c" 还原成 "52@2026.09.18",日期按北京时间 0 点
    assert first.timestamp == _ms(2026, 9, 18)
    assert result.data[1].id == "409"
    assert result.data[1].timestamp == _ms(2026, 8, 21)  # cfemail "281d1d…" 还原成 "55@2026.08.21"


# ---- 入口 ----


async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await tech_blog_feeds.handle_route(_request("superlinear-medium"), no_cache=True)


async def test_default_board_and_type_table():
    assert next(iter(tech_blog_feeds.type_map)) == "devto-top-week"  # board_api DEFAULT_TYPE
    assert len(tech_blog_feeds.type_map) == 28
    assert tech_blog_feeds.ROUTE_META["name"] == tech_blog_feeds.ROUTE_NAME == "tech-blog-feeds"
    assert tech_blog_feeds.ROUTE_META["params"]["type"]["type"] is tech_blog_feeds.type_map

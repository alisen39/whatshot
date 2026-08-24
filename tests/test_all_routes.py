"""
Test all routes and their parameter variants against the live API.

Usage:
    uv run pytest tests/test_all_routes.py -v
    uv run pytest tests/test_all_routes.py -v -k "zhihu"        # test single route
    uv run pytest tests/test_all_routes.py -v -k "baidu"        # test all baidu variants
    uv run pytest tests/test_all_routes.py -v --timeout=30      # custom timeout
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from whats_hot_api.app import create_app

app = create_app()

# ---------------------------------------------------------------------------
# Route definitions: (route, type_path, query_string_or_None, description)
#   type_path    — the {type} path segment; "hot" for no-type routes
#   query_string — SECONDARY params only (range/game/sort/province/month/day)
# ---------------------------------------------------------------------------
ROUTE_CASES: list[tuple[str, str, str | None, str]] = [
    # ---- No-param routes (path type = "hot") ----
    ("/zhihu", "hot", None, "知乎-热榜"),
    ("/weibo", "hot", None, "微博-热搜榜"),
    ("/toutiao", "hot", None, "今日头条-热榜"),
    ("/tieba", "hot", None, "百度贴吧-热议榜"),
    ("/douyin", "hot", None, "抖音-热点榜"),
    ("/douban-movie", "new", None, "豆瓣电影-新片榜"),
    ("/douban-book", "hot", None, "豆瓣读书-月度热门图书"),
    ("/douban-group", "hot", None, "豆瓣讨论组-精选"),
    ("/kuaishou", "hot", None, "快手-热点榜"),
    ("/zhihu-daily", "hot", None, "知乎日报-推荐榜"),
    ("/hackernews", "hot", None, "Hacker News"),
    ("/csdn", "hot", None, "CSDN-排行榜"),
    ("/ithome", "hot", None, "IT之家-热榜"),
    ("/ithome-xijiayi", "hot", None, "IT之家-喜加一"),
    ("/jianshu", "hot", None, "简书-热门推荐"),
    ("/thepaper", "hot", None, "澎湃新闻-热榜"),
    ("/qq-news", "hot", None, "腾讯新闻-热点榜"),
    ("/netease-news", "hot", None, "网易新闻-热点榜"),
    ("/huxiu", "hot", None, "虎嗅-24小时"),
    ("/ifanr", "hot", None, "爱范儿-快讯"),
    ("/guokr", "hot", None, "果壳-热门"),
    ("/geekpark", "hot", None, "极客公园"),
    ("/dgtle", "hot", None, "数字尾巴"),
    ("/newsmth", "hot", None, "水木社区-热帖"),
    ("/hupu", "1", None, "虎扑-主干道"),
    ("/hupu", "home", None, "虎扑-首页热门"),
    ("/coolapk", "hot", None, "酷安-热榜"),
    ("/lol", "hot", None, "英雄联盟-更新公告"),
    ("/ngabbs", "hot", None, "NGA-热帖"),
    ("/nodeseek", "hot", None, "NodeSeek"),
    ("/51cto", "hot", None, "51CTO-推荐榜"),
    ("/earthquake", "hot", None, "地震速报"),
    ("/weatheralarm", "hot", None, "气象预警"),
    ("/history", "hot", None, "历史上的今天"),
    ("/yystv", "hot", None, "游研社"),
    ("/gameres", "hot", None, "GameRes"),
    ("/zdf", "hot", None, "周大福-金价实时行情"),
    ("/chow-taifook-hk", "hot", None, "周大福香港-港币品牌金价"),
    ("/china-gold", "hot", None, "中国黄金-人民币品牌金价"),
    ("/lukfook", "mainland", None, "六福珠宝-中国内地人民币品牌金价"),
    ("/lukfook", "hong-kong", None, "六福珠宝-中国香港港币品牌金价"),
    ("/emperor-jewellery", "hot", None, "英皇珠宝-港币品牌金价"),
    ("/caibai", "hot", None, "菜百首饰-人民币品牌金价"),
    ("/chowsangsang", "hot", None, "周生生-人民币品牌金价"),
    ("/laofengxiang-gd", "hot", None, "老凤祥广东-人民币品牌金价"),
    ("/zhouliufu", "hot", None, "周六福-人民币品牌金价"),
    ("/baoqing", "hot", None, "宝庆银楼-人民币品牌金价"),
    ("/beijing-rtj", "hot", None, "融通金北京-贵金属实时行情"),
    ("/cankaoxiaoxi", "hot", None, "参考消息-资讯"),
    ("/solidot", "hot", None, "Solidot-资讯"),
    ("/sputniknewscn", "hot", None, "俄罗斯卫星通讯社-快报"),
    ("/tencent-hot", "hot", None, "腾讯热点"),
    ("/iqiyi-hot-ranklist", "hot", None, "爱奇艺热播榜"),
    ("/qqvideo-tv-hotsearch", "hot", None, "腾讯视频热搜榜"),
    ("/bilibili-hot-search", "hot", None, "哔哩哔哩热搜"),
    ("/bilibili-hot-video", "hot", None, "哔哩哔哩热门视频"),
    ("/bluesky", "hot", None, "Bluesky-热门话题"),
    ("/bluesky", "popular-feeds", None, "Bluesky-热门信息流"),
    ("/qwen-research", "hot", None, "Qwen Research"),
    ("/qwen", "research", None, "Qwen-研究与发布"),
    ("/qwen", "legacy-blog", None, "Qwen-历史博客"),
    ("/uisdc", "hot", None, "优设网-AI 情报"),
    ("/wikipedia", "zh", None, "Wikipedia-中文昨日阅读榜"),
    ("/wikipedia", "en", None, "Wikipedia-英文昨日阅读榜"),
    ("/wikipedia", "ja", None, "Wikipedia-日文昨日阅读榜"),
    ("/gov-policy", "hot", None, "中国政府网-最新政策"),
    ("/gov-law", "hot", None, "国家法律法规数据库-最新法规"),
    ("/miit-policy", "hot", None, "工业和信息化部-政策解读"),
    ("/crowdsupply", "hot", None, "Crowd Supply"),
    ("/lobsters", "hot", None, "Lobsters"),
    ("/openai-news", "hot", None, "OpenAI News"),
    ("/openfda", "hot", None, "openFDA-食品召回"),
    ("/wanfang", "hot", None, "万方数据-科技前沿"),
    # ---- Parameterized routes (type in path) ----
    # baidu
    ("/baidu", "realtime", None, "百度-实时热搜"),
    ("/baidu", "novel", None, "百度-小说"),
    ("/baidu", "movie", None, "百度-电影"),
    ("/baidu", "teleplay", None, "百度-电视剧"),
    ("/baidu", "car", None, "百度-汽车"),
    ("/baidu", "game", None, "百度-游戏"),
    # bilibili
    ("/bilibili", "0", None, "哔哩哔哩-全站"),
    ("/bilibili", "1", None, "哔哩哔哩-动画"),
    ("/bilibili", "3", None, "哔哩哔哩-音乐"),
    ("/bilibili", "4", None, "哔哩哔哩-游戏"),
    # acfun (type in path, range in query)
    ("/acfun", "1", "range=DAY", "AcFun-动画-日榜"),
    ("/acfun", "155", "range=WEEK", "AcFun-生活-周榜"),
    # sina
    ("/sina", "all", None, "新浪-全部"),
    ("/sina", "hotcmnt", None, "新浪-热评"),
    ("/sina", "ent", None, "新浪-娱乐"),
    # sina-news
    ("/sina-news", "1", None, "新浪新闻-国内"),
    ("/sina-news", "2", None, "新浪新闻-国际"),
    ("/sina-news", "5", None, "新浪新闻-军事"),
    # 36kr
    ("/36kr", "hot", None, "36氪-热门"),
    ("/36kr", "video", None, "36氪-视频"),
    ("/36kr", "comment", None, "36氪-评论"),
    ("/36kr", "collect", None, "36氪-收藏"),
    # github
    ("/github", "daily", None, "GitHub-日榜"),
    ("/github", "weekly", None, "GitHub-周榜"),
    ("/github", "monthly", None, "GitHub-月榜"),
    # v2ex
    ("/v2ex", "hot", None, "V2EX-最热"),
    ("/v2ex", "latest", None, "V2EX-最新"),
    ("/v2ex", "share", None, "V2EX-分享"),
    ("/v2ex", "nodes", None, "V2EX-节点"),
    # linuxdo
    ("/linuxdo", "hot", None, "LinuxDo-周榜"),
    ("/linuxdo", "daily", None, "LinuxDo-日榜"),
    ("/linuxdo", "latest", None, "LinuxDo-最新"),
    ("/lesswrong", "frontpage", None, "LessWrong-算法首页"),
    ("/lesswrong", "curated", None, "LessWrong-编辑精选"),
    ("/lesswrong", "new", None, "LessWrong-最新发布"),
    ("/lesswrong", "shortform", None, "LessWrong-短内容"),
    ("/lesswrong", "top-week", None, "LessWrong-本周高分"),
    ("/lesswrong", "top-month", None, "LessWrong-本月高分"),
    ("/lesswrong", "top-year", None, "LessWrong-本年高分"),
    ("/lesswrong", "top-all", None, "LessWrong-历史高分"),
    ("/lichess", "bullet", None, "Lichess-子弹棋"),
    ("/lichess", "blitz", None, "Lichess-超快棋"),
    ("/lichess", "rapid", None, "Lichess-快棋"),
    ("/lichess", "classical", None, "Lichess-慢棋"),
    ("/nowcoder", "trending", None, "牛客-热门帖子"),
    ("/nowcoder", "hot-search", None, "牛客-热搜词"),
    ("/nowcoder", "topics", None, "牛客-热门话题"),
    ("/nowcoder", "recommend", None, "牛客-首页推荐"),
    ("/pixiv", "daily", None, "Pixiv-每日综合"),
    ("/pixiv", "weekly", None, "Pixiv-每周综合"),
    ("/pixiv", "monthly", None, "Pixiv-每月综合"),
    ("/pixiv", "rookie", None, "Pixiv-新人榜"),
    ("/pixiv", "original", None, "Pixiv-原创榜"),
    ("/pixiv", "male", None, "Pixiv-男性向"),
    ("/pixiv", "female", None, "Pixiv-女性向"),
    ("/producthunt", "today", None, "Product Hunt-今日发布"),
    ("/producthunt", "latest", None, "Product Hunt-最新发布"),
    ("/qoder", "blog", None, "Qoder-官方博客"),
    ("/qoder", "changelog", None, "Qoder-更新日志"),
    ("/stackoverflow", "hot", None, "Stack Overflow-热门问题"),
    ("/stackoverflow", "unanswered", None, "Stack Overflow-高票未解决"),
    ("/stackoverflow", "featured", None, "Stack Overflow-悬赏问题"),
    ("/sina-finance", "central-bank", None, "新浪财经-央行"),
    ("/ths-10jqka", "hot-stock", None, "同花顺-热股榜"),
    ("/ths-10jqka", "industry-flow-today", None, "同花顺-行业资金流 · 即时"),
    ("/ths-10jqka", "industry-flow-3d", None, "同花顺-行业资金流 · 3日"),
    ("/ths-10jqka", "industry-flow-5d", None, "同花顺-行业资金流 · 5日"),
    ("/ths-10jqka", "industry-flow-10d", None, "同花顺-行业资金流 · 10日"),
    ("/ths-10jqka", "industry-flow-20d", None, "同花顺-行业资金流 · 20日"),
    ("/ths-10jqka", "concept-flow-today", None, "同花顺-概念资金流 · 即时"),
    ("/ths-10jqka", "concept-flow-3d", None, "同花顺-概念资金流 · 3日"),
    ("/ths-10jqka", "concept-flow-5d", None, "同花顺-概念资金流 · 5日"),
    ("/ths-10jqka", "concept-flow-10d", None, "同花顺-概念资金流 · 10日"),
    ("/ths-10jqka", "concept-flow-20d", None, "同花顺-概念资金流 · 20日"),
    # NewsNow reference additions
    ("/ghxi", "hot", None, "果核剥壳-软件更新"),
    ("/steam", "players", None, "Steam-在线人数榜"),
    ("/steam", "top-sellers", None, "Steam-热销商品榜"),
    ("/36kr-quick", "hot", None, "36氪-快讯"),
    ("/36kr-quick", "quick", None, "36氪-全部快讯"),
    ("/36kr-quick", "quick-hot", None, "36氪-热点快讯"),
    ("/36kr-quick", "quick-stock", None, "36氪-股市快讯"),
    ("/36kr-quick", "quick-company", None, "36氪-公司快讯"),
    ("/36kr-quick", "quick-macro", None, "36氪-宏观快讯"),
    ("/caixin-data", "hot", None, "财新数据通-内容精选"),
    ("/cctv-xinwenlianbo", "hot", None, "央视新闻联播-节目单"),
    ("/xuangubao", "hot", None, "选股宝-研报"),
    ("/investing", "stock", None, "Investing.com-股票市场"),
    ("/investing", "crypto", None, "Investing.com-加密货币"),
    ("/investing", "commodities", None, "Investing.com-大宗商品"),
    ("/investing", "forex", None, "Investing.com-外汇"),
    ("/investing", "economy", None, "Investing.com-经济"),
    ("/investing", "indicators", None, "Investing.com-经济指标"),
    ("/eastmoney-market", "gainers", None, "东方财富-A股涨幅榜"),
    ("/eastmoney-market", "losers", None, "东方财富-A股跌幅榜"),
    ("/eastmoney-market", "main-inflow", None, "东方财富-主力净流入榜"),
    ("/ths-10jqka", "quick", None, "同花顺-快讯"),
    ("/ths-10jqka", "today", None, "同花顺-财经要闻"),
    ("/ths-10jqka", "macro", None, "同花顺-宏观经济"),
    ("/ths-10jqka", "industry", None, "同花顺-产经新闻"),
    ("/ths-10jqka", "global", None, "同花顺-国际财经"),
    ("/ths-10jqka", "market", None, "同花顺-金融市场"),
    ("/ths-10jqka", "company", None, "同花顺-公司新闻"),
    ("/ths-10jqka", "region", None, "同花顺-区域经济"),
    ("/ths-10jqka", "comment", None, "同花顺-财经评论"),
    ("/ths-10jqka", "people", None, "同花顺-财经人物"),
    ("/spaceflight-news", "hot", None, "Spaceflight News-航天新闻"),
    ("/cisa-kev", "hot", None, "CISA KEV-已知被利用漏洞"),
    ("/nvd", "hot", None, "NVD-最新漏洞"),
    ("/nasa-eonet", "hot", None, "NASA EONET-开放自然事件"),
    ("/hdx", "hot", None, "HDX-最新人道数据集"),
    ("/telegram-osint", "intelslava", None, "Telegram OSINT-Intel Slava Z"),
    ("/telegram-osint", "wartranslated", None, "Telegram OSINT-War Translated"),
    ("/launch-library", "hot", None, "Launch Library 2-未来发射任务"),
    ("/noaa-alerts", "hot", None, "NOAA/NWS-严重气象告警"),
    ("/usgs-earthquakes", "hot", None, "USGS-全球地震"),
    ("/usaspending", "hot", None, "USAspending-国防相关合同交易"),
    ("/celestrak", "hot", None, "CelesTrak-近30日新增空间物体"),
    ("/who-outbreaks", "hot", None, "WHO-最新疾病暴发通报"),
    ("/aibase", "hot", None, "AIbase-每日 AI 趋势"),
    ("/apple-podcasts", "cn", None, "Apple Podcasts-中国区 Top 100"),
    ("/apple-podcasts", "us", None, "Apple Podcasts-美国区 Top 100"),
    ("/apple-podcasts", "gb", None, "Apple Podcasts-英国区 Top 100"),
    ("/apple-podcasts", "jp", None, "Apple Podcasts-日本区 Top 100"),
    ("/binance", "volume", None, "Binance-USDT 24h 成交额榜"),
    ("/binance", "gainers", None, "Binance-USDT 24h 涨幅榜"),
    ("/binance", "losers", None, "Binance-USDT 24h 跌幅榜"),
    ("/coingecko", "market-cap", None, "CoinGecko-全球加密货币市值榜"),
    ("/coingecko", "trending", None, "CoinGecko-24h 搜索趋势榜"),
    ("/coingecko", "categories", None, "CoinGecko-加密货币分类市值榜"),
    ("/coingecko", "derivatives", None, "CoinGecko-加密衍生品 24h 成交额榜"),
    ("/coingecko", "exchanges", None, "CoinGecko-加密货币交易所 24h 成交额榜"),
    ("/defillama", "hot", None, "DefiLlama-协议 TVL 排行榜"),
    ("/flathub", "trending", None, "Flathub-两周趋势榜"),
    ("/flathub", "popular", None, "Flathub-月度热门榜"),
    ("/flathub", "recently-added", None, "Flathub-新上架"),
    ("/flathub", "recently-updated", None, "Flathub-最近更新"),
    ("/devto", "feed", None, "DEV Community-精选 RSS"),
    ("/devto", "top", None, "DEV Community-今日热门"),
    ("/devto", "latest", None, "DEV Community-最新发布"),
    ("/google-trends", "US", None, "Google Trends-美国每日趋势"),
    ("/google-trends", "JP", None, "Google Trends-日本每日趋势"),
    ("/google-trends", "GB", None, "Google Trends-英国每日趋势"),
    ("/google-trends", "TW", None, "Google Trends-台湾每日趋势"),
    ("/google-trends", "IN", None, "Google Trends-印度每日趋势"),
    ("/homebrew", "formula-30d", None, "Homebrew-Formula 30 天"),
    ("/homebrew", "formula-90d", None, "Homebrew-Formula 90 天"),
    ("/homebrew", "formula-365d", None, "Homebrew-Formula 365 天"),
    ("/homebrew", "cask-30d", None, "Homebrew-Cask 30 天"),
    ("/homebrew", "cask-90d", None, "Homebrew-Cask 90 天"),
    ("/homebrew", "cask-365d", None, "Homebrew-Cask 365 天"),
    ("/huggingface-papers", "daily", None, "Hugging Face · Daily Papers-Daily Papers"),
    ("/huggingface-papers", "weekly", None, "Hugging Face · Daily Papers-Weekly 热门"),
    ("/douban-movie", "top250", None, "豆瓣电影-Top 250"),
    # hellogithub (sort is secondary; path type = hot)
    ("/hellogithub", "hot", "sort=featured", "HelloGitHub-精选"),
    ("/hellogithub", "hot", "sort=all", "HelloGitHub-全部"),
    # weread
    ("/weread", "rising", None, "微信读书-飙升"),
    ("/weread", "hot_search", None, "微信读书-热搜"),
    ("/weread", "newbook", None, "微信读书-新书"),
    # genshin / honkai / starrail / miyoushe
    ("/genshin", "1", None, "原神-公告"),
    ("/genshin", "2", None, "原神-活动"),
    ("/honkai", "1", None, "崩坏3-公告"),
    ("/starrail", "1", None, "星穹铁道-公告"),
    ("/miyoushe", "1", None, "米游社-公告"),
    ("/miyoushe", "1", "game=2", "米游社-原神公告"),
    # smzdm
    ("/smzdm", "1", None, "什么值得买-今日"),
    ("/smzdm", "7", None, "什么值得买-周榜"),
    # nytimes
    ("/nytimes", "china", None, "纽约时报-中国"),
    ("/nytimes", "global", None, "纽约时报-全球"),
    # hostloc
    ("/hostloc", "hot", None, "全球主机交流-热门"),
    ("/hostloc", "new", None, "全球主机交流-最新"),
    # 52pojie
    ("/52pojie", "hot", None, "吾爱破解-热门"),
    # pcbeta
    ("/pcbeta", "windows11", None, "远景论坛-Windows 11"),
    ("/pcbeta", "windows", None, "远景论坛-Windows"),
    # chongbuluo
    ("/chongbuluo", "hot", None, "虫部落-热门"),
    ("/chongbuluo", "latest", None, "虫部落-最新"),
    # sspai (list-based type; first tag is the default option)
    ("/sspai", "热门文章", None, "少数派-热门文章"),
    # juejin
    ("/juejin", "1", None, "稀土掘金-综合"),
    ("/juejin", "recommend", None, "稀土掘金-首页推荐"),
    ("/yollomi", "all", None, "Yollomi-综合公开作品"),
    ("/yollomi", "images", None, "Yollomi-图片作品"),
    ("/yollomi", "videos", None, "Yollomi-视频作品"),
    ("/youdao", "popular-courses", None, "有道精品课-热门课程"),
    ("/youtube", "videos-daily", None, "YouTube-全球日榜-音乐视频"),
    ("/youtube", "videos-weekly", None, "YouTube-全球周榜-音乐视频"),
    ("/youtube", "tracks-weekly", None, "YouTube-全球周榜-歌曲"),
    ("/youtube", "artists-weekly", None, "YouTube-全球周榜-音乐艺人"),
    ("/youtube", "shorts-daily", None, "YouTube-全球日榜-Shorts歌曲"),
    ("/youtube", "shorts-weekly", None, "YouTube-全球周榜-Shorts歌曲"),
]


def _make_id(route: str, type_path: str, qs: str | None, desc: str) -> str:
    """Generate a readable test ID."""
    suffix = f"?{qs}" if qs else ""
    return f"{route}/{type_path}{suffix} [{desc}]"


@pytest.fixture(scope="module")
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_all_routes_endpoint(client: AsyncClient):
    """Verify /all returns all registered routes with category info."""
    resp = await client.get("/all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 200
    assert data["count"] == len(data["routes"])
    assert data["count"] >= 56
    # Each route should have category metadata
    for route in data["routes"]:
        assert "category" in route
        assert "category_label" in route


@pytest.mark.asyncio
async def test_categories_endpoint(client: AsyncClient):
    """Verify /categories returns category list."""
    resp = await client.get("/categories")
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 200
    assert isinstance(data["categories"], list)
    # At least hotlist category should exist with routes
    hotlist = [c for c in data["categories"] if c["category"] == "hotlist"]
    assert len(hotlist) == 1
    assert hotlist[0]["count"] == 289


@pytest.mark.asyncio
async def test_root_is_api_404(client: AsyncClient):
    """Verify root path is not a rendered home page."""
    resp = await client.get("/")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["code"] == 404


@pytest.mark.asyncio
async def test_robots_txt_not_registered(client: AsyncClient):
    """Verify robots.txt is not registered for the API-only service."""
    resp = await client.get("/robots.txt")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["code"] == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route, type_path, qs, desc",
    ROUTE_CASES,
    ids=[_make_id(r, t, q, d) for r, t, q, d in ROUTE_CASES],
)
async def test_route(
    client: AsyncClient, route: str, type_path: str, qs: str | None, desc: str
):
    """
    Test a single route+params combination.

    Asserts:
    - HTTP 200
    - JSON response with code field
    - If code=200: has name, title, type, data array, total, updateTime, fromCache
    - Each item in data has at least: id, title, url, mobileUrl
    - If code=500: record the error (upstream failure, not a code bug)
    """
    from urllib.parse import quote

    url = f"{route}/{quote(type_path)}"
    if qs:
        url = f"{url}?{qs}"
    resp = await client.get(url, timeout=20)

    # Upstream failures return HTTP 500 with JSON {code: 500, message: ...}
    if resp.status_code == 500:
        try:
            body = resp.json()
            msg = body.get("message", "")
        except Exception:
            msg = resp.text[:120]
        pytest.skip(f"Upstream error (HTTP 500): {msg[:120]}")

    assert resp.status_code == 200, f"HTTP {resp.status_code} for {url}"

    body = resp.json()
    assert "code" in body, f"Missing 'code' in response for {url}"

    if body["code"] == 500:
        pytest.skip(f"Upstream error: {body.get('message', '')[:120]}")

    assert body["code"] == 200, (
        f"code={body['code']} for {url}: {body.get('message', '')}"
    )

    # Validate response structure
    assert "name" in body, f"Missing 'name' for {url}"
    assert "title" in body, f"Missing 'title' for {url}"
    assert "type" in body, f"Missing 'type' for {url}"
    assert "data" in body, f"Missing 'data' for {url}"
    assert "total" in body, f"Missing 'total' for {url}"
    assert "updateTime" in body, f"Missing 'updateTime' for {url}"
    assert "fromCache" in body, f"Missing 'fromCache' for {url}"
    assert isinstance(body["data"], list), f"'data' is not a list for {url}"

    # If data is non-empty, validate item structure
    if body["data"]:
        item = body["data"][0]
        assert "id" in item, f"Missing 'id' in first item of {url}"
        assert "title" in item, f"Missing 'title' in first item of {url}"
        assert "url" in item, f"Missing 'url' in first item of {url}"
        assert "mobileUrl" in item, f"Missing 'mobileUrl' in first item of {url}"


@pytest.mark.asyncio
async def test_route_limit_param(client: AsyncClient):
    """Verify ?limit=N parameter truncates results."""
    resp = await client.get("/weibo/hot?limit=5", timeout=15)
    if resp.status_code == 200:
        body = resp.json()
        if body.get("code") == 200 and body.get("data"):
            assert len(body["data"]) <= 5
            assert body["total"] <= 5


@pytest.mark.asyncio
async def test_route_cache_param(client: AsyncClient):
    """Verify ?cache=false forces fresh fetch."""
    resp = await client.get("/weibo/hot?cache=false", timeout=15)
    if resp.status_code == 200:
        body = resp.json()
        if body.get("code") == 200:
            assert body.get("fromCache") is False


@pytest.mark.asyncio
async def test_404_page(client: AsyncClient):
    """Verify unknown route returns custom 404."""
    resp = await client.get("/nonexistent-route-xyz")
    assert resp.status_code == 404
    assert "404" in resp.text

"""appstore-charts 路由解析测试:三个数据源各覆盖代表性子榜,全部 mock 共享 get。

fixtures 依据 board_api appstore_charts 证据净化(只取结构与字段,公共目录数据):
- 旧版 iTunes RSS:evidence/01_cn_topfreeapplications.response.body
- 儿童网页 + lookup:evidence/kids/20_*、evidence/kids/21_*
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import appstore_charts
from whats_hot_api.utils.http_client import RequestResult

_UPDATE_TIME = "2026-10-01T00:00:00+00:00"


def _request(board_type: str | None = None) -> Request:
    query = f"type={board_type}" if board_type else ""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/appstore-charts",
        "query_string": query.encode(),
        "headers": [],
    })


def _server_data_script(payload: dict[str, Any]) -> str:
    return (
        "<html><script type=\"application/json\" id=\"serialized-server-data\">"
        f"{json.dumps(payload, ensure_ascii=False)}</script></html>"
    )


def _kids_page_payload(cc: str, device: str, chart: str, first: list[dict[str, Any]], rest: list[dict[str, Any]]):
    return {
        "data": [
            {
                "data": {
                    "canonicalURL": f"https://apps.apple.com/{cc}/{device}/charts/36?ageBandId=0&chart={chart}",
                    "ageBandId": 0,
                    "segments": [
                        {
                            "chart": chart,
                            "shelves": [{"items": first}],
                            "nextPage": {"remainingContent": rest},
                        }
                    ],
                }
            }
        ]
    }


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    # 同进程测试不打 1.2s apple.com 限速与 3s 重试等待
    monkeypatch.setattr(appstore_charts, "RATE_LIMIT_SECONDS", 0)
    monkeypatch.setattr(appstore_charts, "RETRY_WAIT_SECONDS", 0)


@pytest.mark.asyncio
async def test_rss_default_board_maps_fields(monkeypatch):
    """缺省 type 是 cn-iphone-free;RSS 字段映射:im:id / im:name / alternate 链接 / 最大图标 / 毫秒时间戳。"""
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, response_type=None, cache_key=None, **kwargs):
        captured.update({"url": url, "headers": headers, "cache_key": cache_key})
        return RequestResult(False, _UPDATE_TIME, {
            "feed": {
                "title": {"label": "iTunes Store：免费 App 排行"},
                "entry": [{
                    "id": {"label": "https://apps.apple.com/cn/app/x/id1485191072?uo=2",
                           "attributes": {"im:id": "1485191072"}},
                    "im:name": {"label": "抖音商城"},
                    "im:image": [
                        {"label": "https://is1-ssl.mzstatic.com/a/53x53bb.png", "attributes": {"height": "53"}},
                        {"label": "https://is1-ssl.mzstatic.com/a/100x100bb.png", "attributes": {"height": "100"}},
                    ],
                    "im:artist": {"label": "Beijing Douyin"},
                    "im:price": {"label": "获取"},
                    "category": {"attributes": {"label": "购物"}},
                    "link": [
                        {"attributes": {"rel": "alternate", "href": "https://apps.apple.com/cn/app/x/id1485191072?uo=2"}},
                        {"attributes": {"rel": "enclosure", "href": "https://is1-ssl.mzstatic.com/preview.jpg"}},
                    ],
                    "im:releaseDate": {"label": "2019-11-08T00:00:00-07:00"},
                }],
            },
        })

    monkeypatch.setattr(appstore_charts, "get", fake_get)
    result = await appstore_charts.handle_route(_request(), no_cache=True)

    assert captured["url"] == "https://itunes.apple.com/cn/rss/topfreeapplications/limit=100/json"
    assert captured["cache_key"] == f"appstore-charts:{captured['url']}"
    assert captured["headers"]["Accept"] == "application/json"
    assert result.type == "中国 iPhone 免费榜"
    assert result.total == 1
    assert result.fromCache is False
    assert result.updateTime == _UPDATE_TIME
    item = result.data[0]
    assert item.id == "1485191072"
    assert item.title == "抖音商城"  # im:name 不带开发者
    assert item.url == "https://apps.apple.com/cn/app/x/id1485191072?uo=2"  # alternate 原链接,保留 ?uo=2
    assert item.cover == "https://is1-ssl.mzstatic.com/a/100x100bb.png"  # height 最大的图标
    assert item.author == "Beijing Douyin"
    assert item.desc == "购物 · 获取"
    assert item.timestamp == 1573196400000  # 首次上架时间,毫秒
    assert item.hot is None  # 榜单只有名次,没有热度数值


@pytest.mark.asyncio
async def test_rss_category_board_builds_genre_url(monkeypatch):
    """分类榜 URL:feed 按设备/榜型取,genre 是分类 id;体育换分类的口径保持 6004。"""
    urls = []

    async def fake_get(url, headers=None, **kwargs):
        urls.append(url)
        return RequestResult(False, _UPDATE_TIME, {"feed": {"entry": []}})

    monkeypatch.setattr(appstore_charts, "get", fake_get)

    await appstore_charts.handle_route(_request("cn-ipad-grossing-games"), no_cache=True)
    assert urls[-1] == (
        "https://itunes.apple.com/cn/rss/topgrossingipadapplications/limit=100/genre=6014/json"
    )

    await appstore_charts.handle_route(_request("cn-iphone-paid-sports"), no_cache=True)
    # 国区付费榜 7016(游戏-体育)0 条,tophub 显示的是 6004 体育 App,该榜用 6004
    assert urls[-1] == "https://itunes.apple.com/cn/rss/toppaidapplications/limit=100/genre=6004/json"

    await appstore_charts.handle_route(_request("cn-iphone-free-games-sports"), no_cache=True)
    assert urls[-1] == (
        "https://itunes.apple.com/cn/rss/topfreeapplications/limit=100/genre=7016/json"
    )


@pytest.mark.asyncio
async def test_rss_single_entry_object_and_zero_entries(monkeypatch):
    """只 1 条时 entry 是对象不是数组;0 条时没有 entry 键,是证据明确的合法态(输出空榜 + message)。"""

    async def fake_get(url, headers=None, **kwargs):
        if "genre=7004" in url:  # board_api evidence/17_*:1 条时 entry 是对象(单条榜样例)
            return RequestResult(False, _UPDATE_TIME, {"feed": {"entry": {
                "id": {"label": "https://apps.apple.com/us/app/y/id1?uo=2", "attributes": {"im:id": "1"}},
                "im:name": {"label": "单条游戏"},
                "link": {"attributes": {"rel": "alternate", "href": "https://apps.apple.com/us/app/y/id1?uo=2"}},
            }}})
        return RequestResult(False, _UPDATE_TIME, {"feed": {"title": {"label": "付费 Mac App 排行"}}})

    monkeypatch.setattr(appstore_charts, "get", fake_get)
    # 国区桌面游戏付费榜在 board_api 就被 SKIP(tophub 没有该组合),用美区同名榜验证单条对象
    single = await appstore_charts.handle_route(_request("us-iphone-paid-games-board"), no_cache=True)
    assert single.total == 1
    assert single.data[0].title == "单条游戏"

    empty = await appstore_charts.handle_route(_request("cn-mac-free"), no_cache=True)
    assert empty.data == []
    assert "没有条目" in (empty.message or "")


@pytest.mark.asyncio
async def test_rss_entry_missing_required_fields_raises(monkeypatch):
    """条目缺 id / 名称 / 链接必须报错,不得静默少条(board_api 口径)。"""

    async def fake_get(url, headers=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, {"feed": {"entry": [
            {"id": {"attributes": {"im:id": "1"}}, "im:name": {"label": "没有链接的条目"}},
            {"id": {"label": "https://apps.apple.com/cn/app/z/id2?uo=2", "attributes": {"im:id": "2"}},
             "im:name": {"label": "正常条目"},
             "link": {"attributes": {"rel": "alternate", "href": "https://apps.apple.com/cn/app/z/id2?uo=2"}}},
        ]}})

    monkeypatch.setattr(appstore_charts, "get", fake_get)
    with pytest.raises(ValueError, match="缺 id / 名称 / 链接"):
        await appstore_charts.handle_route(_request("cn-iphone-free"), no_cache=True)


@pytest.mark.asyncio
async def test_kids_board_two_hop_page_then_lookup(monkeypatch):
    """儿童榜两跳:先网页(top-free 段,第一屏 + remainingContent),再一次 lookup 补齐其余字段。"""
    calls: list[str] = []

    async def fake_get(url, headers=None, response_type=None, **kwargs):
        calls.append(url)
        if url.startswith("https://apps.apple.com/"):
            first = [{
                "adamId": "1031121586",
                "title": "宝宝巴士-儿童早教益智快乐启蒙大全",
                "developerName": "BABYBUS CO.,LTD",
                "icon": {"template": "https://is1-ssl.mzstatic.com/icon.png/{w}x{h}{c}.{f}"},
                "clickAction": {"pageUrl": "https://apps.apple.com/cn/app/%E5%AE%9D%E5%AE%9D/id1031121586"},
            }]
            rest = [{"id": "1624871138", "type": "apps"}]
            return RequestResult(
                False, _UPDATE_TIME,
                _server_data_script(_kids_page_payload("cn", "iphone", "top-free", first, rest)),
            )
        assert url == "https://itunes.apple.com/lookup?id=1031121586,1624871138&country=cn"
        return RequestResult(False, _UPDATE_TIME, {
            "resultCount": 2,
            "results": [
                {"trackId": 1031121586, "trackName": "宝宝巴士-儿童早教益智快乐启蒙大全",
                 "trackViewUrl": "https://apps.apple.com/cn/app/x/id1031121586?uo=4",
                 "artworkUrl100": "https://is1-ssl.mzstatic.com/bb.jpg",
                 "artistName": "BABYBUS CO.,LTD", "genres": ["教育"], "formattedPrice": "免费",
                 "releaseDate": "2015-09-10T06:00:11Z"},
                {"trackId": 1624871138, "trackName": "洪恩识字",
                 "trackViewUrl": "https://apps.apple.com/cn/app/hongen/id1624871138?uo=4",
                 "artworkUrl100": "https://is1-ssl.mzstatic.com/cc.jpg",
                 "artistName": "洪恩", "genres": ["教育"], "formattedPrice": "¥8.00",
                 "releaseDate": "2019-01-01T00:00:00Z"},
            ],
        })

    monkeypatch.setattr(appstore_charts, "get", fake_get)
    result = await appstore_charts.handle_route(_request("cn-iphone-free-kids"), no_cache=True)

    assert calls[0] == "https://apps.apple.com/cn/iphone/charts/36?ageBandId=0&chart=top-free"
    assert result.type == "儿童免费榜[iPhone][国区]"
    assert result.total == 2

    first_item = result.data[0]
    assert first_item.id == "1031121586"
    assert first_item.title == "宝宝巴士-儿童早教益智快乐启蒙大全"  # 第一屏取页面 title
    assert first_item.url == "https://apps.apple.com/cn/app/%E5%AE%9D%E5%AE%9D/id1031121586"  # clickAction.pageUrl
    assert first_item.author == "BABYBUS CO.,LTD"  # 页面 developerName
    assert first_item.desc == "教育 · 免费"  # lookup genres[0] + formattedPrice
    assert first_item.timestamp == 1441864811000  # lookup releaseDate(UTC),毫秒;与 board_api fields_report 一致

    second_item = result.data[1]
    assert second_item.title == "洪恩识字"  # 其余条目取 lookup trackName
    assert second_item.url == "https://apps.apple.com/cn/app/hongen/id1624871138"  # trackViewUrl 去掉 ?uo=4
    assert second_item.cover == "https://is1-ssl.mzstatic.com/cc.jpg"
    assert second_item.timestamp == 1546300800000


@pytest.mark.asyncio
async def test_kids_ipad_board_appends_platform_suffix(monkeypatch):
    """iPad 榜 lookup 条目链接与页面一致,补 ?platform=ipad;页面 URL 用 ipad 路径与 top-paid 段。"""

    async def fake_get(url, headers=None, **kwargs):
        if url.startswith("https://apps.apple.com/"):
            rest = [{"id": "100", "type": "apps"}]
            return RequestResult(
                False, _UPDATE_TIME,
                _server_data_script(_kids_page_payload("cn", "ipad", "top-paid", [], rest)),
            )
        assert url == "https://itunes.apple.com/lookup?id=100&country=cn"
        return RequestResult(False, _UPDATE_TIME, {"resultCount": 1, "results": [
            {"trackId": 100, "trackName": "iPad 付费应用",
             "trackViewUrl": "https://apps.apple.com/cn/app/ipadapp/id100?uo=4",
             "genres": ["教育"], "formattedPrice": "¥6.00", "releaseDate": "2020-05-05T00:00:00Z"},
        ]})

    monkeypatch.setattr(appstore_charts, "get", fake_get)
    result = await appstore_charts.handle_route(_request("cn-ipad-paid-kids"), no_cache=True)
    assert result.data[0].url == "https://apps.apple.com/cn/app/ipadapp/id100?platform=ipad"
    assert result.type == "儿童付费榜[iPad][国区]"


@pytest.mark.asyncio
async def test_kids_region_redirect_is_rejected(monkeypatch):
    """国内 CDN 节点把 /us 302 到 /cn:跟随后 canonicalURL 是国区页面,必须报错,不得把国区当美区。"""

    async def fake_get(url, headers=None, **kwargs):
        payload = _kids_page_payload("cn", "iphone", "top-free", [], [])
        return RequestResult(False, _UPDATE_TIME, _server_data_script(payload))

    monkeypatch.setattr(appstore_charts, "get", fake_get)
    with pytest.raises(ValueError, match="美区"):
        await appstore_charts.handle_route(_request("us-iphone-free-kids"), no_cache=True)


@pytest.mark.asyncio
async def test_kids_lookup_misses_over_limit_raise(monkeypatch):
    """lookup 查不到的条目超过 10 个,说明接口变了,直接报错(board_api 口径)。"""

    async def fake_get(url, headers=None, **kwargs):
        if url.startswith("https://apps.apple.com/"):
            rest = [{"id": str(i), "type": "apps"} for i in range(20)]
            return RequestResult(
                False, _UPDATE_TIME,
                _server_data_script(_kids_page_payload("cn", "iphone", "top-free", [], rest)),
            )
        return RequestResult(False, _UPDATE_TIME, {"resultCount": 0, "results": []})

    monkeypatch.setattr(appstore_charts, "get", fake_get)
    with pytest.raises(ValueError, match="lookup 查不到"):
        await appstore_charts.handle_route(_request("cn-iphone-free-kids"), no_cache=True)


@pytest.mark.asyncio
async def test_kids_product_page_fallback_for_lookup_miss(monkeypatch):
    """lookup 查不到的个别条目(如套装)取商品页补名称 / 链接 / 图标,并在 message 说明。"""
    urls: list[str] = []

    async def fake_get(url, headers=None, **kwargs):
        urls.append(url)
        if url.startswith("https://apps.apple.com/") and "id999" in url:
            payload = {"data": [{"data": {
                "title": "家庭套装",
                "canonicalURL": "https://apps.apple.com/cn/app-bundle/%E5%A5%97%E8%A3%85/id999",
                "lockup": {"icon": {"template": "https://is1-ssl.mzstatic.com/bundle.png/{w}x{h}{c}.{f}"}},
            }}]}
            return RequestResult(False, _UPDATE_TIME, _server_data_script(payload))
        if url.startswith("https://apps.apple.com/"):
            rest = [{"id": "999", "type": "app-bundles"}]
            return RequestResult(
                False, _UPDATE_TIME,
                _server_data_script(_kids_page_payload("cn", "iphone", "top-free", [], rest)),
            )
        return RequestResult(False, _UPDATE_TIME, {"resultCount": 0, "results": []})

    monkeypatch.setattr(appstore_charts, "get", fake_get)
    result = await appstore_charts.handle_route(_request("cn-iphone-free-kids"), no_cache=True)

    assert "https://apps.apple.com/cn/app-bundle/id999" in urls  # 套装走 app-bundle 商品页
    item = result.data[0]
    assert item.title == "家庭套装"
    assert item.url == "https://apps.apple.com/cn/app-bundle/%E5%A5%97%E8%A3%85/id999"
    assert item.cover == "https://is1-ssl.mzstatic.com/bundle.png/100x100bb.jpg"  # 模板填 100x100bb.jpg
    assert "lookup 查不到" in (result.message or "")
    assert "商品页" in (result.message or "")


@pytest.mark.asyncio
async def test_unknown_type_is_rejected(monkeypatch):
    async def fake_get(url, headers=None, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("unknown type 不应发起上游请求")

    monkeypatch.setattr(appstore_charts, "get", fake_get)
    with pytest.raises(ValueError, match="Unknown type"):
        await appstore_charts.handle_route(_request("cn-iphone-cheap"), no_cache=True)


def test_board_table_shape_matches_board_api():
    """466 个子榜与 board_api 同构:458 RSS + 8 儿童;声明序第一个是默认榜(播客榜已并回既有 /apple-podcasts)。"""
    sources: dict[str, int] = {}
    for board in appstore_charts.BOARDS.values():
        sources[board.source] = sources.get(board.source, 0) + 1
    assert sources == {"rss": 458, "kids": 8}
    assert len(appstore_charts.BOARDS) == 466
    assert next(iter(appstore_charts.BOARDS)) == appstore_charts.DEFAULT_TYPE == "cn-iphone-free"
    assert next(iter(appstore_charts.type_map)) == "cn-iphone-free"

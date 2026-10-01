from __future__ import annotations

import re

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import bilibili_rank
from whats_hot_api.utils.http_client import RequestResult

# fixtures 按 captured_data 的结构手工净化构造,不含任何 cookie 原文
_BOOTSTRAP = {
    "buvid3": "test-buvid3",
    "buvid4": "test-buvid4",
    "img_key": "7cd084941338484aae1ad9425b84077c",
    "sub_key": "4932caff0ff746eab6f01bf08b70ac45",
}

_VIDEO_ROW = {
    "bvid": "BV17Eaw6DEMi",
    "title": "示例视频标题",
    "desc": "视频简介",
    "pic": "http://i2.hdslb.com/bfs/archive/cover.jpg",
    "owner": {"name": "UP主甲"},
    "stat": {"view": 2334801},
    "pubdate": 1790221927,
}


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": f"/bilibili-rank/{board_type}",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _patch_bootstrap(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    async def fake_bootstrap(refresh: bool = False) -> dict:
        calls.append({"refresh": refresh})
        return dict(_BOOTSTRAP)

    monkeypatch.setattr(bilibili_rank, "_get_bootstrap", fake_bootstrap)
    return calls


def _patch_sleep(monkeypatch) -> list[float]:
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(bilibili_rank, "_sleep", fake_sleep)
    return waits


def _ok(update_time: str = "2026-10-01T00:00:00+00:00", from_cache: bool = False):
    def wrap(payload):
        return RequestResult(from_cache, update_time, payload)

    return wrap


async def test_video_rank_url_params_and_mapping(monkeypatch):
    _patch_bootstrap(monkeypatch)
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, cache_key=None, **kwargs):
        captured.update({"url": url, "headers": headers, "cache_key": cache_key})
        return _ok()({"code": 0, "message": "0", "data": {"list": [dict(_VIDEO_ROW)]}})

    monkeypatch.setattr(bilibili_rank, "get", fake_get)
    result = await bilibili_rank.handle_route(_request("tech"), no_cache=True)

    # 新版分区 ID:科技数码 rid=1012(旧版 188 已不适用);wbi 签名参数按序拼进 URL
    assert captured["url"].startswith(
        "https://api.bilibili.com/x/web-interface/ranking/v2?"
        "rid=1012&type=all&web_location=333.934&wts="
    )
    assert re.search(r"w_rid=[0-9a-f]{32}$", captured["url"])
    # Referer 必须是发起页地址,不能用首页(首页 Referer 会被判 -352)
    assert captured["headers"]["Referer"] == "https://www.bilibili.com/v/popular/rank/all"
    assert "buvid3=test-buvid3" in captured["headers"]["Cookie"]
    assert "Chrome" in captured["headers"]["User-Agent"]

    assert result.type == "排行榜 · 科技数码"
    assert result.total == 1
    item = result.data[0]
    assert item.id == "BV17Eaw6DEMi"
    assert item.url == "https://www.bilibili.com/video/BV17Eaw6DEMi"
    assert item.mobileUrl == "https://m.bilibili.com/video/BV17Eaw6DEMi"
    assert item.hot == 2334801
    assert item.author == "UP主甲"
    assert item.desc == "视频简介"
    assert item.cover == "https://i2.hdslb.com/bfs/archive/cover.jpg"  # http 升 https
    assert item.timestamp == 1790221927000  # 秒级 pubdate 统一为毫秒


async def test_search_square_signs_subset_and_appends_web_location(monkeypatch):
    _patch_bootstrap(monkeypatch)
    signed_params: list[dict] = []

    def fake_enc_wbi(params, img_key, sub_key):
        signed_params.append(dict(params))
        return "limit=50&platform=web&wts=1700000000&w_rid=" + "ab" * 16

    monkeypatch.setattr(bilibili_rank, "_enc_wbi", fake_enc_wbi)
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, cache_key=None, **kwargs):
        captured.update({"url": url, "headers": headers})
        return _ok()({
            "code": 0,
            "data": {"trending": {"list": [
                {"keyword": "热词 一", "show_name": "热词<em>一</em>", "heat_score": 987654},
            ]}},
        })

    monkeypatch.setattr(bilibili_rank, "get", fake_get)
    result = await bilibili_rank.handle_route(_request("hot"), no_cache=True)

    # 热搜只对 limit / platform / wts 签名;web_location 在签名后追加(与浏览器一致)
    assert signed_params[0].keys() == {"limit", "platform"}
    assert captured["url"] == (
        "https://api.bilibili.com/x/web-interface/wbi/search/square?"
        "limit=50&platform=web&wts=1700000000&w_rid=" + "ab" * 16 + "&web_location=333.337"
    )
    assert captured["headers"]["Referer"] == "https://search.bilibili.com/all"

    item = result.data[0]
    assert item.id == "热词 一"
    assert item.title == "热词<em>一</em>"
    assert item.url == "https://search.bilibili.com/all?keyword=%E7%83%AD%E8%AF%8D%20%E4%B8%80"
    assert item.hot == 987654
    assert item.cover is None


async def test_bootstrap_cached_once_and_refreshed_on_352(monkeypatch):
    fetch_calls: list[dict] = []

    async def fake_fetch_bootstrap() -> dict:
        fetch_calls.append({})
        return dict(_BOOTSTRAP)

    monkeypatch.setattr(bilibili_rank, "_fetch_bootstrap", fake_fetch_bootstrap)

    class FakeCache:
        def __init__(self):
            self.store: dict = {}

        async def get(self, key):
            return self.store.get(key)

        async def set(self, key, value, ttl=None):
            self.store[key] = value

    fake_cache = FakeCache()
    monkeypatch.setattr(bilibili_rank, "cache", fake_cache)
    waits = _patch_sleep(monkeypatch)

    responses = [
        _ok()({"code": -352, "message": "啥都看不到"}),
        _ok()({"code": -352, "message": "啥都看不到"}),
        _ok()({"code": 0, "data": {"list": [dict(_VIDEO_ROW)]}}),
    ]
    seen_urls: list[str] = []

    async def fake_get(url, headers=None, no_cache=None, cache_key=None, **kwargs):
        seen_urls.append(url)
        return responses[len(seen_urls) - 1]

    monkeypatch.setattr(bilibili_rank, "get", fake_get)
    result = await bilibili_rank.handle_route(_request("all"), no_cache=True)

    assert result.total == 1
    # 首次冷取 bootstrap → 缓存生效;两次 -352 各退避并换一套 buvid/密钥重试
    assert len(fetch_calls) == 3
    assert waits == [1.0, 5.0]
    assert fake_cache.store["bilibili-rank-bootstrap"].data["buvid3"] == "test-buvid3"
    assert len(seen_urls) == 3


async def test_error_shells_raise(monkeypatch):
    _patch_bootstrap(monkeypatch)
    _patch_sleep(monkeypatch)

    async def risk_control(url, headers=None, no_cache=None, cache_key=None, **kwargs):
        return _ok()({"code": -352, "message": "啥都看不到"})

    monkeypatch.setattr(bilibili_rank, "get", risk_control)
    with pytest.raises(RuntimeError, match=r"-352.*risk control"):
        await bilibili_rank.handle_route(_request("all"), no_cache=True)

    async def html_shell(url, headers=None, no_cache=None, cache_key=None, **kwargs):
        return RequestResult(False, "t", "<html>请求被拦截</html>")

    monkeypatch.setattr(bilibili_rank, "get", html_shell)
    with pytest.raises(RuntimeError, match="unexpected response envelope"):
        await bilibili_rank.handle_route(_request("all"), no_cache=True)

    async def business_error(url, headers=None, no_cache=None, cache_key=None, **kwargs):
        return _ok()({"code": -400, "message": "请求错误"})

    monkeypatch.setattr(bilibili_rank, "get", business_error)
    with pytest.raises(RuntimeError, match=r"code=-400"):
        await bilibili_rank.handle_route(_request("all"), no_cache=True)

    async def empty_success(url, headers=None, no_cache=None, cache_key=None, **kwargs):
        return _ok()({"code": 0, "data": {"list": []}})

    monkeypatch.setattr(bilibili_rank, "get", empty_success)
    with pytest.raises(RuntimeError, match="returned no items"):
        await bilibili_rank.handle_route(_request("all"), no_cache=True)


async def test_popular_pages_dedup_and_stop_on_no_more(monkeypatch):
    _patch_bootstrap(monkeypatch)
    requests: list[dict] = []

    async def fake_get(url, headers=None, no_cache=None, cache_key=None, **kwargs):
        requests.append({"url": url, "referer": (headers or {}).get("Referer"), "cache_key": cache_key})
        if "pn=1" in url:
            return _ok("t1", from_cache=True)({"code": 0, "data": {"list": [
                dict(_VIDEO_ROW, bvid="BV1a", rcmd_reason={"content": "小编推荐"}),
                dict(_VIDEO_ROW, bvid="BV1b", rcmd_reason={"content": ""}),
            ], "no_more": False}})
        return _ok("t2", from_cache=False)({"code": 0, "data": {"list": [
            dict(_VIDEO_ROW, bvid="BV1a"),  # 翻页间重复稿件
            dict(_VIDEO_ROW, bvid="BV1c", desc=None),
        ], "no_more": True}})

    monkeypatch.setattr(bilibili_rank, "get", fake_get)
    result = await bilibili_rank.handle_route(_request("popular"), no_cache=True)

    assert len(requests) == 2  # no_more 命中后不再翻页
    assert all(r["referer"] == "https://www.bilibili.com/v/popular/all" for r in requests)
    assert [r["cache_key"] for r in requests] == [
        "bilibili-rank:popular:pn1",
        "bilibili-rank:popular:pn2",
    ]

    assert result.type == "综合热门"
    assert [item.id for item in result.data] == ["BV1a", "BV1b", "BV1c"]  # 按 bvid 去重
    assert result.data[0].desc == "小编推荐"  # 综合热门 desc 取推荐理由
    assert result.data[1].desc == "视频简介"  # 无推荐理由时回落到视频简介
    assert result.data[2].desc is None
    assert result.fromCache is False  # 任一页未命中缓存即为 false
    assert result.updateTime == "t2"


async def test_pgc_bangumi_uses_legacy_endpoint_and_maps_fields(monkeypatch):
    _patch_bootstrap(monkeypatch)
    captured = {}

    async def fake_get(url, headers=None, no_cache=None, cache_key=None, **kwargs):
        captured.update({"url": url})
        return _ok()({"code": 0, "result": {"list": [
            {
                "season_id": 1234,
                "title": "示例番剧",
                "rating": "9.8",
                "new_ep": {"index_show": "第12话"},
                "badge": "独家",
                "stat": {"view": 100000},
                "cover": "https://i0.hdslb.com/bfs/bangumi/cover.jpg",
                "url": None,
            },
        ]}})

    monkeypatch.setattr(bilibili_rank, "get", fake_get)
    result = await bilibili_rank.handle_route(_request("bangumi"), no_cache=True)

    assert captured["url"].startswith(
        "https://api.bilibili.com/pgc/web/rank/list?day=3&season_type=1&"
    )
    item = result.data[0]
    assert item.id == "1234"
    assert item.title == "示例番剧"
    assert item.desc == "9.8 · 第12话 · 独家"
    assert item.hot == 100000
    assert item.url == "https://www.bilibili.com/bangumi/play/ss1234"
    assert item.mobileUrl == "https://m.bilibili.com/bangumi/play/ss1234"

    # 非 1 的 season_type 走 season/rank/web/list
    async def fake_get_season(url, headers=None, no_cache=None, cache_key=None, **kwargs):
        captured.update({"url": url})
        return _ok()({"code": 0, "data": {"list": []}})

    monkeypatch.setattr(bilibili_rank, "get", fake_get_season)
    with pytest.raises(RuntimeError, match="returned no items"):
        await bilibili_rank.handle_route(_request("guochuang"), no_cache=True)
    assert captured["url"].startswith("https://api.bilibili.com/pgc/season/rank/web/list?day=3&season_type=4&")


async def test_weekly_resolves_latest_issue_number(monkeypatch):
    _patch_bootstrap(monkeypatch)
    urls: list[str] = []

    async def fake_get(url, headers=None, no_cache=None, cache_key=None, **kwargs):
        urls.append(url)
        if "series/list" in url:
            # 期数列表按期号倒序,第一项是最新一期
            return _ok()({"code": 0, "data": {"list": [{"number": 392}, {"number": 391}]}})
        return _ok()({"code": 0, "data": {
            "config": {"label": "第392期(0925更新)"},
            "list": [dict(_VIDEO_ROW, rcmd_reason="本周必看")],
        }})

    monkeypatch.setattr(bilibili_rank, "get", fake_get)
    result = await bilibili_rank.handle_route(_request("weekly"), no_cache=True)

    assert len(urls) == 2
    assert "series/list" in urls[0]
    assert "series/one" in urls[1] and "number=392" in urls[1]
    assert result.type == "每周必看 · 第392期(0925更新)"
    assert result.data[0].desc == "本周必看"


async def test_precious_and_article_boards(monkeypatch):
    _patch_bootstrap(monkeypatch)
    calls: list[dict] = []

    async def fake_get(url, headers=None, params=None, no_cache=None, cache_key=None, **kwargs):
        calls.append({"url": url, "params": params})
        if "precious" in url:
            return _ok()({"code": 0, "data": {"list": [
                dict(_VIDEO_ROW, achievement="百大作品"),
            ]}})
        return _ok()({"code": 0, "data": [{
            "id": 53147170,
            "title": "示例专栏",
            "summary": "专栏摘要",
            "banner_url": "http://i0.hdslb.com/bfs/article/banner.jpg",
            "image_urls": [],
            "author": {"name": "作者甲"},
            "stats": {"view": 4321},
            "publish_time": 1790000000,
        }]})

    monkeypatch.setattr(bilibili_rank, "get", fake_get)

    precious = await bilibili_rank.handle_route(_request("precious"), no_cache=True)
    assert precious.type == "入站必刷"
    assert precious.data[0].desc == "百大作品"  # 入站必刷 desc 放成就语

    article = await bilibili_rank.handle_route(_request("article"), no_cache=True)
    # 专栏接口不带 WBI 签名,cid 已不区分月/周/日
    assert calls[-1]["url"] == "https://api.bilibili.com/x/article/rank/list"
    assert calls[-1]["params"] == {"cid": 1}
    assert "w_rid" not in calls[-1]["url"]
    assert article.type == "专栏热门"
    assert article.message is not None and "专栏" in article.message
    item = article.data[0]
    assert item.id == "cv53147170"
    assert item.url == "https://www.bilibili.com/read/cv53147170"
    assert item.hot == 4321
    assert item.author == "作者甲"
    assert item.cover == "https://i0.hdslb.com/bfs/article/banner.jpg"
    assert item.timestamp == 1790000000000


async def test_board_registry_shape_and_unknown_type():
    # 声明序第一个是默认榜;26 个子榜与 board_api 一致,含 Core 原先没有的 7 个榜
    assert bilibili_rank.DEFAULT_TYPE == "all"
    assert len(bilibili_rank.BOARD_TYPES) == 26
    for key in ("knowledge", "food", "car", "sports", "animal", "weekly", "precious"):
        assert key in bilibili_rank.BOARD_TYPES

    with pytest.raises(ValueError, match="Unknown board 'nosuch'"):
        await bilibili_rank.handle_route(_request("nosuch"), no_cache=True)

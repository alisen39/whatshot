from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import (
    _weibo_categories,
    weibo_acg,
    weibo_entertainment,
    weibo_life,
    weibo_social,
    weibo_sport,
    weibo_technology,
)
from whats_hot_api.utils.cache import CacheData
from whats_hot_api.utils.http_client import RequestResult

GENVISITOR_URL = "https://passport.weibo.com/visitor/genvisitor"
INCARNATE_URL = "https://passport.weibo.com/visitor/visitor"
BOARD_URL = "https://weibo.com/ajax/statuses/{endpoint}"

GENVISITOR_TEXT = (
    'window.gen_callback && gen_callback({"retcode":20000000,"msg":"succ",'
    '"data":{"tid":"anon-tid","new_tid":true}});'
)
INCARNATE_TEXT = (
    'window.cross_domain && cross_domain({"retcode":20000000,"msg":"succ",'
    '"data":{"sub":"anon-sub","subp":"anon-subp"}});'
)

ROWS = [
    {
        "realpos": 1,
        "rank": 0,
        "word": "锤娜丽莎回应打针减肥质疑",
        "word_scheme": "#锤娜丽莎回应打针减肥质疑#",
        "num": 1188533,
        "category": "艺人",
        "onboard_time": 1788688535,
    },
    {
        "rank": 0,
        "word": "广告位",
        "num": 1000000,
        "is_ad": 1,
    },
    {
        "realpos": 2,
        "rank": 1,
        "word": "丁程鑫手伤是断掉了",
        "word_scheme": "主办方回应丁程鑫手伤是断掉了",
        "num": 303801,
    },
]

CATEGORY_MODULES = [
    (weibo_entertainment, "entertainment", "weibo-entertainment", "entrank"),
    (weibo_social, "social", "weibo-social", "socialevent"),
    (weibo_technology, "technology", "weibo-technology", "tech"),
    (weibo_life, "life", "weibo-life", "life"),
    (weibo_sport, "sport", "weibo-sport", "sport"),
    (weibo_acg, "acg", "weibo-acg", "game"),
]


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/weibo-entertainment/hot",
            "query_string": b"",
            "headers": [],
        }
    )


class _SharedStub:
    """Records shared-wrapper calls; replays the visitor chain then the board."""

    def __init__(self, payload: object, board_update_time: str = "2026-09-06T14:00:00+00:00"):
        self.payload = payload
        self.board_update_time = board_update_time
        self.get_calls: list[dict] = []
        self.post_calls: list[dict] = []

    async def post(self, **kwargs):  # noqa: ANN003
        self.post_calls.append(kwargs)
        return RequestResult(False, "2026-09-06T13:59:59+00:00", GENVISITOR_TEXT)

    async def get(self, **kwargs):  # noqa: ANN003
        self.get_calls.append(kwargs)
        url = kwargs["url"]
        if url == INCARNATE_URL:
            return RequestResult(False, "2026-09-06T13:59:59+00:00", INCARNATE_TEXT)
        return RequestResult(True, self.board_update_time, self.payload)


class _CacheStub:
    def __init__(self, value: object):
        self.value = value
        self.calls: list[str] = []

    async def get(self, key: str):
        self.calls.append(key)
        return self.value


def _install(monkeypatch, stub: _SharedStub, cached_cookie: object = None) -> _CacheStub:
    cache_stub = _CacheStub(
        CacheData(update_time="2026-09-06T13:00:00+00:00", data=cached_cookie)
        if cached_cookie is not None
        else None
    )
    monkeypatch.setattr(_weibo_categories, "cache", cache_stub)
    monkeypatch.setattr(_weibo_categories, "post", stub.post)
    monkeypatch.setattr(_weibo_categories, "get", stub.get)
    return cache_stub


@pytest.mark.asyncio
@pytest.mark.parametrize(("module", "endpoint", "route_name", "cate"), CATEGORY_MODULES)
async def test_category_route_metadata_and_request_chain(
    monkeypatch, module, endpoint, route_name, cate
):
    stub = _SharedShared = _SharedStub({"ok": 1, "data": {"band_list": ROWS}})
    _install(monkeypatch, stub)

    assert module.ROUTE_NAME == route_name
    assert module.ROUTE_META["title"].startswith("微博")
    assert module.ROUTE_META["link"] == f"https://s.weibo.com/top/summary?cate={cate}"

    route_data = await module.handle_route(_request())

    assert route_data.type == "热搜榜"
    assert route_data.total == 2
    assert route_data.fromCache is True
    assert route_data.updateTime == "2026-09-06T14:00:00+00:00"
    assert [item.id for item in route_data.data] == [
        "锤娜丽莎回应打针减肥质疑",
        "丁程鑫手伤是断掉了",
    ]

    assert len(stub.post_calls) == 1
    gen_call = stub.post_calls[0]
    assert gen_call["url"] == GENVISITOR_URL
    assert gen_call["no_cache"] is True
    assert gen_call["response_type"] == "text"
    assert gen_call["body"] == "cb=gen_callback"
    assert gen_call["headers"] == {"Content-Type": "application/x-www-form-urlencoded"}

    assert len(stub.get_calls) == 2
    incarnate_call, board_call = stub.get_calls
    assert incarnate_call["url"] == INCARNATE_URL
    assert incarnate_call["params"] == {"a": "incarnate", "t": "anon-tid", "cb": "cross_domain"}
    assert incarnate_call["response_type"] == "text"
    assert incarnate_call["cache_key"] == "weibo:visitor:cookie"
    assert incarnate_call["ttl"] == 3600

    assert board_call["url"] == BOARD_URL.format(endpoint=endpoint)
    assert board_call["headers"]["Referer"] == "https://weibo.com/"
    assert board_call["headers"]["Cookie"] == "SUB=anon-sub; SUBP=anon-subp"
    assert "no_cache" in board_call


@pytest.mark.asyncio
async def test_category_route_propagates_no_cache(monkeypatch):
    stub = _SharedStub({"ok": 1, "data": {"band_list": ROWS[:1]}})
    cache_stub = _install(monkeypatch, stub, cached_cookie=INCARNATE_TEXT)

    await weibo_entertainment.handle_route(_request(), no_cache=True)

    assert cache_stub.calls == []  # no_cache 必须跳过 cookie 缓存复用
    incarnate_call, board_call = stub.get_calls
    assert incarnate_call["no_cache"] is True
    assert board_call["no_cache"] is True


@pytest.mark.asyncio
async def test_cached_visitor_cookie_skips_bootstrap(monkeypatch):
    stub = _SharedStub({"ok": 1, "data": {"band_list": ROWS[:1]}})
    cache_stub = _install(monkeypatch, stub, cached_cookie=INCARNATE_TEXT)

    await weibo_life.handle_route(_request())

    assert cache_stub.calls == ["weibo:visitor:cookie"]
    assert stub.post_calls == []
    assert len(stub.get_calls) == 1
    board_call = stub.get_calls[0]
    assert board_call["url"] == BOARD_URL.format(endpoint="life")
    assert board_call["headers"]["Cookie"] == "SUB=anon-sub; SUBP=anon-subp"


@pytest.mark.asyncio
async def test_visitor_bootstrap_failure_raises(monkeypatch):
    async def bad_post(**kwargs):  # noqa: ANN003
        return RequestResult(False, "2026-09-06T13:59:59+00:00", "")

    async def unused_get(**kwargs):  # noqa: ANN003
        raise AssertionError("data request must not run after a failed bootstrap")

    monkeypatch.setattr(_weibo_categories, "post", bad_post)
    monkeypatch.setattr(_weibo_categories, "get", unused_get)

    with pytest.raises(RuntimeError, match="genvisitor returned no tid"):
        await weibo_social.handle_route(_request())


def test_parse_band_maps_confirmed_fields():
    data = _weibo_categories._parse_band({"ok": 1, "data": {"band_list": ROWS}})

    assert len(data) == 2
    first, second = data
    assert first.hot == 1188533
    assert first.timestamp == 1788688535000
    assert first.desc is None
    assert first.url == (
        "https://s.weibo.com/weibo?"
        "q=%23%E9%94%A4%E5%A8%9C%E4%B8%BD%E8%8E%8E%E5%9B%9E%E5%BA%94%E6%89%93"
        "%E9%92%88%E5%87%8F%E8%82%A5%E8%B4%A8%E7%96%91%23"
    )
    assert first.mobileUrl == first.url
    assert second.desc == "主办方回应丁程鑫手伤是断掉了"
    assert second.timestamp is None


def test_parse_band_requires_contiguous_unique_ranked_topics():
    gap = [ROWS[0], {**ROWS[2], "realpos": 3}]
    duplicate = [ROWS[0], {**ROWS[2], "word": ROWS[0]["word"]}]

    assert _weibo_categories._parse_band({"ok": 1, "data": {"band_list": gap}}) == []
    assert _weibo_categories._parse_band({"ok": 1, "data": {"band_list": duplicate}}) == []


def test_parse_band_rejects_failed_or_malformed_payloads():
    assert _weibo_categories._parse_band({"ok": 0, "data": {"band_list": ROWS}}) == []
    assert _weibo_categories._parse_band({"ok": 1, "data": {"band_list": "bad"}}) == []
    assert _weibo_categories._parse_band({"ok": 1, "data": {"band_list": [None]}}) == []
    assert _weibo_categories._parse_band("html challenge") == []
    too_many = [{**ROWS[0], "realpos": n, "word": f"话题{n}"} for n in range(1, 52)]
    assert _weibo_categories._parse_band({"ok": 1, "data": {"band_list": too_many}}) == []


def test_source_and_fixtures_carry_no_captured_credentials():
    import inspect

    source = inspect.getsource(_weibo_categories)
    assert "_2AkM" not in source  # captured visitor SUB prefix never enters code
    assert "0033WrSXqPxf" not in source  # captured SUBP prefix never enters code
    for module, *_ in CATEGORY_MODULES:
        assert "_2AkM" not in inspect.getsource(module)

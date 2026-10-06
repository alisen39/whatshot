"""IMDb 榜单路由测试。

fixtures 由 board_api 证据（tmp/board_api/imdb_charts/evidence/01、07 的响应体）净化而来：
截取前几条并同步改小 ``total``，GraphQL 查询语句与请求体结构与抓包原文逐字一致。
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import imdb_charts
from whats_hot_api.utils.http_client import RequestResult

# 以下两条查询语句与 evidence/01_chart_top.request.json、07_boxoffice.request.json 逐字一致
# （board_api 手写并逐字段实测的 GraphQL）。
CAPTURED_CHART_QUERY = (
    "query ImdbChart($chartType: ChartTitleType!, $first: Int!) {\n"
    "  chartTitles(first: $first, chart: {chartType: $chartType}) {\n"
    "    total\n"
    "    pageInfo { hasNextPage }\n"
    "    edges { currentRank node { \n"
    "  id\n"
    "  titleText { text }\n"
    "  titleType { id }\n"
    "  releaseYear { year endYear }\n"
    "  runtime { seconds }\n"
    "  certificate { rating }\n"
    "  ratingsSummary { aggregateRating voteCount }\n"
    "  primaryImage { url }\n"
    "  plot { plotText { plainText } }\n"
    " } }\n"
    "  }\n"
    "}"
)
CAPTURED_BOXOFFICE_QUERY = (
    "query ImdbBoxOffice {\n"
    "  boxOfficeWeekendChart(limit: 10) {\n"
    "    weekendStartDate\n"
    "    weekendEndDate\n"
    "    entries {\n"
    "      weekendGross { total { amount currency } }\n"
    "      title { \n"
    "  id\n"
    "  titleText { text }\n"
    "  titleType { id }\n"
    "  releaseYear { year endYear }\n"
    "  runtime { seconds }\n"
    "  certificate { rating }\n"
    "  ratingsSummary { aggregateRating voteCount }\n"
    "  primaryImage { url }\n"
    "  plot { plotText { plainText } }\n"
    " lifetimeGross(boxOfficeArea: DOMESTIC) { total { amount currency } } }\n"
    "    }\n"
    "  }\n"
    "}"
)

# 净化自 evidence/01_chart_top.response.body（截取前 3 条，total 同步改小）
SHAWSHANK = {
    "currentRank": 1,
    "node": {
        "id": "tt0111161",
        "titleText": {"text": "The Shawshank Redemption"},
        "titleType": {"id": "movie"},
        "releaseYear": {"year": 1994, "endYear": None},
        "runtime": {"seconds": 8520},
        "certificate": {"rating": "R"},
        "ratingsSummary": {"aggregateRating": 9.3, "voteCount": 3243710},
        "primaryImage": {"url": "https://m.media-amazon.com/images/M/abc._V1_.jpg"},
        "plot": {"plotText": {"plainText": "After a banker is sentenced to life in Shawshank Prison."}},
    },
}
GODFATHER = {
    "currentRank": 2,
    "node": {
        "id": "tt0068646",
        "titleText": {"text": "The Godfather"},
        "titleType": {"id": "movie"},
        "releaseYear": {"year": 1972, "endYear": None},
        "runtime": {"seconds": 10500},
        "certificate": {"rating": "R"},
        "ratingsSummary": {"aggregateRating": 9.2, "voteCount": 2259369},
        "primaryImage": {"url": "https://m.media-amazon.com/images/M/def._V1_.jpg"},
        "plot": {"plotText": {"plainText": "The aging patriarch of an organized crime dynasty"}},
    },
}
DARK_KNIGHT = {
    "currentRank": 3,
    "node": {
        "id": "tt0468569",
        "titleText": {"text": "The Dark Knight"},
        "titleType": {"id": "movie"},
        "releaseYear": {"year": 2008, "endYear": None},
        "runtime": {"seconds": 9120},
        "certificate": {"rating": "PG-13"},
        "ratingsSummary": {"aggregateRating": 9.1, "voteCount": 3231684},
        "primaryImage": {"url": "https://m.media-amazon.com/images/M/ghi._V1_.jpg"},
        "plot": {"plotText": {"plainText": "When the Joker wreaks havoc on Gotham"}},
    },
}
BREAKING_BAD = {
    "currentRank": 1,
    "node": {
        "id": "tt0903747",
        "titleText": {"text": "Breaking Bad"},
        "titleType": {"id": "tvSeries"},
        "releaseYear": {"year": 2008, "endYear": 2013},
        "runtime": {"seconds": 2820},
        "certificate": {"rating": "TV-MA"},
        "ratingsSummary": {"aggregateRating": 9.5, "voteCount": 1403912},
        "primaryImage": None,
        "plot": {"plotText": {"plainText": "A chemistry teacher turned meth manufacturer."}},
    },
}

# 净化自 evidence/07_boxoffice.response.body（截取前 2 条）
RESIDENT_EVIL_ENTRY = {
    "weekendGross": {"total": {"amount": 60152878, "currency": "USD"}},
    "title": {
        "id": "tt35538033",
        "titleText": {"text": "Resident Evil"},
        "titleType": {"id": "movie"},
        "releaseYear": {"year": 2026, "endYear": None},
        "runtime": {"seconds": 5640},
        "certificate": {"rating": "R"},
        "ratingsSummary": {"aggregateRating": 7.6, "voteCount": 63084},
        "primaryImage": {"url": "https://m.media-amazon.com/images/M/jkl._V1_.jpg"},
        "plot": {"plotText": {"plainText": "A hapless courier must fight through hordes of mutated creatures."}},
        "lifetimeGross": {"total": {"amount": 87076247, "currency": "USD"}},
    },
}
PRACTICAL_MAGIC_ENTRY = {
    "weekendGross": {"total": {"amount": 12158856, "currency": "USD"}},
    "title": {
        "id": "tt32588798",
        "titleText": {"text": "Practical Magic 2"},
        "titleType": {"id": "movie"},
        "releaseYear": {"year": 2026, "endYear": None},
        "runtime": {"seconds": 7800},
        "certificate": {"rating": "PG-13"},
        "ratingsSummary": {"aggregateRating": 6.3, "voteCount": 9654},
        "primaryImage": {"url": "https://m.media-amazon.com/images/M/mno._V1_.jpg"},
        "plot": {"plotText": {"plainText": "A multi generational family of witches."}},
        "lifetimeGross": {"total": {"amount": 31107542, "currency": "USD"}},
    },
}


def _chart_payload(edges: list[dict], total: int | None = None, has_next: bool = False) -> dict[str, Any]:
    return {
        "data": {
            "chartTitles": {
                "total": len(edges) if total is None else total,
                "pageInfo": {"hasNextPage": has_next},
                "edges": edges,
            }
        }
    }


def _boxoffice_payload(entries: list[dict], start: str = "2026-09-18", end: str = "2026-09-20") -> dict[str, Any]:
    return {
        "data": {
            "boxOfficeWeekendChart": {
                "weekendStartDate": start,
                "weekendEndDate": end,
                "entries": entries,
            }
        }
    }


def _request(board_type: str | None = None) -> Request:
    query_string = f"type={board_type}".encode() if board_type else b""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/imdb-charts",
        "query_string": query_string,
        "headers": [],
    })


@pytest.mark.asyncio
async def test_default_top_board_request_and_item_mapping(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers, "body": body, "no_cache": no_cache})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _chart_payload([SHAWSHANK, GODFATHER, DARK_KNIGHT]))

    monkeypatch.setattr(imdb_charts, "post", fake_post)
    result = await imdb_charts.handle_route(_request(), no_cache=True)

    # 请求：GraphQL endpoint、查询语句与抓包一致，variables 带榜单枚举与一次取全的条数
    assert captured["url"] == "https://caching.graphql.imdb.com/"
    assert captured["body"]["query"] == CAPTURED_CHART_QUERY
    assert captured["body"]["variables"] == {"chartType": "TOP_RATED_MOVIES", "first": 250}
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["headers"]["x-imdb-client-name"]  # 缺了或为空 awselb 直接 403
    assert captured["headers"]["x-imdb-user-country"] == "US"  # 决定标题语言，固定英文原名

    # 响应：字段映射与名次排序
    assert result.name == "imdb-charts"
    assert result.type == "Top 250 电影"
    assert result.link == "https://www.imdb.com/chart/top/"
    assert result.total == 3
    assert result.fromCache is False
    assert result.updateTime == "2026-10-01T00:00:00+00:00"
    first = result.data[0]
    assert (first.id, first.title) == ("tt0111161", "The Shawshank Redemption")
    assert first.url == first.mobileUrl == "https://www.imdb.com/title/tt0111161/"
    assert first.hot == 3243710  # 评分榜 hot 取投票人数
    assert first.cover == "https://m.media-amazon.com/images/M/abc._V1_.jpg"
    assert first.desc == (
        "评分 9.3（3,243,710 人评分） · 1994 · 2h 22m · R · "
        "After a banker is sentenced to life in Shawshank Prison."
    )
    assert first.timestamp is None  # 上映日期不是发布时间，且旧片毫秒值会被误当秒
    assert [item.id for item in result.data] == ["tt0111161", "tt0068646", "tt0468569"]


@pytest.mark.asyncio
async def test_boxoffice_board_uses_boxoffice_query_and_weekend_message(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        captured.update({"url": url, "body": body})
        return RequestResult(True, "2026-10-01T00:00:00+00:00", _boxoffice_payload([RESIDENT_EVIL_ENTRY, PRACTICAL_MAGIC_ENTRY]))

    monkeypatch.setattr(imdb_charts, "post", fake_post)
    result = await imdb_charts.handle_route(_request("boxoffice"), no_cache=True)

    assert captured["body"]["query"] == CAPTURED_BOXOFFICE_QUERY
    assert captured["body"]["variables"] == {}
    assert result.type == "最高票房（美国）"
    assert result.link == "https://www.imdb.com/chart/boxoffice/"
    assert result.message == "美国周末票房：2026-09-18 ~ 2026-09-20"
    assert result.fromCache is True
    first = result.data[0]
    assert first.id == "tt35538033"
    assert first.hot == 60152878  # 票房榜 hot 取周末票房（美元）
    assert first.desc.startswith("周末票房 $60,152,878 · 累计 $87,076,247 · 评分 7.6（63,084 人评分） · 2026 · 1h 34m")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board", "chart_type", "first"),
    [
        ("top", "TOP_RATED_MOVIES", 250),
        ("toptv", "TOP_RATED_TV_SHOWS", 250),
        ("top-english", "TOP_RATED_ENGLISH_MOVIES", 250),
        ("bottom", "LOWEST_RATED_MOVIES", 100),
        ("moviemeter", "MOST_POPULAR_MOVIES", 100),
        ("tvmeter", "MOST_POPULAR_TV_SHOWS", 100),
    ],
)
async def test_each_chart_board_maps_to_captured_enum(monkeypatch, board, chart_type, first):
    captured: dict[str, Any] = {}

    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        captured.update({"body": body})
        return RequestResult(False, "t", _chart_payload([BREAKING_BAD]))

    monkeypatch.setattr(imdb_charts, "post", fake_post)
    result = await imdb_charts.handle_route(_request(board), no_cache=True)

    assert captured["body"]["query"] == CAPTURED_CHART_QUERY
    assert captured["body"]["variables"] == {"chartType": chart_type, "first": first}
    assert result.data[0].id == "tt0903747"
    # 剧集年份写成区间，海报缺失时留空
    assert "2008–2013" in result.data[0].desc
    assert result.data[0].cover is None


@pytest.mark.asyncio
async def test_hot_semantics_rating_vs_meter_boards(monkeypatch):
    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", _chart_payload([BREAKING_BAD]))

    monkeypatch.setattr(imdb_charts, "post", fake_post)
    # 评分榜 hot=投票人数
    top = await imdb_charts.handle_route(_request("top"), no_cache=True)
    assert top.data[0].hot == 1403912
    # 热度榜只按名次排，接口不给名次背后的数值，hot 留空
    meter = await imdb_charts.handle_route(_request("moviemeter"), no_cache=True)
    assert meter.data[0].hot is None


@pytest.mark.asyncio
async def test_graphql_errors_shell_rejected(monkeypatch):
    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {
            "errors": [{"message": "Validation error of type UnknownArgument: 'foo'"}],
        })

    monkeypatch.setattr(imdb_charts, "post", fake_post)
    with pytest.raises(RuntimeError, match="IMDb GraphQL returned errors"):
        await imdb_charts.handle_route(_request("top"), no_cache=True)


@pytest.mark.asyncio
async def test_waf_and_non_json_shell_rejected(monkeypatch):
    # AWS WAF 质询页是 HTML（202 + x-amzn-waf-action: challenge），JSON 解析会失败
    async def fake_html_post(url, headers=None, body=None, no_cache=None, **kwargs):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(imdb_charts, "post", fake_html_post)
    with pytest.raises(RuntimeError, match="WAF"):
        await imdb_charts.handle_route(_request("top"), no_cache=True)

    # 响应壳不是带 data 键的对象（如 202 下被解析成字符串）也拒绝
    async def fake_text_post(url, headers=None, body=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html>challenge</html>")

    monkeypatch.setattr(imdb_charts, "post", fake_text_post)
    with pytest.raises(RuntimeError, match="error shell or WAF"):
        await imdb_charts.handle_route(_request("top"), no_cache=True)


@pytest.mark.asyncio
async def test_chart_count_mismatch_rejected_not_truncated(monkeypatch):
    # 条数变了（如扩成 Top 500）：返回条数与接口声明 total 不符，直接报错
    async def fake_short_post(url, headers=None, body=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", _chart_payload([SHAWSHANK, GODFATHER, DARK_KNIGHT], total=250))

    monkeypatch.setattr(imdb_charts, "post", fake_short_post)
    with pytest.raises(RuntimeError, match="total=250"):
        await imdb_charts.handle_route(_request("top"), no_cache=True)

    async def fake_paged_post(url, headers=None, body=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", _chart_payload([SHAWSHANK], total=1, has_next=True))

    monkeypatch.setattr(imdb_charts, "post", fake_paged_post)
    with pytest.raises(RuntimeError, match="hasNextPage|total=1"):
        await imdb_charts.handle_route(_request("top"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_board_rejected_and_empty_edges_rejected(monkeypatch):
    with pytest.raises(ValueError, match="Unknown board"):
        await imdb_charts.handle_route(_request("foo"), no_cache=True)

    async def fake_empty_post(url, headers=None, body=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", _chart_payload([]))

    monkeypatch.setattr(imdb_charts, "post", fake_empty_post)
    with pytest.raises(RuntimeError, match="no edges"):
        await imdb_charts.handle_route(_request("top"), no_cache=True)

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import tiktok
from whats_hot_api.utils.http_client import RequestResult


def _request(query: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/tiktok/hashtags",
        "query_string": query,
        "headers": [],
    })


def _base() -> dict:
    return {"BaseResp": {"StatusCode": 0, "StatusMessage": ""}}


def _curve() -> list[dict]:
    return [
        {"timestamp": str(1783468800 + index * 86400), "value": index * 10.0}
        for index in range(7)
    ]


def _hashtag(
    hashtag_id: object = "1598391085330438",
    rank: int = 1,
    **overrides: object,
) -> dict:
    row = {
        "hashtagID": hashtag_id,
        "hashtagName": "rainbowpfp",
        "rankIndex": rank,
        "publishCnt": 89781,
        "vv": 82270700,
        "popularityCurve": _curve(),
    }
    row.update(overrides)
    return row


def _hashtag_payload(*rows: dict) -> dict:
    return {
        **_base(),
        "items": list(rows),
        "pagination": {
            "hasMore": False,
            "limit": len(rows),
            "page": 1,
            "totalCount": len(rows),
        },
    }


def _video(
    item_id: object = 7601361448245218591,
    views: int = 360822865,
    **info_overrides: object,
) -> dict:
    info = {
        "itemID": item_id,
        "contentType": 1,
        "createTime": 1769829894,
        "title": "Big moment coming 💥 #livefest2025",
    }
    info.update(info_overrides)
    return {
        "itemInfo": info,
        "itemAuthorInfo": {"handlerName": "kekepalmer", "nickName": "Keke™"},
        "itemAuthorMetrics": {"followers": 9043680},
        "itemMetrics": {"videoViews": views, "engagementRate": 0.001},
        "contentTags": [{"contentLabelID": 11007, "contentLabelName": "Sports & Outdoor"}],
    }


def _video_payload(*rows: dict) -> dict:
    return {
        **_base(),
        "entityInfos": list(rows),
        "pagination": {
            "hasMore": True,
            "limit": len(rows),
            "page": 1,
            "pageCount": 25,
            "totalCount": 100,
        },
    }


def test_tiktok_hashtag_parser_preserves_rank_and_identity() -> None:
    second = _hashtag("7659867926865903649", 2, hashtagName="marvelrivalss9", vv=46105243)
    rows = tiktok._parse_hashtags(_hashtag_payload(_hashtag(), second))

    assert [row.id for row in rows] == ["1598391085330438", "7659867926865903649"]
    assert rows[0].title == "#rainbowpfp"
    assert rows[0].hot == 82270700
    assert rows[0].desc == "近 7 日发布量：89781"
    assert rows[0].url == (
        "https://ads.tiktok.com/creative/creativeCenter/trends/hashtag/"
        "1598391085330438?period=7&region=US"
    )


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("hashtagID", "bad"),
        ("hashtagName", ""),
        ("rankIndex", 2),
        ("vv", -1),
        ("popularityCurve", []),
    ],
)
def test_tiktok_hashtag_parser_rejects_invalid_identity_or_window(
    override: str,
    value: object,
) -> None:
    assert tiktok._parse_hashtags(_hashtag_payload(_hashtag(**{override: value}))) == []


def test_tiktok_video_parser_preserves_views_order_and_canonical_url() -> None:
    second = _video(7637621329239264542, 188799212, title="World Cup vibes")
    rows = tiktok._parse_videos(_video_payload(_video(), second))

    assert [row.id for row in rows] == ["7601361448245218591", "7637621329239264542"]
    assert rows[0].author == "kekepalmer"
    assert rows[0].hot == 360822865
    assert rows[0].timestamp == 1769829894000
    assert rows[0].desc == "粉丝：9043680 · 分类：Sports & Outdoor"
    assert rows[0].url == "https://www.tiktok.com/@kekepalmer/video/7601361448245218591"


def test_tiktok_video_parser_rejects_reversed_view_order() -> None:
    payload = _video_payload(_video(1, 100), _video(2, 101))
    assert tiktok._parse_videos(payload) == []


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("itemID", "bad"),
        ("contentType", 2),
        ("title", ""),
        ("createTime", 0),
    ],
)
def test_tiktok_video_parser_rejects_invalid_video_identity(
    override: str,
    value: object,
) -> None:
    assert tiktok._parse_videos(_video_payload(_video(**{override: value}))) == []


def test_tiktok_parsers_reject_failed_or_spoofed_pagination() -> None:
    failed = _hashtag_payload(_hashtag())
    failed["BaseResp"]["StatusCode"] = 1
    assert tiktok._parse_hashtags(failed) == []

    spoofed = _video_payload(_video())
    spoofed["pagination"]["page"] = 2
    assert tiktok._parse_videos(spoofed) == []


@pytest.mark.asyncio
async def test_tiktok_route_fetches_fixed_hashtag_board(monkeypatch) -> None:
    async def fake_post(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == tiktok._HASHTAG_URL
        assert kwargs["body"] == tiktok._HASHTAG_BODY
        assert kwargs["cache_key"] == "tiktok:creative-center:hashtags:us:7d"
        return RequestResult(
            data=_hashtag_payload(_hashtag()),
            from_cache=False,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(tiktok, "post", fake_post)
    result = await tiktok.handle_route(_request(b"type=hashtags"), True)

    assert result.name == "tiktok"
    assert result.type == "美国近 7 日热门话题"
    assert result.total == 1


@pytest.mark.asyncio
async def test_tiktok_route_fetches_overview_then_fixed_video_board(monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_get(**kwargs):  # noqa: ANN003
        calls.append(kwargs)
        if kwargs["url"] == tiktok._OVERVIEW_URL:
            return RequestResult(
                data={**_base(), "lastDailyEndTimestamp": 1783987200},
                from_cache=True,
                update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
            )
        return RequestResult(
            data=_video_payload(_video()),
            from_cache=False,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(tiktok, "get", fake_get)
    result = await tiktok.handle_route(_request(b"type=videos"), True)

    assert [call["url"] for call in calls] == [tiktok._OVERVIEW_URL, tiktok._VIDEO_URL]
    assert calls[1]["params"] == {
        "periodDimension": 5,
        "periodEndTimestamp": 1783987200,
        "orderByMetric": 1,
        "countryCode": "US",
        "contentLabelIDs": "",
        "organicOnly": False,
        "limit": 20,
        "page": 1,
    }
    assert result.type == "美国近 30 日热门视频"
    assert result.total == 1

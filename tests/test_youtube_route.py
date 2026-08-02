from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import youtube
from whats_hot_api.utils.http_client import RequestResult


def _request(query: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/youtube/videos-daily",
            "query_string": query,
            "headers": [],
        }
    )


def _bootstrap_html(*, duplicate: bool = False, visitor: str = "visitor") -> str:
    config = {
        "INNERTUBE_CLIENT_NAME": "WEB_MUSIC_ANALYTICS",
        "INNERTUBE_CLIENT_VERSION": "2.0",
        "INNERTUBE_CONTEXT": {
            "client": {
                "clientName": "WEB_MUSIC_ANALYTICS",
                "clientVersion": "2.0",
                "visitorData": visitor,
            }
        },
    }
    call = f"ytcfg.set({json.dumps(config)});"
    return f"<html><script>{call}{call if duplicate else ''}</script></html>"


def _row(board_type: str, rank: int, count: int) -> dict:
    metadata = {
        "currentPosition": rank,
        "previousPosition": 0 if rank == count else rank,
        "percentViewsChange": -0.01 if rank == count else 0.02,
        "periodsOnChart": rank,
    }
    if board_type == "artists-weekly":
        return {
            "id": f"/m/artist_{rank}",
            "name": f"Artist {rank}",
            "viewCount": str(1_000_000 - rank),
            "isLaunched": rank % 2 == 0,
            "chartEntryMetadata": metadata,
            "isVisible": True,
        }
    if board_type.startswith("videos-"):
        video_id = f"{rank:011d}"
        return {
            "id": video_id,
            "title": f"Video {rank}",
            "viewCount": str(1_000_000 - rank),
            "thumbnail": {
                "thumbnails": [
                    {
                        "url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                        "width": 480,
                        "height": 360,
                    },
                    {
                        "url": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                        "width": 1920,
                        "height": 1080,
                    },
                ]
            },
            "videoDuration": 180 + rank,
            "chartEntryMetadata": metadata,
            "isAvailable": True,
            "artists": [{"kgMid": "/m/artist", "name": f"Artist {rank}"}],
            "isVisible": True,
            "releaseDate": {"year": 2026, "month": 7, "day": 1},
            "externalChannelId": f"UC{rank:022d}",
            "channelName": f"Channel {rank}",
        }
    video_id = f"{rank:011d}"
    row = {
        "id": f"G:{rank:011d}",
        "name": f"Song {rank}",
        "thumbnail": {
            "thumbnails": [
                {
                    "url": f"https://yt3.googleusercontent.com/song-{rank}=w180-h180-l90-rj",
                    "width": 180,
                    "height": 180,
                }
            ]
        },
        "encryptedVideoId": video_id,
        "chartEntryMetadata": metadata,
        "artists": [{"name": f"Artist {rank}"}],
        "isVisible": True,
        "releaseDate": {"year": 2025, "month": 12, "day": 31},
    }
    if board_type == "tracks-weekly":
        row["viewCount"] = str(1_000_000 - rank)
    return row


def _chart_payload(board_type: str) -> dict:
    spec = youtube._BOARD_SPECS[board_type]
    count = int(spec["count"])
    end_date = "2026-07-16" if spec["period"] == "DAILY" else "2026-07-09"
    group = {
        "listType": spec["list_type"],
        "chartPeriodType": f"CHART_PERIOD_TYPE_{spec['period']}",
        "endDate": end_date,
        str(spec["row_key"]): [_row(board_type, rank, count) for rank in range(1, count + 1)],
    }
    content = {
        "perspectiveMetadata": {
            "requestParams": {
                "perspective": "CHART_DETAILS",
                "chartParams": {
                    "countryCode": "global",
                    "chartType": f"CHART_TYPE_{spec['chart_type']}",
                    "chartPeriodType": f"CHART_PERIOD_TYPE_{spec['period']}",
                },
            },
            "availableChartsInfo": [
                {
                    "chartType": f"CHART_TYPE_{spec['chart_type']}",
                    "chartPeriodType": f"CHART_PERIOD_TYPE_{spec['period']}",
                    "earliestEndDate": "2023-11-06",
                    "latestEndDate": end_date,
                }
            ],
        },
        str(spec["section"]): [group],
    }
    return {
        "contents": {
            "sectionListRenderer": {
                "contents": [{"musicAnalyticsSectionRenderer": {"content": content}}]
            }
        }
    }


def test_youtube_bootstrap_extracts_one_official_analytics_context() -> None:
    context = youtube._parse_bootstrap(_bootstrap_html())
    assert context is not None
    assert context["client"]["visitorData"] == "visitor"
    assert youtube._parse_bootstrap(_bootstrap_html(duplicate=True)) is None
    assert youtube._parse_bootstrap(_bootstrap_html(visitor="")) is None
    assert youtube._parse_bootstrap("<html></html>") is None


@pytest.mark.parametrize("board_type", list(youtube.type_map))
def test_youtube_parser_preserves_complete_official_board(board_type: str) -> None:
    rows = youtube._parse_chart(_chart_payload(board_type), board_type)
    expected_count = int(youtube._BOARD_SPECS[board_type]["count"])

    assert len(rows) == expected_count
    assert len({row.id for row in rows}) == expected_count
    assert "榜期 2026-07-" in (rows[0].desc or "")
    assert rows[-1].desc is not None and "本期上榜" in rows[-1].desc
    if board_type == "artists-weekly":
        assert rows[0].url == "https://charts.youtube.com/artist/%2Fm%2Fartist_1"
        assert rows[0].hot == 999_999
    elif board_type.startswith("videos-"):
        assert rows[0].id == "00000000001"
        assert rows[0].cover == "https://i.ytimg.com/vi/00000000001/maxresdefault.jpg"
        assert rows[0].timestamp == 1_782_864_000_000
    elif board_type.startswith("shorts-"):
        assert rows[0].hot is None
        assert rows[0].url == "https://www.youtube.com/source/00000000001/shorts"
    else:
        assert rows[0].hot == 999_999
        assert rows[0].url == "https://www.youtube.com/watch?v=00000000001"


@pytest.mark.parametrize(
    "mutation",
    ["rank", "duplicate", "count", "request", "stale", "visibility", "ascending"],
)
def test_youtube_parser_rejects_incomplete_or_inconsistent_chart(mutation: str) -> None:
    payload = _chart_payload("videos-daily")
    content = payload["contents"]["sectionListRenderer"]["contents"][0][
        "musicAnalyticsSectionRenderer"
    ]["content"]
    rows = content["videos"][0]["videoViews"]
    if mutation == "rank":
        rows[0]["chartEntryMetadata"]["currentPosition"] = 2
    elif mutation == "duplicate":
        rows[1]["id"] = rows[0]["id"]
    elif mutation == "count":
        rows.pop()
    elif mutation == "request":
        content["perspectiveMetadata"]["requestParams"]["chartParams"]["countryCode"] = "US"
    elif mutation == "stale":
        content["perspectiveMetadata"]["availableChartsInfo"][0]["latestEndDate"] = "2026-07-17"
    elif mutation == "visibility":
        rows[0]["isVisible"] = False
    elif mutation == "ascending":
        rows[1]["viewCount"] = "2000000"

    assert youtube._parse_chart(payload, "videos-daily") == []


def test_youtube_parser_rejects_wrong_thumbnail_identity() -> None:
    payload = _chart_payload("videos-daily")
    rows = payload["contents"]["sectionListRenderer"]["contents"][0][
        "musicAnalyticsSectionRenderer"
    ]["content"]["videos"][0]["videoViews"]
    rows[0]["thumbnail"]["thumbnails"] = [
        {
            "url": "https://i.ytimg.com/vi/wrong_id_00/hqdefault.jpg",
            "width": 480,
            "height": 360,
        }
    ]
    assert youtube._parse_chart(payload, "videos-daily") == []


def test_youtube_parser_accepts_upstream_reentry_and_blank_artist_placeholder() -> None:
    payload = _chart_payload("tracks-weekly")
    rows = payload["contents"]["sectionListRenderer"]["contents"][0][
        "musicAnalyticsSectionRenderer"
    ]["content"]["trackTypes"][0]["trackViews"]
    rows[0]["chartEntryMetadata"].pop("previousPosition")
    rows[1]["artists"].append({"name": ""})

    parsed = youtube._parse_chart(payload, "tracks-weekly")
    assert len(parsed) == 100
    assert "本期上榜" in (parsed[0].desc or "")
    assert parsed[1].author == "Artist 2"


@pytest.mark.asyncio
async def test_youtube_route_bootstraps_dynamic_context_and_posts_fixed_chart(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    async def fake_get(**kwargs):  # noqa: ANN003
        calls.append(("get", kwargs))
        return RequestResult(
            data=_bootstrap_html(),
            from_cache=True,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    async def fake_post(**kwargs):  # noqa: ANN003
        calls.append(("post", kwargs))
        query = parse_qs(kwargs["body"]["query"])
        assert kwargs["body"]["browseId"] == "FEmusic_analytics_charts_home"
        assert query == {
            "perspective": ["CHART_DETAILS"],
            "chart_params_country_code": ["global"],
            "chart_params_chart_type": ["SHORTS_TRACKS_BY_USAGE"],
            "chart_params_period_type": ["WEEKLY"],
        }
        assert kwargs["headers"]["X-Youtube-Client-Name"] == "31"
        assert kwargs["cache_key"] == "youtube:charts:shorts-weekly"
        return RequestResult(
            data=_chart_payload("shorts-weekly"),
            from_cache=False,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(youtube, "get", fake_get)
    monkeypatch.setattr(youtube, "post", fake_post)
    result = await youtube.handle_route(_request(b"type=shorts-weekly"), True)

    assert [call[0] for call in calls] == ["get", "post"]
    assert result.name == "youtube"
    assert result.type == "全球周榜 · Shorts 歌曲"
    assert result.total == 50
    assert result.fromCache is False


@pytest.mark.asyncio
async def test_youtube_route_falls_back_to_daily_videos(monkeypatch) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        return RequestResult(
            data=_bootstrap_html(),
            from_cache=True,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    async def fake_post(**kwargs):  # noqa: ANN003
        return RequestResult(
            data=_chart_payload("videos-daily"),
            from_cache=True,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(youtube, "get", fake_get)
    monkeypatch.setattr(youtube, "post", fake_post)
    result = await youtube.handle_route(_request(b"type=recommended"))
    assert result.type == "全球日榜 · 音乐视频"
    assert result.total == 100

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from urllib.parse import quote, urlencode, urlparse

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get, post

ROUTE_NAME = "youtube"

type_map: dict[str, str] = {
    "videos-daily": "全球日榜 · 音乐视频",
    "videos-weekly": "全球周榜 · 音乐视频",
    "tracks-weekly": "全球周榜 · 歌曲",
    "artists-weekly": "全球周榜 · 音乐艺人",
    "shorts-daily": "全球日榜 · Shorts 歌曲",
    "shorts-weekly": "全球周榜 · Shorts 歌曲",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "YouTube",
    "description": "YouTube Charts 官方全球音乐视频、歌曲、艺人与 Shorts 歌曲榜",
    "params": {
        "type": {
            "name": "榜单类型",
            "type": type_map,
        },
    },
    "link": "https://charts.youtube.com/charts/TopVideos/global/daily",
}

_ORIGIN = "https://charts.youtube.com"
_BOOTSTRAP_URL = f"{_ORIGIN}/charts/TopVideos/global/weekly"
_API_URL = f"{_ORIGIN}/youtubei/v1/browse?prettyPrint=false"
_BROWSE_ID = "FEmusic_analytics_charts_home"
_CLIENT_NAME = "WEB_MUSIC_ANALYTICS"
_CLIENT_NAME_NUMBER = "31"
_CLIENT_VERSION = "2.0"
_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
_SONG_ID_RE = re.compile(r"G:[A-Za-z0-9_-]{6,64}")
_ARTIST_ID_RE = re.compile(r"/(?:m|g)/[A-Za-z0-9_-]+")

_BOARD_SPECS: dict[str, dict[str, object]] = {
    "videos-daily": {
        "chart_type": "VIDEOS",
        "period": "DAILY",
        "section": "videos",
        "row_key": "videoViews",
        "kind": "video",
        "count": 100,
        "list_type": "TOP_VIEWS_CHART",
        "referer": f"{_ORIGIN}/charts/TopVideos/global/daily",
    },
    "videos-weekly": {
        "chart_type": "VIDEOS",
        "period": "WEEKLY",
        "section": "videos",
        "row_key": "videoViews",
        "kind": "video",
        "count": 100,
        "list_type": "TOP_VIEWS_CHART",
        "referer": f"{_ORIGIN}/charts/TopVideos/global/weekly",
    },
    "tracks-weekly": {
        "chart_type": "TRACKS",
        "period": "WEEKLY",
        "section": "trackTypes",
        "row_key": "trackViews",
        "kind": "track",
        "count": 100,
        "list_type": "TOP_VIEWS_CHART",
        "referer": f"{_ORIGIN}/charts/TopSongs/global/weekly",
    },
    "artists-weekly": {
        "chart_type": "ARTISTS",
        "period": "WEEKLY",
        "section": "artists",
        "row_key": "artistViews",
        "kind": "artist",
        "count": 100,
        "list_type": "TOP_VIEWS_CHART",
        "referer": f"{_ORIGIN}/charts/TopArtists/global/weekly",
    },
    "shorts-daily": {
        "chart_type": "SHORTS_TRACKS_BY_USAGE",
        "period": "DAILY",
        "section": "trackTypes",
        "row_key": "trackViews",
        "kind": "shorts",
        "count": 50,
        "list_type": "TOP_SHORTS_BY_USAGE",
        "referer": f"{_ORIGIN}/charts/TopShortsSongs/global/daily",
    },
    "shorts-weekly": {
        "chart_type": "SHORTS_TRACKS_BY_USAGE",
        "period": "WEEKLY",
        "section": "trackTypes",
        "row_key": "trackViews",
        "kind": "shorts",
        "count": 50,
        "list_type": "TOP_SHORTS_BY_USAGE",
        "referer": f"{_ORIGIN}/charts/TopShortsSongs/global/weekly",
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get("type", "videos-daily")
    selected = requested if requested in type_map else "videos-daily"
    list_data = await _get_list(selected, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict:
    spec = _BOARD_SPECS[board_type]
    bootstrap = await get(
        url=_BOOTSTRAP_URL,
        no_cache=no_cache,
        cache_key="youtube:charts:bootstrap",
        response_type="text",
        headers=_page_headers(),
    )
    context = _parse_bootstrap(bootstrap.data)
    if context is None:
        return {
            "from_cache": bootstrap.from_cache,
            "update_time": bootstrap.update_time,
            "data": [],
        }

    query = urlencode(
        {
            "perspective": "CHART_DETAILS",
            "chart_params_country_code": "global",
            "chart_params_chart_type": spec["chart_type"],
            "chart_params_period_type": spec["period"],
        }
    )
    result = await post(
        url=_API_URL,
        body={"context": context, "browseId": _BROWSE_ID, "query": query},
        no_cache=no_cache,
        cache_key=f"youtube:charts:{board_type}",
        headers=_api_headers(str(spec["referer"])),
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_chart(result.data, board_type),
    }


def _parse_bootstrap(payload: object) -> dict | None:
    if not isinstance(payload, str) or not payload.strip():
        return None
    marker = "ytcfg.set("
    candidates: list[dict] = []
    cursor = 0
    while True:
        marker_index = payload.find(marker, cursor)
        if marker_index < 0:
            break
        start = marker_index + len(marker)
        try:
            config, consumed = json.JSONDecoder().raw_decode(payload[start:])
        except (TypeError, json.JSONDecodeError):
            cursor = start
            continue
        cursor = start + max(consumed, 1)
        if not isinstance(config, dict):
            continue
        context = config.get("INNERTUBE_CONTEXT")
        client = context.get("client") if isinstance(context, dict) else None
        if (
            config.get("INNERTUBE_CLIENT_NAME") == _CLIENT_NAME
            and config.get("INNERTUBE_CLIENT_VERSION") == _CLIENT_VERSION
            and isinstance(client, dict)
            and client.get("clientName") == _CLIENT_NAME
            and client.get("clientVersion") == _CLIENT_VERSION
            and _clean_text(client.get("visitorData"))
        ):
            candidates.append(context)
    return candidates[0] if len(candidates) == 1 else None


def _parse_chart(payload: object, board_type: str) -> list[ListItem]:
    if not isinstance(payload, dict) or board_type not in _BOARD_SPECS:
        return []
    spec = _BOARD_SPECS[board_type]
    section_list = _nested(payload, "contents", "sectionListRenderer", "contents")
    if not isinstance(section_list, list) or len(section_list) != 1:
        return []
    renderer = _nested(section_list[0], "musicAnalyticsSectionRenderer", "content")
    if not isinstance(renderer, dict) or not _valid_request_metadata(renderer, spec):
        return []

    groups = renderer.get(str(spec["section"]))
    if not isinstance(groups, list) or len(groups) != 1:
        return []
    group = groups[0]
    if not isinstance(group, dict):
        return []
    period = f"CHART_PERIOD_TYPE_{spec['period']}"
    end_date = _clean_text(group.get("endDate"))
    if (
        group.get("listType") != spec["list_type"]
        or group.get("chartPeriodType") != period
        or _date_timestamp(end_date) is None
        or not _is_latest_period(renderer, spec, end_date)
    ):
        return []

    rows = group.get(str(spec["row_key"]))
    if not isinstance(rows, list) or len(rows) != spec["count"]:
        return []
    items: list[ListItem] = []
    seen_ids: set[str] = set()
    previous_hot: int | None = None
    for rank, row in enumerate(rows, 1):
        item = _chart_item(row, str(spec["kind"]), rank, end_date)
        if item is None or item.id in seen_ids:
            return []
        if item.hot is not None:
            if previous_hot is not None and item.hot > previous_hot:
                return []
            previous_hot = item.hot
        seen_ids.add(item.id)
        items.append(item)
    return items


def _valid_request_metadata(renderer: dict, spec: dict[str, object]) -> bool:
    request_params = _nested(renderer, "perspectiveMetadata", "requestParams")
    expected = {
        "perspective": "CHART_DETAILS",
        "chartParams": {
            "countryCode": "global",
            "chartType": f"CHART_TYPE_{spec['chart_type']}",
            "chartPeriodType": f"CHART_PERIOD_TYPE_{spec['period']}",
        },
    }
    return request_params == expected


def _is_latest_period(renderer: dict, spec: dict[str, object], end_date: str) -> bool:
    available = _nested(renderer, "perspectiveMetadata", "availableChartsInfo")
    if not isinstance(available, list) or not available:
        return False
    expected_type = f"CHART_TYPE_{spec['chart_type']}"
    expected_period = f"CHART_PERIOD_TYPE_{spec['period']}"
    identities: set[tuple[str, str]] = set()
    matching: list[dict] = []
    for row in available:
        if not isinstance(row, dict):
            return False
        identity = (_clean_text(row.get("chartType")), _clean_text(row.get("chartPeriodType")))
        earliest = _clean_text(row.get("earliestEndDate"))
        latest = _clean_text(row.get("latestEndDate"))
        if (
            not all(identity)
            or identity in identities
            or _date_timestamp(earliest) is None
            or _date_timestamp(latest) is None
            or earliest > latest
        ):
            return False
        identities.add(identity)
        if identity == (expected_type, expected_period):
            matching.append(row)
    return len(matching) == 1 and matching[0].get("latestEndDate") == end_date


def _chart_item(value: object, kind: str, rank: int, end_date: str) -> ListItem | None:
    if not isinstance(value, dict) or value.get("isVisible") is not True:
        return None
    rank_desc = _rank_description(value.get("chartEntryMetadata"), rank, end_date)
    if rank_desc is None:
        return None
    if kind == "artist":
        return _artist_item(value, rank_desc)
    if kind == "video":
        return _video_item(value, rank_desc)
    if kind in {"track", "shorts"}:
        return _track_item(value, rank_desc, shorts=kind == "shorts")
    return None


def _artist_item(value: dict, rank_desc: str) -> ListItem | None:
    artist_id = _clean_text(value.get("id"))
    name = _clean_text(value.get("name"))
    views = _positive_int(value.get("viewCount"))
    if not _ARTIST_ID_RE.fullmatch(artist_id) or not name or views is None:
        return None
    url = f"{_ORIGIN}/artist/{quote(artist_id, safe='')}"
    return ListItem(
        id=artist_id,
        title=name,
        hot=views,
        desc=rank_desc,
        url=url,
        mobileUrl=url,
    )


def _video_item(value: dict, rank_desc: str) -> ListItem | None:
    video_id = _clean_text(value.get("id"))
    title = _clean_text(value.get("title"))
    views = _positive_int(value.get("viewCount"))
    duration = _positive_int(value.get("videoDuration"))
    artists = _artist_names(value.get("artists"))
    timestamp = _release_timestamp(value.get("releaseDate"))
    cover = _thumbnail_url(value.get("thumbnail"), video_id=video_id)
    channel_id = _clean_text(value.get("externalChannelId"))
    channel_name = _clean_text(value.get("channelName"))
    if (
        not _VIDEO_ID_RE.fullmatch(video_id)
        or not title
        or views is None
        or duration is None
        or not artists
        or timestamp is None
        or cover is None
        or value.get("isAvailable") is not True
        or not channel_id.startswith("UC")
        or len(channel_id) != 24
        or not channel_name
    ):
        return None
    url = f"https://www.youtube.com/watch?v={video_id}"
    desc = f"{_duration_label(duration)} · {rank_desc}"
    return ListItem(
        id=video_id,
        title=title,
        author=" / ".join(artists),
        hot=views,
        cover=cover,
        desc=desc,
        timestamp=timestamp,
        url=url,
        mobileUrl=url,
    )


def _track_item(value: dict, rank_desc: str, *, shorts: bool) -> ListItem | None:
    song_id = _clean_text(value.get("id"))
    title = _clean_text(value.get("name"))
    video_id = _clean_text(value.get("encryptedVideoId"))
    artists = _artist_names(value.get("artists"))
    timestamp = _release_timestamp(value.get("releaseDate"))
    cover = _thumbnail_url(value.get("thumbnail"))
    views = None if shorts else _positive_int(value.get("viewCount"))
    if (
        not _SONG_ID_RE.fullmatch(song_id)
        or not title
        or not _VIDEO_ID_RE.fullmatch(video_id)
        or not artists
        or timestamp is None
        or cover is None
        or (not shorts and views is None)
    ):
        return None
    if shorts:
        url = f"https://www.youtube.com/source/{video_id}/shorts"
    else:
        url = f"https://www.youtube.com/watch?v={video_id}"
    return ListItem(
        id=song_id,
        title=title,
        author=" / ".join(artists),
        hot=views,
        cover=cover,
        desc=rank_desc,
        timestamp=timestamp,
        url=url,
        mobileUrl=url,
    )


def _rank_description(value: object, expected_rank: int, end_date: str) -> str | None:
    if not isinstance(value, dict) or value.get("currentPosition") != expected_rank:
        return None
    periods = _positive_int(value.get("periodsOnChart"))
    if periods is None:
        return None
    previous_value = value.get("previousPosition")
    percent = value.get("percentViewsChange")
    if previous_value is None:
        prior = "本期上榜"
    else:
        previous = _nonnegative_int(previous_value)
        if previous is None:
            return None
        prior = "本期上榜" if previous == 0 else f"上期第 {previous} 名"
    parts = [f"榜期 {end_date}", prior]
    if percent is not None:
        if (
            isinstance(percent, bool)
            or not isinstance(percent, (int, float))
            or not math.isfinite(float(percent))
        ):
            return None
        parts.append(f"变化 {float(percent) * 100:+.1f}%")
    parts.append(f"在榜 {periods} 期")
    return " · ".join(parts)


def _thumbnail_url(value: object, video_id: str | None = None) -> str | None:
    rows = value.get("thumbnails") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    candidates: list[tuple[int, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = _clean_text(row.get("url"))
        width = _positive_int(row.get("width"))
        height = _positive_int(row.get("height"))
        try:
            parsed = urlparse(url)
        except ValueError:
            continue
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"i.ytimg.com", "yt3.googleusercontent.com"}
            or width is None
            or height is None
        ):
            continue
        if video_id is not None and (
            parsed.hostname != "i.ytimg.com" or not parsed.path.startswith(f"/vi/{video_id}/")
        ):
            continue
        candidates.append((width * height, url))
    return max(candidates, default=(0, ""))[1] or None


def _artist_names(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        return []
    if any(not isinstance(row, dict) for row in value):
        return []
    names = [_clean_text(row.get("name")) for row in value if _clean_text(row.get("name"))]
    return names if names and len(names) == len(set(names)) else []


def _release_timestamp(value: object) -> int | None:
    if not isinstance(value, dict):
        return None
    year = _positive_int(value.get("year"))
    month = _positive_int(value.get("month"))
    day = _positive_int(value.get("day"))
    if year is None or month is None or day is None:
        return None
    try:
        return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)
    except ValueError:
        return None


def _date_timestamp(value: str) -> int | None:
    try:
        return int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())
    except (TypeError, ValueError):
        return None


def _duration_label(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _page_headers() -> dict[str, str]:
    return {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }


def _api_headers(referer: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": _ORIGIN,
        "Referer": referer,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "X-Youtube-Client-Name": _CLIENT_NAME_NUMBER,
        "X-Youtube-Client-Version": _CLIENT_VERSION,
    }


def _nested(value: object, *keys: str) -> object:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _positive_int(value: object) -> int | None:
    number = _nonnegative_int(value)
    return number if number is not None and number > 0 else None


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 and str(value).strip() == str(number) else None


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())

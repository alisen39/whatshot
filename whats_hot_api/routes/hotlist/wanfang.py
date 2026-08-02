from __future__ import annotations

import base64
import html
import re
from collections.abc import Iterator

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "wanfang"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "万方数据",
    "description": "万方数据编辑发布的科技前沿文章",
    "link": "https://www.wanfangdata.com.cn/article-list/science",
}

_API_URL = (
    "https://s.wanfangdata.com.cn/"
    "WwwService.IndexService/queryInformation"
)
_ARTICLE_URL = "https://www.wanfangdata.com.cn/article-detail/science/{item_id}"
_MAX_ITEMS = 10
_UUID_RE = re.compile(r"[0-9a-f]{32}")
_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
_TAG_RE = re.compile(r"<[^>]+>")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="科技前沿",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await post(
        url=_API_URL,
        body=_query_request(),
        no_cache=no_cache,
        response_type="base64",
        cache_key="wanfang:science:latest:10",
        headers={
            "Accept": "application/grpc-web+proto",
            "Content-Type": "application/grpc-web+proto",
            "Origin": "https://s.wanfangdata.com.cn",
            "Referer": "https://s.wanfangdata.com.cn/recommends/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "X-Grpc-Web": "1",
            "X-User-Agent": "grpc-web-javascript/0.1",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_response(result.data),
    }


def _query_request() -> bytes:
    # QueryRequest(informationtype="science", page=1, rows=10), preceded by
    # the five-byte gRPC-Web data-frame header.
    message = b"\x0a\x07science\x18\x01\x20\x0a"
    return b"\x00" + len(message).to_bytes(4, "big") + message


def _parse_response(encoded: object) -> list[ListItem]:
    if not isinstance(encoded, str):
        return []
    try:
        raw = base64.b64decode(encoded, validate=True)
        payload = _grpc_payload(raw)
        fields = list(_protobuf_fields(payload))
        row_payloads = [value for number, wire, value in fields if number == 1 and wire == 2]
        totals = [value for number, wire, value in fields if number == 2 and wire == 0]
        if len(totals) != 1 or totals[0] < len(row_payloads) or not row_payloads:
            return []

        data: list[ListItem] = []
        seen_ids: set[str] = set()
        seen_titles: set[str] = set()
        previous_timestamp: int | None = None
        for row_payload in row_payloads:
            values = _detail_values(row_payload)
            item_id = _text(values.get(1))
            item_type = _text(values.get(2))
            title = _clean_text(values.get(3))
            published_at = _text(values.get(12))
            timestamp = get_time(published_at) if _TIME_RE.fullmatch(published_at) else None
            title_key = _identity_text(title)
            if (
                not _UUID_RE.fullmatch(item_id)
                or item_type != "science"
                or not title_key
                or not timestamp
                or item_id in seen_ids
                or title_key in seen_titles
                or (previous_timestamp is not None and timestamp > previous_timestamp)
            ):
                return []
            seen_ids.add(item_id)
            seen_titles.add(title_key)
            previous_timestamp = timestamp
            url = _ARTICLE_URL.format(item_id=item_id)
            data.append(
                ListItem(
                    id=item_id,
                    title=title,
                    desc="万方数据科技前沿编辑文章",
                    timestamp=timestamp,
                    url=url,
                    mobileUrl=url,
                )
            )
        return data[:_MAX_ITEMS]
    except (ValueError, UnicodeDecodeError):
        return []


def _grpc_payload(raw: bytes) -> bytes:
    offset = 0
    data_frames: list[bytes] = []
    grpc_ok = False
    while offset < len(raw):
        if len(raw) - offset < 5:
            raise ValueError("truncated gRPC-Web frame")
        flags = raw[offset]
        length = int.from_bytes(raw[offset + 1 : offset + 5], "big")
        offset += 5
        end = offset + length
        if end > len(raw):
            raise ValueError("truncated gRPC-Web payload")
        frame = raw[offset:end]
        offset = end
        if flags == 0:
            data_frames.append(frame)
        elif flags & 0x80:
            trailers = frame.decode("ascii")
            grpc_ok = bool(re.search(r"(?:^|\r\n)grpc-status:\s*0(?:\r\n|$)", trailers))
        else:
            raise ValueError("unsupported gRPC-Web frame")
    if len(data_frames) != 1 or not grpc_ok:
        raise ValueError("invalid gRPC-Web response")
    return data_frames[0]


def _protobuf_fields(data: bytes) -> Iterator[tuple[int, int, bytes | int]]:
    offset = 0
    while offset < len(data):
        key, offset = _read_varint(data, offset)
        number, wire = key >> 3, key & 7
        if number <= 0:
            raise ValueError("invalid protobuf field")
        if wire == 0:
            value, offset = _read_varint(data, offset)
        elif wire == 2:
            length, offset = _read_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ValueError("truncated protobuf field")
            value = data[offset:end]
            offset = end
        else:
            raise ValueError("unsupported protobuf wire type")
        yield number, wire, value


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("truncated protobuf varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
    raise ValueError("oversized protobuf varint")


def _detail_values(payload: bytes | int) -> dict[int, bytes | int]:
    if not isinstance(payload, bytes):
        raise ValueError("invalid detail payload")
    values: dict[int, bytes | int] = {}
    for number, wire, value in _protobuf_fields(payload):
        if wire == 2 and number in {1, 2, 3, 12} and number in values:
            raise ValueError("duplicate detail field")
        values[number] = value
    return values


def _text(value: object) -> str:
    return value.decode("utf-8").strip() if isinstance(value, bytes) else ""


def _clean_text(value: object) -> str:
    return " ".join(html.unescape(_TAG_RE.sub(" ", _text(value))).split())


def _identity_text(value: object) -> str:
    return re.sub(r"[^\w]+", " ", str(value).casefold()).strip()

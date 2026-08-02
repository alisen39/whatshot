from __future__ import annotations

import base64

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import wanfang
from whats_hot_api.utils.http_client import RequestResult


ROWS = [
    (
        "709e8bbfbd054e6890fc1e2174a7ed30",
        "具身智能驱动手术机器人迈向自动化新纪元",
        "2026-06-08 17:18:35",
    ),
    (
        "266b3b59eecf4333adeafe699da9b55c",
        "摩擦纳米发电机技术：开启高熵能源收集新时代",
        "2026-06-08 17:18:23",
    ),
]


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/wanfang/hot",
        "query_string": b"",
        "headers": [],
    })


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _string_field(number: int, value: str) -> bytes:
    raw = value.encode()
    return _varint((number << 3) | 2) + _varint(len(raw)) + raw


def _row(item_id: str, title: str, published_at: str) -> bytes:
    return b"".join((
        _string_field(1, item_id),
        _string_field(2, "science"),
        _string_field(3, title),
        _string_field(12, published_at),
    ))


def _response(rows=ROWS, *, grpc_status: int = 0, total: int = 149) -> str:
    message = b"".join(
        _varint((1 << 3) | 2) + _varint(len(payload)) + payload
        for payload in (_row(*row) for row in rows)
    )
    message += _varint(2 << 3) + _varint(total)
    trailer = f"grpc-status: {grpc_status}\r\n".encode()
    framed = (
        b"\x00" + len(message).to_bytes(4, "big") + message
        + b"\x80" + len(trailer).to_bytes(4, "big") + trailer
    )
    return base64.b64encode(framed).decode()


@pytest.mark.asyncio
async def test_wanfang_fetches_official_science_editorial_list(monkeypatch):
    async def fake_post(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == wanfang._API_URL
        assert kwargs["body"] == wanfang._query_request()
        assert kwargs["response_type"] == "base64"
        assert kwargs["cache_key"] == "wanfang:science:latest:10"
        assert kwargs["headers"]["Content-Type"] == "application/grpc-web+proto"
        assert kwargs["headers"]["Origin"] == "https://s.wanfangdata.com.cn"
        return RequestResult(False, "2026-07-18T00:00:00+00:00", _response())

    monkeypatch.setattr(wanfang, "post", fake_post)
    route_data = await wanfang.handle_route(_request())

    assert route_data.type == "科技前沿"
    assert route_data.total == 2
    assert [item.id for item in route_data.data] == [row[0] for row in ROWS]
    assert route_data.data[0].title == ROWS[0][1]
    assert route_data.data[0].timestamp == 1780910315000
    assert route_data.data[0].url == (
        "https://www.wanfangdata.com.cn/article-detail/science/"
        "709e8bbfbd054e6890fc1e2174a7ed30"
    )
    assert route_data.data[0].mobileUrl == route_data.data[0].url


def test_wanfang_parser_rejects_duplicate_identity_or_reversed_time():
    duplicate = [ROWS[0], (ROWS[0][0], "另一标题", "2026-06-08 17:18:23")]
    reversed_time = [ROWS[1], ROWS[0]]

    assert wanfang._parse_response(_response(duplicate)) == []
    assert wanfang._parse_response(_response(reversed_time)) == []


def test_wanfang_parser_rejects_failed_or_malformed_grpc_web():
    assert wanfang._parse_response(_response(grpc_status=7)) == []
    assert wanfang._parse_response(base64.b64encode(b"truncated").decode()) == []
    assert wanfang._parse_response("not base64") == []

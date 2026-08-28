from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import ngabbs
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/ngabbs",
        "query_string": b"",
        "headers": [],
    })


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "tid": 44040507,
        "subject": "iOS升级18.4后请下载新版APP",
        "author": "zeg",
        "replies": 0,
        "postdate": 1746760563,
        "tpcurl": "/read.php?tid=44040507",
    }
    row.update(overrides)
    return row


def _incident_row() -> dict[str, object]:
    return _row(
        tid=47447060,
        subject=False,
        author="Prepyramid",
        replies=123,
        postdate=1787768690,
        tpcurl="/read.php?tid=47447060",
    )


def test_ngabbs_skips_invalid_rows_without_losing_valid_topics():
    rows = [
        _row(),
        _incident_row(),
        _row(tid=47447675, subject="Another topic", tpcurl="/read.php?tid=47447675"),
        _row(tid="not-a-number", subject="Bad id"),
        _row(tid=47447700, subject="Missing path", tpcurl="read.php?tid=47447700"),
        "not-an-object",
    ]

    items = ngabbs._parse_items({"code": 0, "result": [rows]})

    assert [item.id for item in items] == ["44040507", "47447675"]
    assert items[0].title == "iOS升级18.4后请下载新版APP"
    assert items[0].author == "zeg"
    assert items[0].hot == 0
    assert items[0].timestamp == 1746760563000
    assert items[0].url == "https://bbs.nga.cn/read.php?tid=44040507"
    assert items[0].mobileUrl == "https://bbs.nga.cn/read.php?tid=44040507"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"error": {"message": "upstream denied"}},
        {"result": "not-a-list"},
        {"result": []},
        {"result": [[]]},
    ],
)
def test_ngabbs_rejects_malformed_or_empty_payloads(payload: object):
    with pytest.raises(RuntimeError):
        ngabbs._parse_items(payload)


def test_ngabbs_rejects_payload_with_no_usable_topics():
    with pytest.raises(RuntimeError):
        ngabbs._parse_items({"code": 0, "result": [[_incident_row()]]})


@pytest.mark.asyncio
async def test_ngabbs_incident_payload_returns_remaining_valid_topics(monkeypatch):
    payload = {"code": 0, "result": [[_row(), _incident_row(), _row(tid=47447675, subject="Another topic", replies=57)]]}

    async def fake_post(*args, **kwargs):
        assert kwargs["no_cache"] is True
        return RequestResult(False, "2026-08-27T12:55:00+00:00", payload)

    monkeypatch.setattr(ngabbs, "post", fake_post)
    result = await ngabbs.handle_route(_request(), no_cache=True)

    assert result.type == "论坛热帖"
    assert result.total == 2
    assert [item.id for item in result.data] == ["44040507", "47447675"]
    assert result.updateTime == "2026-08-27T12:55:00+00:00"

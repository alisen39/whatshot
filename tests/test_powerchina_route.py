from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import powerchina
from whats_hot_api.utils.http_client import RequestResult


ROWS = [
    {
        "id": "2409487435",
        "systemId": "faa91a5c34bc441c91e72e6b5555df14",
        "systemType": "purchase",
        "title": "中国电建核电工程公司临建材料采购项目公开询比采购公告",
        "titleTypeName": "货物类",
        "announcementType": "招采公告",
        "companyType": "2",
        "publishTime": "2026-07-17 00:45:00",
        "source": "设备物资集中采购电子平台",
        "registrationDeadline": "2026-07-22",
        "submissionDeadline": "2026-07-23",
        "bidOpenTime": "2026-07-23 14:00:00",
        "projectNumber": "PC-2026-001",
        "readCount": 12,
        "author": "",
        "procuringEntity": "中国电建集团核电工程有限公司",
        "isShow": "1",
        "isDeleted": 0,
        "isPublic": 0,
        "bidType": 0,
        "publicUrl": "",
        "pictureUrl": "https://files.example/notice.pdf",
    }
]


def _request(query: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/powerchina/notice",
        "query_string": query,
        "headers": [],
    })


@pytest.mark.asyncio
async def test_powerchina_fetches_official_notice_board(monkeypatch):
    async def fake_post(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("BidAnnouncementSummary/list")
        assert kwargs["body"] == {
            "pageNum": 1,
            "pageSize": 50,
            "announcementType": "招采公告",
            "companyType": "3",
        }
        assert kwargs["cache_key"] == "powerchina:notice:latest:50"
        return RequestResult(
            False,
            "2026-07-17T00:50:00+00:00",
            {"code": 200, "rows": ROWS},
        )

    monkeypatch.setattr(powerchina, "post", fake_post)
    route_data = await powerchina.handle_route(_request())
    item = route_data.data[0]

    assert route_data.type == "招采公告"
    assert item.id == "2409487435"
    assert item.author == "中国电建集团核电工程有限公司"
    assert item.hot == 12
    assert item.timestamp == 1784220300000
    assert item.desc == (
        "类别：货物类"
        " · 来源：设备物资集中采购电子平台"
        " · 项目编号：PC-2026-001"
        " · 报名截止：2026-07-22"
        " · 提交截止：2026-07-23"
        " · 开标时间：2026-07-23 14:00:00"
    )

    parsed = urlparse(item.url)
    query = parse_qs(parsed.query)
    assert parsed.path == "/notice/detail"
    assert query["id"] == ["2409487435"]
    assert query["type"] == ["招采公告"]
    assert query["path"] == ["/consult/notice"]
    assert query["bidType"] == ["0"]
    assert item.mobileUrl == item.url


@pytest.mark.asyncio
async def test_powerchina_selects_publicity_board(monkeypatch):
    captured = {}

    async def fake_post(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        row = {
            **ROWS[0],
            "id": "2409487434",
            "title": "中国电建某项目成交结果公示",
            "announcementType": "中标/成交公示",
        }
        return RequestResult(
            False,
            "2026-07-17T00:50:00+00:00",
            {"code": 200, "rows": [row]},
        )

    monkeypatch.setattr(powerchina, "post", fake_post)
    route_data = await powerchina.handle_route(_request(b"type=result"))

    assert route_data.type == "中标/成交公示"
    assert captured["body"]["announcementType"] == "中标/成交公示"
    query = parse_qs(urlparse(route_data.data[0].url).query)
    assert query["path"] == ["/consult/publicity"]


def test_powerchina_parser_rejects_wrong_board_and_deduplicates_stable_ids():
    duplicate_id = dict(ROWS[0])
    duplicate_title = {
        **ROWS[0],
        "id": "2409487000",
    }
    wrong_board = {
        **ROWS[0],
        "id": "2409486999",
        "announcementType": "变更公告",
    }
    hidden = {
        **ROWS[0],
        "id": "2409486998",
        "title": "隐藏公告",
        "isShow": "0",
    }

    items = powerchina._parse_rows(
        {
            "code": 200,
            "rows": [ROWS[0], duplicate_id, duplicate_title, wrong_board, hidden],
        },
        "招采公告",
    )

    assert [item.id for item in items] == ["2409487435", "2409487000"]


def test_powerchina_public_external_notice_uses_upstream_url():
    row = {
        **ROWS[0],
        "isPublic": 1,
        "publicUrl": "https://example.gov.cn/public/notice-1",
    }
    item = powerchina._announcement_item(row, "招采公告")

    assert item is not None
    assert item.url == "https://example.gov.cn/public/notice-1"

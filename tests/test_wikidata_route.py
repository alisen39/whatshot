from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import wikidata
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_wikidata_status_updates_route(monkeypatch):
    current_year = datetime.now(timezone.utc).year
    calls = []

    async def fake_get(**kwargs):  # noqa: ANN003
        calls.append(kwargs)
        year = current_year if f"%2F{current_year}" in kwargs["url"] else current_year - 1
        rows = [
            {
                "pageid": year * 10 + 1,
                "ns": 4,
                "title": f"Wikidata:Status updates/{year} 01 08",
            },
            {
                "pageid": year * 10,
                "ns": 4,
                "title": f"Wikidata:Status updates/{year} 01 01",
            },
        ]
        return RequestResult(
            from_cache=year != current_year,
            update_time=f"{year}-07-18T00:00:00+00:00",
            data={"query": {"allpages": rows}},
        )

    monkeypatch.setattr(wikidata, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/wikidata", "query_string": b"", "headers": []}
    )
    route_data = await wikidata.handle_route(request)

    assert route_data.name == "wikidata"
    assert route_data.type == "官方周报"
    assert route_data.total == 4
    assert route_data.fromCache is False
    assert [item.id for item in route_data.data] == [
        str(current_year * 10 + 1),
        str(current_year * 10),
        str((current_year - 1) * 10 + 1),
        str((current_year - 1) * 10),
    ]
    assert route_data.data[0].title == f"Wikidata 周报 · {current_year}-01-08"
    assert route_data.data[0].url.endswith(f"/{current_year}_01_08")
    assert len(calls) == 2
    assert all(call["response_type"] == "json" for call in calls)
    assert {call["cache_key"] for call in calls} == {
        f"wikidata:status-updates:{current_year}:50",
        f"wikidata:status-updates:{current_year - 1}:50",
    }


def test_wikidata_parser_validates_identity_date_and_order():
    rows = [
        {"pageid": 30, "title": "Wikidata:Status updates/2026 07 13"},
        {"pageid": 20, "title": "Wikidata:Status updates/2026 07 06"},
        {"pageid": 10, "title": "Wikidata:Status updates/2026 06 29"},
        {"pageid": 30, "title": "Wikidata:Status updates/2026 06 22"},
        {"pageid": 9, "title": "Wikidata:Status updates/2026 07 06"},
        {"pageid": 8, "title": "Wikidata:Status updates/2027 01 01"},
        {"pageid": 7, "title": "Wikidata:Status updates/Next"},
        {"pageid": "6", "title": "Wikidata:Status updates/2026 06 15"},
    ]

    items = wikidata._parse_rows(rows, date(2026, 7, 18))

    assert [item.id for item in items] == ["30", "20", "10"]
    assert [item.timestamp for item in items] == sorted(
        (item.timestamp for item in items), reverse=True
    )
    assert len({item.url for item in items}) == 3


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"error": {}}, {"query": None}, {"query": {}}, {"query": {"allpages": {}}}],
)
def test_wikidata_response_rows_rejects_malformed_payload(payload):
    assert wikidata._response_rows(payload) == []

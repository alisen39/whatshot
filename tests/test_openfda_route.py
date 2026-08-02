from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import openfda
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/openfda",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_openfda_sorts_and_maps_recall_fields(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"] == {
            "sort": "report_date:desc",
            "limit": "100",
        }
        return RequestResult(
            False,
            "2026-07-17T00:00:00+00:00",
            {
                "results": [
                    {
                        "recall_number": "F-1000-2026",
                        "event_id": "90000",
                        "report_date": "20260701",
                        "recalling_firm": "Older Foods",
                        "product_description": "Older food product",
                        "reason_for_recall": "Older reason",
                        "classification": "Class II",
                        "status": "Completed",
                        "country": "United States",
                    },
                    {
                        "recall_number": "F-2000-2026",
                        "event_id": "90001",
                        "report_date": "20260708",
                        "recalling_firm": "Fresh Foods",
                        "product_description": "Ready-to-eat salad",
                        "reason_for_recall": "Potential Listeria contamination",
                        "classification": "Class I",
                        "status": "Ongoing",
                        "country": "United States",
                        "state": "CA",
                        "distribution_pattern": "Nationwide",
                        "product_quantity": "1,000 cases",
                        "recall_initiation_date": "20260630",
                        "voluntary_mandated": "Voluntary: Firm initiated",
                    },
                ],
            },
        )

    monkeypatch.setattr(openfda, "get", fake_get)
    route_data = await openfda.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.type == "食品召回"
    assert item.id == "F-2000-2026"
    assert item.title == "Fresh Foods · Ready-to-eat salad"
    assert item.content == (
        "Product: Ready-to-eat salad\n\n"
        "Reason: Potential Listeria contamination\n\n"
        "Distribution: Nationwide\n\n"
        "Quantity: 1,000 cases"
    )
    assert item.isImportant is True
    assert item.tags == ["Class I", "Ongoing", "United States", "CA"]
    assert item.metrics == {
        "recallNumber": "F-2000-2026",
        "eventId": "90001",
        "reportDate": "20260708",
        "initiationDate": "20260630",
        "voluntaryMandated": "Voluntary: Firm initiated",
    }
    assert item.timestamp == 1783440000000
    assert "recall_number%3A%22F-2000-2026%22" in item.url


def test_openfda_builds_stable_fallback_id_for_unclassified_record():
    row = {
        "recall_number": "N/A",
        "event_id": "99231",
        "product_description": "Blue Ribbon Classics French Vanilla",
    }

    assert openfda._item_id(row) == openfda._item_id(dict(row))
    assert openfda._item_id(row).startswith("event-99231-")
    assert "event_id%3A%2299231%22" in openfda._detail_url("N/A", "99231")

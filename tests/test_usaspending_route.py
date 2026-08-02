from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import usaspending
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_usaspending_uses_recent_transactions_not_award_start_dates(monkeypatch):
    async def fake_post(**kwargs):  # noqa: ANN003
        body = kwargs["body"]
        assert kwargs["url"].endswith("/search/spending_by_transaction/")
        assert "Action Date" in body["fields"]
        assert "Transaction Amount" in body["fields"]
        assert "Start Date" not in body["fields"]
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {"results": [{
            "Award ID": "693KA723F00002",
            "Recipient Name": "RAYTHEON COMPANY",
            "Action Date": "2026-07-07",
            "Transaction Amount": 104948620.0,
            "Transaction Description": "STARS delivery order modification.",
            "Awarding Agency": "Department of Transportation",
            "Awarding Sub Agency": "Federal Aviation Administration",
            "Award Type": "DELIVERY ORDER",
            "Mod": "P00026",
            "generated_internal_id": "CONT_AWD_693KA723F00002_6920_693KA721D00001_6920",
        }]})

    monkeypatch.setattr(usaspending, "post", fake_post)
    request = Request({"type": "http", "method": "GET", "path": "/usaspending", "query_string": b"", "headers": []})
    route_data = await usaspending.handle_route(request)
    item = route_data.data[0]
    assert route_data.kind == "newsflash"
    assert route_data.type == "国防相关合同交易"
    assert item.title == "RAYTHEON COMPANY · $104.95M"
    assert item.isImportant is True
    assert item.metrics["transactionAmount"] == 104948620.0
    assert item.metrics["actionDate"] == "2026-07-07"
    assert item.timestamp is not None
    assert item.url.startswith("https://www.usaspending.gov/award/CONT_AWD_")

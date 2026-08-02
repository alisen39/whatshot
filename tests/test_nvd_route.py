from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import nvd
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/nvd", "query_string": b"", "headers": []})


@pytest.mark.asyncio
async def test_nvd_fetches_last_page_and_filters_rejected_entries(monkeypatch):
    calls: list[dict] = []

    async def fake_get(**kwargs):  # noqa: ANN003
        calls.append(kwargs["params"])
        if kwargs["params"]["resultsPerPage"] == "1":
            return RequestResult(False, "2026-07-16T00:00:00+00:00", {"totalResults": 3757})
        return RequestResult(False, "2026-07-16T00:01:00+00:00", {"vulnerabilities": [
            {"cve": {"id": "CVE-2026-REJECTED", "vulnStatus": "Rejected", "published": "2026-07-15T17:16:54Z", "descriptions": [{"lang": "en", "value": "Rejected entry."}]}},
            {"cve": {
                "id": "CVE-2026-62378", "vulnStatus": "Received",
                "published": "2026-07-15T17:16:53Z", "lastModified": "2026-07-15T17:20:00Z",
                "descriptions": [{"lang": "zh", "value": "中文描述"}, {"lang": "en", "value": "A remote attacker can execute arbitrary code."}],
                "metrics": {"cvssMetricV31": [{"cvssData": {"baseSeverity": "CRITICAL", "baseScore": 9.8}}]},
                "weaknesses": [{"description": [{"lang": "en", "value": "CWE-78"}]}],
            }},
        ]})

    monkeypatch.setattr(nvd, "get", fake_get)
    route_data = await nvd.handle_route(_request())
    item = route_data.data[0]
    assert calls[0]["resultsPerPage"] == "1"
    assert calls[1]["resultsPerPage"] == "100"
    assert calls[1]["startIndex"] == "3657"
    assert route_data.kind == "newsflash"
    assert route_data.total == 1
    assert item.id == "CVE-2026-62378"
    assert item.title == "CVE-2026-62378 · CRITICAL 9.8"
    assert item.content == "A remote attacker can execute arbitrary code."
    assert item.isImportant is True
    assert item.tags == ["CRITICAL", "Received", "CWE-78"]
    assert item.metrics["score"] == 9.8
    assert item.timestamp == 1784135813000

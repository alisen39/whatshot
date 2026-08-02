from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import cisa_kev
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/cisa-kev",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_cisa_kev_sorts_and_maps_actionable_fields(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "catalogVersion": "2026.07.15",
                "vulnerabilities": [
                    {
                        "cveID": "CVE-2026-10000",
                        "vendorProject": "Vendor A",
                        "product": "Product A",
                        "vulnerabilityName": "Older Vulnerability",
                        "dateAdded": "2026-07-14",
                        "shortDescription": "Older description.",
                        "requiredAction": "Apply the update.",
                        "dueDate": "2026-07-28",
                        "knownRansomwareCampaignUse": "Unknown",
                        "cwes": ["CWE-20"],
                    },
                    {
                        "cveID": "CVE-2026-20000",
                        "vendorProject": "Vendor B",
                        "product": "Product B",
                        "vulnerabilityName": "Newer Vulnerability",
                        "dateAdded": "2026-07-15",
                        "shortDescription": "Newer description.",
                        "requiredAction": "Apply mitigations immediately.",
                        "dueDate": "2026-07-18",
                        "knownRansomwareCampaignUse": "Known",
                        "cwes": ["CWE-78"],
                    },
                ],
            },
        )

    monkeypatch.setattr(cisa_kev, "get", fake_get)
    route_data = await cisa_kev.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.type == "已知被利用漏洞"
    assert item.id == "CVE-2026-20000"
    assert item.title.startswith("CVE-2026-20000 · ")
    assert item.content == "Newer description.\n\nApply mitigations immediately."
    assert item.contentStatus == "full"
    assert item.isImportant is True
    assert item.tags == ["Vendor B", "Product B", "CWE-78"]
    assert item.metrics == {
        "dateAdded": "2026-07-15",
        "dueDate": "2026-07-18",
        "ransomwareUse": "Known",
    }
    assert item.timestamp == 1784044800000
    assert item.url == "https://nvd.nist.gov/vuln/detail/CVE-2026-20000"

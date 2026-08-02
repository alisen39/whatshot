from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import osv
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/osv",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_osv_parses_latest_vulnerability_table(monkeypatch):
    html = """
    <div class="vuln-table-rows">
      <div class="vuln-table-row">
        <span><a href="/vulnerability/UBUNTU-CVE-2026-11386">UBUNTU-CVE-2026-11386</a></span>
        <span class="vuln-packages"><ul>
          <li>Ubuntu:24.04:LTS/ubuntu-advantage-tools</li>
          <li>Ubuntu:26.04:LTS/ubuntu-advantage-tools</li>
        </ul></span>
        <span class="vuln-summary">See record for full details</span>
        <span><relative-time datetime="2026-07-17 14:00:00+00:00">17 Jul</relative-time></span>
        <span class="vuln-attributes"><span class="tag">Fix available</span>
          <span class="tag">Severity - 9.0 (Critical)</span></span>
      </div>
      <div class="vuln-table-row">
        <span><a href="/vulnerability/MAL-2026-10700">MAL-2026-10700</a></span>
        <span class="vuln-packages"><ul><li>npm/time-format-kit</li></ul></span>
        <span class="vuln-summary">Malicious code in time-format-kit (npm)</span>
        <span><relative-time datetime="2026-07-16 14:26:20+00:00">2 hours ago</relative-time></span>
        <span class="vuln-attributes"><span class="tag">No fix available</span></span>
      </div>
    </div>
    """

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://osv.dev/list"
        assert kwargs["response_type"] == "text"
        return RequestResult(False, "2026-07-17T16:00:00+00:00", html)

    monkeypatch.setattr(osv, "get", fake_get)
    route_data = await osv.handle_route(_request())

    assert route_data.kind == "newsflash"
    assert route_data.type == "最新漏洞"
    assert route_data.total == 2

    critical = route_data.data[0]
    assert critical.id == "UBUNTU-CVE-2026-11386"
    assert critical.title.endswith("Ubuntu:24.04:LTS/ubuntu-advantage-tools")
    assert critical.summary is None
    assert critical.contentStatus == "summary"
    assert critical.isImportant is True
    assert critical.tags == ["Fix available", "Severity - 9.0 (Critical)"]
    assert critical.metrics == {
        "published": "2026-07-17 14:00:00+00:00",
        "packages": [
            "Ubuntu:24.04:LTS/ubuntu-advantage-tools",
            "Ubuntu:26.04:LTS/ubuntu-advantage-tools",
        ],
        "severity": "Critical",
        "score": 9.0,
    }
    assert critical.timestamp == 1784296800000
    assert critical.url == "https://osv.dev/vulnerability/UBUNTU-CVE-2026-11386"

    malicious = route_data.data[1]
    assert malicious.title == "MAL-2026-10700 · Malicious code in time-format-kit (npm)"
    assert malicious.summary == "Malicious code in time-format-kit (npm)"
    assert malicious.metrics["packages"] == ["npm/time-format-kit"]

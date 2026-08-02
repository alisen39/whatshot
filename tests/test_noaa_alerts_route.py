from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import noaa_alerts
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/noaa-alerts", "query_string": b"", "headers": []})


@pytest.mark.asyncio
async def test_noaa_alerts_maps_severe_geojson_without_obsolete_limit(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"] == {"status": "actual", "severity": "Extreme,Severe"}
        assert "limit" not in kwargs["params"]
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {"features": [{
            "id": "https://api.weather.gov/alerts/alert-1",
            "geometry": {"type": "Polygon", "coordinates": [[[-99.25, 29.4], [-99.23, 29.3], [-99.33, 29.3], [-99.32, 29.4]]]},
            "properties": {
                "@id": "https://api.weather.gov/alerts/alert-1", "id": "alert-1", "category": "Met",
                "event": "Flash Flood Warning", "severity": "Extreme", "urgency": "Immediate", "certainty": "Observed",
                "headline": "Flash Flood Emergency", "areaDesc": "Medina, TX",
                "description": "Life-threatening flash flooding is occurring.", "instruction": "Move to higher ground now.",
                "senderName": "NWS Austin/San Antonio TX", "sent": "2026-07-15T12:42:00-05:00",
                "effective": "2026-07-15T12:42:00-05:00", "expires": "2026-07-15T20:30:00-05:00",
            },
        }, {
            "id": "https://api.weather.gov/alerts/safety-1",
            "geometry": None,
            "properties": {
                "@id": "https://api.weather.gov/alerts/safety-1", "id": "safety-1", "category": "Safety",
                "event": "Law Enforcement Warning", "severity": "Extreme", "headline": "Armed and dangerous subject",
            },
        }]})

    monkeypatch.setattr(noaa_alerts, "get", fake_get)
    route_data = await noaa_alerts.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.type == "严重气象告警"
    assert route_data.total == 1
    assert item.id == "alert-1"
    assert item.isImportant is True
    assert item.content == "Life-threatening flash flooding is occurring.\n\nSafety instructions:\nMove to higher ground now."
    assert item.source == "NWS Austin/San Antonio TX"
    assert item.tags == ["Flash Flood Warning", "Extreme", "Immediate", "Observed"]
    assert item.metrics["area"] == "Medina, TX"
    assert item.metrics["latitude"] == 29.35
    assert item.metrics["longitude"] == -99.282
    assert item.timestamp == 1784137320000
    assert item.url == "https://api.weather.gov/alerts/alert-1"

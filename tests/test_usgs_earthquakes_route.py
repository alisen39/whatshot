from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import usgs_earthquakes
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_usgs_earthquakes_maps_global_event_metadata(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"]["minmagnitude"] == "2.5"
        assert kwargs["params"]["starttime"].endswith(":00:00Z")
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {"features": [{
            "id": "us7000test",
            "geometry": {"type": "Point", "coordinates": [-19.0, -59.97, 10.0]},
            "properties": {
                "mag": 6.1, "place": "east of the South Sandwich Islands", "time": 1784136697000,
                "updated": 1784137000000, "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000test",
                "tsunami": 1, "sig": 590, "felt": 3, "alert": "green", "status": "reviewed", "magType": "mww",
            },
        }]})

    monkeypatch.setattr(usgs_earthquakes, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/usgs-earthquakes", "query_string": b"", "headers": []})
    route_data = await usgs_earthquakes.handle_route(request)
    item = route_data.data[0]
    assert route_data.kind == "newsflash"
    assert route_data.type == "全球地震"
    assert item.title == "M6.1 · east of the South Sandwich Islands"
    assert item.isImportant is True
    assert item.tags == ["M6+", "green", "reviewed"]
    assert item.metrics["depthKm"] == 10.0
    assert item.metrics["tsunami"] is True
    assert item.timestamp == 1784136697000
    assert item.url.endswith("/eventpage/us7000test")

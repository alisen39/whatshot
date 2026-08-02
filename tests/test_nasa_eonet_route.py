from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import nasa_eonet
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/nasa-eonet", "query_string": b"", "headers": []})


@pytest.mark.asyncio
async def test_nasa_eonet_uses_latest_point_geometry_and_filters_polygons(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"] == {"status": "open", "limit": "60"}
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {"events": [
            {
                "id": "EONET_1", "title": "Wildfire Example", "description": "4 miles from Example City",
                "link": "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_1",
                "categories": [{"id": "wildfires", "title": "Wildfires"}],
                "sources": [{"id": "IRWIN", "url": "https://example.com/fire"}],
                "geometry": [
                    {"date": "2026-07-14T00:00:00Z", "type": "Point", "coordinates": [-115.0, 40.0]},
                    {"date": "2026-07-15T12:00:00Z", "type": "Point", "coordinates": [-114.2, 41.5], "magnitudeValue": 1326, "magnitudeUnit": "acres"},
                ],
            },
            {
                "id": "EONET_2", "title": "Storm Example", "categories": [{"title": "Severe Storms"}],
                "sources": [{"id": "JTWC"}],
                "geometry": [{"date": "2026-07-15T13:00:00Z", "type": "Point", "coordinates": [120.0, 15.0], "magnitudeValue": 40, "magnitudeUnit": "kts"}],
            },
            {
                "id": "EONET_3", "title": "Polygon Event", "categories": [{"title": "Floods"}],
                "geometry": [{"date": "2026-07-15T14:00:00Z", "type": "Polygon", "coordinates": [[[1, 2], [3, 4]]]}],
            },
        ]})

    monkeypatch.setattr(nasa_eonet, "get", fake_get)
    route_data = await nasa_eonet.handle_route(_request())
    storm, wildfire = route_data.data
    assert route_data.kind == "newsflash"
    assert route_data.total == 2
    assert storm.id == "EONET_2"
    assert wildfire.id == "EONET_1"
    assert wildfire.content == "4 miles from Example City"
    assert wildfire.source == "IRWIN"
    assert wildfire.tags == ["Wildfires"]
    assert wildfire.metrics["latitude"] == 41.5
    assert wildfire.metrics["longitude"] == -114.2
    assert wildfire.metrics["magnitude"] == 1326
    assert wildfire.timestamp == 1784116800000
    assert wildfire.url == "https://example.com/fire"

from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import launch_library
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/launch-library", "query_string": b"", "headers": []})


@pytest.mark.asyncio
async def test_launch_library_maps_and_sorts_upcoming_launches(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/launches/upcoming/")
        assert kwargs["params"] == {"limit": "10"}
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {"results": [
            {
                "id": "later", "name": "Rocket B | Mission B", "net": "2099-07-18T06:00:00Z",
                "url": "https://ll.thespacedevs.com/2.3.0/launches/later/",
                "status": {"name": "To Be Confirmed"},
                "launch_service_provider": {"name": "Provider B"},
                "mission": {"name": "Mission B", "type": "Test Flight", "description": "Mission details", "orbit": {"name": "Low Earth Orbit"}},
                "pad": {"name": "Pad B", "latitude": 13.7, "longitude": 80.2, "country": {"name": "India"}},
                "image": {"image_url": "https://example.com/launch.jpg"},
                "window_start": "2099-07-18T06:00:00Z", "window_end": "2099-07-18T07:00:00Z",
            },
            {
                "id": "sooner", "name": "Rocket A | Mission A", "net": "2099-07-17T11:50:00Z",
                "url": "https://ll.thespacedevs.com/2.3.0/launches/sooner/",
                "status": {"name": "Go for Launch"},
                "launch_service_provider": {"name": "Provider A"},
                "mission": None, "pad": None,
            },
            {
                "id": "past", "name": "Past", "net": "2020-01-01T00:00:00Z",
                "url": "https://ll.thespacedevs.com/2.3.0/launches/past/",
            },
        ]})

    monkeypatch.setattr(launch_library, "get", fake_get)
    route_data = await launch_library.handle_route(_request())

    assert route_data.kind == "newsflash"
    assert route_data.type == "未来发射任务"
    assert [item.id for item in route_data.data] == ["sooner", "later"]
    item = route_data.data[1]
    assert item.content == "Mission details"
    assert item.source == "Provider B"
    assert item.tags == ["To Be Confirmed", "Test Flight", "Low Earth Orbit", "India"]
    assert item.images == ["https://example.com/launch.jpg"]
    assert item.metrics["pad"] == "Pad B"
    assert item.metrics["latitude"] == 13.7
    assert item.timestamp == 4088037600000
    assert item.url.endswith("/launches/later/")

from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import celestrak
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_celestrak_sorts_by_launch_designator_not_element_epoch(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"] == {"GROUP": "last-30-days", "FORMAT": "json"}
        return RequestResult(False, "2026-07-16T00:00:00+00:00", [
            {"OBJECT_NAME": "OLDER LAUNCH UPDATED LATER", "OBJECT_ID": "2026-140N", "NORAD_CAT_ID": 69604, "EPOCH": "2026-07-15T05:21:41.631264", "CLASSIFICATION_TYPE": "U", "INCLINATION": 51.8781, "ECCENTRICITY": 0.0005551, "MEAN_MOTION": 15.36},
            {"OBJECT_NAME": "NEWER LAUNCH", "OBJECT_ID": "2026-153U", "NORAD_CAT_ID": 69818, "EPOCH": "2026-07-15T04:10:37.106112", "CLASSIFICATION_TYPE": "U", "INCLINATION": 88.9922, "ECCENTRICITY": 0.0007999, "MEAN_MOTION": 14.26},
        ])

    monkeypatch.setattr(celestrak, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/celestrak", "query_string": b"", "headers": []})
    route_data = await celestrak.handle_route(request)
    assert [item.id for item in route_data.data] == ["69818", "69604"]
    item = route_data.data[0]
    assert route_data.kind == "newsflash"
    assert route_data.type == "近30日新增空间物体"
    assert item.title == "NEWER LAUNCH"
    assert item.tags == ["Unclassified", "2026"]
    assert item.metrics["internationalDesignator"] == "2026-153U"
    assert item.metrics["noradCatalogId"] == 69818
    assert item.url.endswith("CATNR=69818")

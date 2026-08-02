from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import hdx
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/hdx", "query_string": b"", "headers": []})


@pytest.mark.asyncio
async def test_hdx_filters_archived_and_maps_dataset_metadata(monkeypatch):
    long_notes = "Humanitarian assessment details. " * 60

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"]["fq"] == "archived:false"
        assert kwargs["params"]["sort"] == "metadata_modified desc"
        return RequestResult(False, "2026-07-16T00:00:00+00:00", {"result": {"results": [
            {"id": "archived", "name": "archived-dataset", "title": "Archived", "archived": True},
            {
                "id": "dataset-1", "name": "afghanistan-assessment", "title": "Afghanistan - Rapid Household Assessment",
                "archived": False, "dataset_source": "UNHCR", "notes": long_notes,
                "metadata_created": "2023-01-01T00:00:00Z", "metadata_modified": "2026-07-15T17:10:32Z",
                "num_resources": 4,
                "groups": [{"name": "afg", "display_name": "Afghanistan"}],
                "tags": [{"name": "needs-assessment", "display_name": "Needs Assessment"}],
            },
        ]}})

    monkeypatch.setattr(hdx, "get", fake_get)
    route_data = await hdx.handle_route(_request())
    item = route_data.data[0]
    assert route_data.kind == "newsflash"
    assert route_data.total == 1
    assert item.id == "dataset-1"
    assert item.content.endswith("…")
    assert item.contentStatus == "truncated"
    assert item.source == "UNHCR"
    assert item.tags == ["Afghanistan", "Needs Assessment"]
    assert item.metrics["resourceCount"] == 4
    assert item.timestamp == 1784135432000
    assert item.url == "https://data.humdata.org/dataset/afghanistan-assessment"

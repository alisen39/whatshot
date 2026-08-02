from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.newsflash import who_outbreaks
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_who_outbreaks_requests_server_sorted_latest_items(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/api/news/diseaseoutbreaknews")
        assert kwargs["params"] == {
            "$orderby": "PublicationDate desc",
            "$top": "50",
        }
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "value": [
                    {
                        "Title": "Older outbreak",
                        "PublicationDate": "2026-07-02T18:27:48Z",
                        "DonId": "2026-DON611",
                        "ItemDefaultUrl": "/2026-DON611",
                        "Summary": "<p>Older summary.</p>",
                    },
                    {
                        "Title": "Latest outbreak",
                        "PublicationDate": "2026-07-03T15:31:57Z",
                        "DonId": "2026-DON612",
                        "ItemDefaultUrl": "/2026-DON612",
                        "Summary": "<p>Latest <strong>summary</strong>.</p>",
                        "LastModified": "2026-07-03T16:00:00Z",
                    },
                ]
            },
        )

    monkeypatch.setattr(who_outbreaks, "get", fake_get)
    request = Request(
        {"type": "http", "method": "GET", "path": "/who-outbreaks", "query_string": b"", "headers": []}
    )
    route_data = await who_outbreaks.handle_route(request)

    assert route_data.kind == "newsflash"
    assert route_data.type == "最新通报"
    assert [item.id for item in route_data.data] == ["2026-DON612", "2026-DON611"]
    latest = route_data.data[0]
    assert latest.content == "Latest summary."
    assert latest.timestamp == 1783092717000
    assert latest.url == (
        "https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON612"
    )


def test_who_outbreaks_normalizes_item_urls():
    assert who_outbreaks._detail_url("/item/2026-DON612", "2026-DON612") == (
        "https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON612"
    )
    assert who_outbreaks._detail_url(None, "2026-DON612") == (
        "https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON612"
    )

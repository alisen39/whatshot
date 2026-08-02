from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import openalex
from whats_hot_api.utils.http_client import RequestResult


WORK_ROWS = [
    {
        "id": "https://openalex.org/W7168353611",
        "doi": "https://doi.org/10.1017/jfm.2026.10123",
        "display_name": "An experimental study on <i>heat transport</i>",
        "publication_date": "2026-07-16",
        "cited_by_count": 7,
        "type": "article",
        "language": "en",
        "authorships": [
            {"author": {"display_name": "Ada Lovelace"}},
            {"author": {"display_name": "Grace Hopper"}},
            {"author": {"display_name": "Edsger Dijkstra"}},
            {"author": {"display_name": "Donald Knuth"}},
        ],
        "primary_location": {
            "source": {
                "display_name": "Journal of Fluid Mechanics",
                "type": "journal",
            }
        },
        "open_access": {"is_oa": True},
        "primary_topic": {"display_name": "Porous Media Convection"},
    }
]


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/openalex/default",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_openalex_fetches_latest_quality_filtered_journal_articles(monkeypatch):
    monkeypatch.setattr(openalex, "_utc_today", lambda: "2026-07-17")

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://api.openalex.org/works"
        assert kwargs["params"] == {
            "filter": (
                "to_publication_date:2026-07-17,"
                "type:article,"
                "primary_location.source.type:journal,"
                "has_doi:true,"
                "has_abstract:true,"
                "is_retracted:false,"
                "is_paratext:false"
            ),
            "sort": "publication_date:desc,cited_by_count:desc,display_name:asc",
            "per_page": "50",
            "select": openalex._SELECT_FIELDS,
        }
        return RequestResult(
            False,
            "2026-07-17T00:00:00+00:00",
            {"results": WORK_ROWS},
        )

    monkeypatch.setattr(openalex, "get", fake_get)
    route_data = await openalex.handle_route(_request())
    item = route_data.data[0]

    assert route_data.type == "最新期刊论文"
    assert item.id == "W7168353611"
    assert item.title == "An experimental study on heat transport"
    assert item.author == "Ada Lovelace, Grace Hopper, Edsger Dijkstra et al."
    assert item.hot == 7
    assert item.timestamp == 1784131200000
    assert item.url == "https://doi.org/10.1017/jfm.2026.10123"
    assert item.mobileUrl == item.url
    assert item.desc == (
        "期刊：Journal of Fluid Mechanics"
        " · 主题：Porous Media Convection"
        " · 语言：en"
        " · OpenAlex ID：W7168353611"
        " · DOI：10.1017/jfm.2026.10123"
        " · 开放获取"
    )


def test_openalex_parser_deduplicates_by_work_doi_and_title():
    duplicate_id = dict(WORK_ROWS[0])
    duplicate_doi = {**WORK_ROWS[0], "id": "https://openalex.org/W2"}
    duplicate_title = {
        **WORK_ROWS[0],
        "id": "https://openalex.org/W3",
        "doi": "https://doi.org/10.1000/different",
    }
    unique = {
        **WORK_ROWS[0],
        "id": "https://openalex.org/W4",
        "doi": "https://doi.org/10.1000/unique",
        "display_name": "A different article",
    }

    items = openalex._parse_works(
        {"results": [WORK_ROWS[0], duplicate_id, duplicate_doi, duplicate_title, unique]}
    )

    assert [item.id for item in items] == ["W7168353611", "W4"]


def test_openalex_parser_skips_rows_without_stable_identity():
    items = openalex._parse_works({
        "results": [
            {"id": "https://openalex.org/W1", "display_name": "No DOI"},
            {"id": "not-a-work", "doi": "10.1000/a", "display_name": "Bad ID"},
            {"id": "https://openalex.org/W2", "doi": "10.1000/b", "display_name": ""},
        ]
    })

    assert items == []

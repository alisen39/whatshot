from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import pubmed
from whats_hot_api.utils.http_client import RequestResult


TRENDING_HTML = """
<div class="search-results-chunk" data-results-amount="1,000">
  <article class="full-docsum">
    <span class="docsum-pmid">35465561</span>
  </article>
  <article class="full-docsum">
    <span class="docsum-pmid">42417444</span>
  </article>
</div>
"""

SUMMARY = {
    "result": {
        "uids": ["35465561", "42417444"],
        "35465561": {
            "uid": "35465561",
            "title": "Animal Crossing and COVID-19.",
            "sortpubdate": "2022/04/01 00:00",
            "fulljournalname": "Frontiers in psychology",
            "authors": [
                {"name": "Yee AZH"},
                {"name": "Sng JRH"},
            ],
            "lang": ["eng"],
            "pubtype": ["Journal Article"],
            "articleids": [
                {"idtype": "doi", "value": "10.3389/fpsyg.2022.800683"},
                {"idtype": "pmc", "value": "PMC9022176"},
            ],
        },
        "42417444": {
            "uid": "42417444",
            "title": "Global cancer statistics 2024.",
            "sortpubdate": "2026/07/01 00:00",
            "fulljournalname": "CA: a cancer journal for clinicians",
            "authors": [
                {"name": "Sung H"},
                {"name": "Filho AM"},
                {"name": "Laversanne M"},
                {"name": "Ferlay J"},
            ],
            "lang": ["eng"],
            "pubtype": ["Journal Article", "Review"],
            "articleids": [
                {"idtype": "doi", "value": "10.3322/caac.70090"},
            ],
        },
    }
}


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/pubmed/default",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_pubmed_fetches_trending_order_and_enriches_pmids(monkeypatch):
    calls = []

    async def fake_get(**kwargs):  # noqa: ANN003
        calls.append(kwargs)
        if kwargs["url"] == pubmed._TRENDING_URL:
            assert kwargs["params"] == {"size": "50"}
            return RequestResult(
                False,
                "2026-07-17T00:00:00+00:00",
                TRENDING_HTML,
            )
        assert kwargs["url"] == pubmed._ESUMMARY_URL
        assert kwargs["params"] == {
            "db": "pubmed",
            "retmode": "json",
            "id": "35465561,42417444",
            "tool": "whats_hot",
        }
        assert kwargs["cache_key"] == pubmed._summary_cache_key(
            ["35465561", "42417444"]
        )
        return RequestResult(
            False,
            "2026-07-17T00:00:01+00:00",
            SUMMARY,
        )

    monkeypatch.setattr(pubmed, "get", fake_get)
    route_data = await pubmed.handle_route(_request())

    assert len(calls) == 2
    assert route_data.type == "趋势论文"
    assert route_data.updateTime == "2026-07-17T00:00:01+00:00"
    assert [item.id for item in route_data.data] == ["35465561", "42417444"]

    first = route_data.data[0]
    assert first.author == "Yee AZH, Sng JRH"
    assert first.timestamp == 1648742400000
    assert first.url == "https://pubmed.ncbi.nlm.nih.gov/35465561/"
    assert first.desc == (
        "趋势排名：1"
        " · 期刊：Frontiers in psychology"
        " · 类型：Journal Article"
        " · 语言：eng"
        " · PMID：35465561"
        " · DOI：10.3389/fpsyg.2022.800683"
        " · PMC：PMC9022176"
    )
    assert route_data.data[1].author == "Sung H, Filho AM, Laversanne M et al."
    assert "类型：Review" in route_data.data[1].desc


def test_pubmed_trending_parser_keeps_unique_numeric_pmids_in_order():
    html = TRENDING_HTML.replace(
        "</div>",
        """
        <article class="full-docsum"><span class="docsum-pmid">35465561</span></article>
        <article class="full-docsum"><span class="docsum-pmid">PMID-bad</span></article>
        </div>
        """,
    )

    assert pubmed._parse_trending_pmids(html) == ["35465561", "42417444"]


def test_pubmed_summary_parser_requires_every_ranked_pmid():
    incomplete = {"result": {"35465561": SUMMARY["result"]["35465561"]}}

    with pytest.raises(ValueError, match="42417444"):
        pubmed._parse_summaries(["35465561", "42417444"], incomplete)


def test_pubmed_summary_item_rejects_identity_mismatch():
    row = {**SUMMARY["result"]["35465561"], "uid": "999"}

    assert pubmed._summary_item(row, "35465561", 1) is None

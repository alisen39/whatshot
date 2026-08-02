from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import openreview
from whats_hot_api.utils.http_client import RequestResult


NOTE = {
    "id": "qq4yipldw2",
    "pdate": 1784210978384,
    "cdate": 1772831462463,
    "mdate": 1784210978452,
    "tmdate": 1784210978452,
    "invitations": [
        "TMLR/-/Submission",
        "TMLR/-/Edit",
        "TMLR/-/Accepted",
    ],
    "readers": ["everyone"],
    "content": {
        "venue": {"value": "Accepted by TMLR"},
        "venueid": {"value": "TMLR"},
        "title": {
            "value": (
                "Sin&lt;GLU&gt;: Sinusoidal Gated Linear Units "
                "Improve Classification Accuracy"
            )
        },
        "authors": {"value": ["Luke Byrne", "Paul Murray"]},
        "authorids": {"value": ["~Luke_Byrne1", "~Paul_Murray1"]},
        "abstract": {
            "value": "A controlled study of sinusoidal gated linear units."
        },
        "submission_length": {
            "value": "Long submission (more than 12 pages of main content)"
        },
        "code": {
            "value": "https://github.com/example/singlu"
        },
        "pdf": {
            "value": "/pdf/bfa35d6618ff12ffa4a57b38ad581012f5444a5d.pdf"
        },
    },
}


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/openreview/hot",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_openreview_fetches_public_tmlr_acceptances(monkeypatch):
    async def fake_post(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://api2.openreview.net/notes/search"
        assert kwargs["body"] == {
            "content": {
                "venue": {
                    "terms": ["Accepted by TMLR"],
                    "matchMethod": "match",
                }
            },
            "venueid": "TMLR",
            "source": "forum",
            "sort": "tmdate:desc",
            "limit": 100,
        }
        assert kwargs["cache_key"] == "openreview:tmlr:accepted:tmdate-desc:100"
        return RequestResult(
            False,
            "2026-07-17T00:00:00+00:00",
            {"count": 4298, "notes": [NOTE]},
        )

    monkeypatch.setattr(openreview, "post", fake_post)
    route_data = await openreview.handle_route(_request())
    item = route_data.data[0]

    assert route_data.type == "TMLR 最新接收"
    assert item.id == "qq4yipldw2"
    assert item.title == (
        "Sin<GLU>: Sinusoidal Gated Linear Units Improve Classification Accuracy"
    )
    assert item.author == "Luke Byrne, Paul Murray"
    assert item.timestamp == 1784210978384
    assert item.url == "https://openreview.net/forum?id=qq4yipldw2"
    assert item.mobileUrl == item.url
    assert item.hot is None
    assert "期刊：Transactions on Machine Learning Research" in item.desc
    assert "摘要：A controlled study" in item.desc
    assert "代码：https://github.com/example/singlu" in item.desc
    assert "OpenReview ID：qq4yipldw2" in item.desc


def test_openreview_parser_filters_status_visibility_and_deduplicates():
    older = {
        **NOTE,
        "id": "older123",
        "pdate": NOTE["pdate"] - 1000,
        "tmdate": NOTE["tmdate"] - 1000,
        "content": {
            **NOTE["content"],
            "title": {"value": "Older accepted paper"},
        },
    }
    duplicate_title = {
        **NOTE,
        "id": "other123",
    }
    private = {
        **older,
        "id": "private1",
        "readers": ["TMLR"],
    }
    rejected = {
        **older,
        "id": "reject12",
        "content": {
            **older["content"],
            "venue": {"value": "Rejected by TMLR"},
            "venueid": {"value": "TMLR/Rejected"},
        },
    }
    no_accept_invitation = {
        **older,
        "id": "pending1",
        "invitations": ["TMLR/-/Submission"],
    }

    items = openreview._parse_notes({
        "notes": [
            older,
            NOTE,
            duplicate_title,
            private,
            rejected,
            no_accept_invitation,
        ]
    })

    assert [item.id for item in items] == ["qq4yipldw2", "older123"]


def test_openreview_uses_author_ids_and_truncates_long_abstract():
    note = {
        **NOTE,
        "id": "authors1",
        "content": {
            **NOTE["content"],
            "authors": None,
            "authorids": {
                "value": [
                    "~Ada_Lovelace1",
                    "~Grace_Hopper2",
                    "~Edsger_Dijkstra3",
                    "~Donald_Knuth4",
                ]
            },
            "abstract": {"value": "x" * 700},
            "title": {"value": "Fallback authors"},
        },
    }

    item = openreview._parse_notes({"notes": [note]})[0]

    assert item.author == "Ada Lovelace, Grace Hopper, Edsger Dijkstra et al."
    assert "摘要：" + "x" * 599 + "…" in item.desc

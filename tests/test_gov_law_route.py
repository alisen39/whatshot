from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import gov_law
from whats_hot_api.utils.http_client import RequestResult


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/gov-law",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
async def test_gov_law_uses_explicit_date_sort_and_maps_stable_details(monkeypatch):
    async def fake_post(**kwargs):  # noqa: ANN003
        assert kwargs["body"]["orderByParam"] == {
            "order": "gbrq",
            "sort": "DESC",
        }
        assert kwargs["body"]["pageSize"] == 30
        assert kwargs["cache_key"] == "gov-law:recent:gbrq-desc:30"
        return RequestResult(
            False,
            "2026-07-17T00:00:00+00:00",
            {
                "code": 200,
                "rows": [
                    {
                        "bbbs": "older-id",
                        "title": "Older Regulation",
                        "gbrq": "2026-06-20",
                        "sxrq": "2026-07-01",
                        "sxx": 3,
                        "flxz": "地方法规",
                        "zdjgName": "Older Legislature",
                    },
                    {
                        "bbbs": "newer-id",
                        "title": "New Regulation",
                        "gbrq": "2026-06-29",
                        "sxrq": "2027-01-01",
                        "sxx": 4,
                        "flxz": "法律",
                        "zdjgName": "全国人民代表大会常务委员会",
                    },
                ],
            },
        )

    monkeypatch.setattr(gov_law, "post", fake_post)
    route_data = await gov_law.handle_route(_request())
    item = route_data.data[0]

    assert route_data.type == "最新法律法规"
    assert item.id == "newer-id"
    assert item.title == "New Regulation"
    assert item.author == "全国人民代表大会常务委员会"
    assert item.desc == "法律 · 尚未生效 · 施行日期：2027-01-01"
    assert item.timestamp == 1782662400000
    assert item.url == (
        "https://flk.npc.gov.cn/detail?"
        "id=newer-id&fileId=&type=&title=New+Regulation"
    )


def test_gov_law_marks_amendment_decision_detail_type():
    url = gov_law._detail_url(
        "decision-id",
        "关于修改某法的决定",
        "修改、废止的决定",
    )

    assert "type=decision" in url

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import youdao
from whats_hot_api.utils.http_client import RequestResult


def _request(query: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/youdao/popular-courses",
        "query_string": query,
        "headers": [],
    })


def _course(course_id: int = 289622, **overrides: object) -> dict:
    row = {
        "categoryName": "升学",
        "courseSaleNum": 88,
        "courseSalePrice": 0,
        "courseTime": "随到随学",
        "courseTitle": "【9月升高一】家长选课咨询",
        "expireDate": "2026-07-30 00:00",
        "hideLessonNum": False,
        "hideNum": False,
        "id": course_id,
        "itemType": 1,
        "lessonNum": 8,
        "status": 1,
        "teacherList": [
            {
                "name": "有道升学规划师",
                "imgUrl": "https://oimagec7.ydstatic.com/image?id=teacher&product=xue",
            }
        ],
        "title": "【9月升高一】家长选课咨询",
    }
    row.update(overrides)
    return row


def _html(*rows: dict, dom_ids: list[int] | None = None) -> str:
    app = {"state": {"home": {"popularCourse": list(rows)}}}
    ids = dom_ids if dom_ids is not None else [row["id"] for row in rows]
    anchors = "".join(
        f'<a href="https://ke.youdao.com/course/detail/{course_id}?'
        'position=courseIndex&inLoc=web_home_popular&Pdt=jpkWeb">课程</a>'
        for course_id in ids
    )
    return (
        "<html><body><div><h3>热门课程</h3>"
        f"{anchors}</div><script>window.App={json.dumps(app)};</script></body></html>"
    )


def test_youdao_parser_preserves_official_course_order_and_identity() -> None:
    hidden = _course(
        162521,
        title="【高一数学】专属1对1规划（限时0.1元）",
        courseTitle="【高一数学】专属1对1规划（限时0.1元）",
        courseSaleNum=0,
        courseSalePrice=0.1,
        hideNum=True,
        lessonNum=1,
        expireDate="2028-12-31 23:59",
    )

    rows = youdao._parse_popular_courses(_html(_course(), hidden))

    assert [row.id for row in rows] == ["289622", "162521"]
    assert rows[0].url == "https://ke.youdao.com/course/detail/289622"
    assert rows[0].author == "有道升学规划师"
    assert rows[0].hot == 88
    assert rows[0].desc == "升学 · 随到随学 · 8 课时 · 免费 · 报名截止：2026-07-30 00:00"
    assert rows[0].cover.startswith("https://oimagec7.ydstatic.com/")
    assert rows[1].hot is None
    assert "￥0.1" in rows[1].desc


def test_youdao_parser_requires_dom_and_state_identity_order() -> None:
    rows = (_course(), _course(289623))
    assert youdao._parse_popular_courses(_html(*rows, dom_ids=[289623, 289622])) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("courseTitle", "另一门课程"),
        ("status", 0),
        ("itemType", 2),
        ("courseSaleNum", -1),
        ("hideNum", "false"),
        ("expireDate", "July 30"),
        ("teacherList", []),
    ],
)
def test_youdao_parser_rejects_invalid_public_course_contract(
    field: str,
    value: object,
) -> None:
    assert youdao._parse_popular_courses(_html(_course(**{field: value}))) == []


def test_youdao_parser_rejects_duplicate_course_ids() -> None:
    assert youdao._parse_popular_courses(_html(_course(), _course())) == []


@pytest.mark.asyncio
async def test_youdao_route_fetches_public_course_home(monkeypatch) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://ke.youdao.com/?position=courseIndex"
        assert kwargs["cache_key"] == "youdao:popular-courses"
        assert kwargs["response_type"] == "text"
        return RequestResult(
            data=_html(_course()),
            from_cache=False,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(youdao, "get", fake_get)
    result = await youdao.handle_route(_request(), True)

    assert result.name == "youdao"
    assert result.type == "热门课程"
    assert result.total == 1


@pytest.mark.asyncio
async def test_youdao_route_falls_back_to_popular_courses(monkeypatch) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        return RequestResult(
            data=_html(_course()),
            from_cache=True,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(youdao, "get", fake_get)
    result = await youdao.handle_route(_request(b"type=notes"))
    assert result.type == "热门课程"

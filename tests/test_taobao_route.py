from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import taobao
from whats_hot_api.utils.http_client import RequestResult


def _request(query: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/taobao/chuanda",
        "query_string": query,
        "headers": [],
    })


def _theme(theme_id: object = 203601814, **overrides: object) -> dict:
    row = {
        "themePageId": theme_id,
        "title": "学生摄影入门包",
        "floorTitle": "学生摄影入门包",
        "floorSubTitle": "二手佳能200D2+配件，开学就能拍",
        "keywords": "佳能200D2二手套机,64G高速SD卡",
        "seo_category": "闪存卡/U盘/存储/移动硬盘",
        "floorPicUrl": "https://img.alicdn.com/example.png",
        "likeCount": 25,
        "selfTheme": False,
        "source": 7,
    }
    row.update(overrides)
    return row


def _html(board_type: str = "shuma", *feeds: dict, **context_overrides: object) -> str:
    tabs = [
        {"tabId": "all", "tabName": "推荐"},
        {"tabId": "chuanda", "tabName": "穿搭"},
        {"tabId": "shuma", "tabName": "数码"},
    ]
    context = {
        "routePath": "/aiGuangHome",
        "matchedIds": ["aiGuangHome"],
        "renderMode": "SSR",
        "loaderData": {
            "aiGuangHome": {
                "data": [{"homePageData": {"tabList": tabs, "feedsList": list(feeds)}}]
            }
        },
    }
    context.update(context_overrides)
    tab_html = "".join(
        f'<h2 id="theme-tab-{tab_id}" '
        f'class="ai-guang-theme-tabs-item'
        f'{" ai-guang-theme-tabs-item-active" if tab_id == board_type else ""}">'
        f"{tab_name}</h2>"
        for tab_id, tab_name in (("chuanda", "穿搭"), ("shuma", "数码"))
    )
    return f"""
    <html><head>
      <link rel="canonical" href="https://guangtao.taobao.com/category-{board_type}">
    </head><body>
      {tab_html}
      <script>var b = {json.dumps(context, ensure_ascii=False)}; window.__ICE_APP_CONTEXT__=b</script>
    </body></html>
    """


def test_taobao_parser_preserves_public_theme_identity_and_order() -> None:
    second = _theme(
        202507152,
        title="手机电瓶一充搞定",
        floorTitle="手机电瓶一充搞定",
        likeCount=0,
    )
    invalid = _theme("not-numeric")
    rows = taobao._parse_board(
        _html("shuma", _theme(), _theme(), second, invalid),
        "shuma",
    )

    assert [row.id for row in rows] == ["203601814", "202507152"]
    assert rows[0].url == "https://guangtao.taobao.com/topic-203601814.html"
    assert rows[0].hot == 25
    assert rows[0].cover == "https://img.alicdn.com/example.png"
    assert rows[0].desc == (
        "二手佳能200D2+配件，开学就能拍 · "
        "关键词：佳能200D2二手套机、64G高速SD卡 · "
        "类目：闪存卡/U盘/存储/移动硬盘"
    )


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("selfTheme", True),
        ("source", 6),
        ("floorTitle", ""),
        ("title", "另一个标题"),
    ],
)
def test_taobao_parser_rejects_non_public_or_inconsistent_theme(
    override: str,
    value: object,
) -> None:
    assert taobao._parse_board(
        _html("shuma", _theme(**{override: value})),
        "shuma",
    ) == []


@pytest.mark.parametrize(
    ("needle", "replacement"),
    [
        ("category-shuma", "category-chuanda"),
        ("theme-tab-shuma", "theme-tab-wrong"),
        ("ai-guang-theme-tabs-item-active", "ai-guang-theme-tabs-item"),
    ],
)
def test_taobao_parser_rejects_wrong_page_identity(
    needle: str,
    replacement: str,
) -> None:
    html = _html("shuma", _theme()).replace(needle, replacement)
    assert taobao._parse_board(html, "shuma") == []


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("renderMode", "CSR"),
        ("routePath", "/other"),
        ("matchedIds", ["other"]),
    ],
)
def test_taobao_parser_rejects_wrong_ssr_context(
    override: str,
    value: object,
) -> None:
    assert taobao._parse_board(
        _html("shuma", _theme(), **{override: value}),
        "shuma",
    ) == []


@pytest.mark.asyncio
async def test_taobao_route_fetches_fixed_category_page(monkeypatch) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://guangtao.taobao.com/category-shuma"
        assert kwargs["response_type"] == "text"
        assert kwargs["cache_key"] == "taobao:guangtao:shuma"
        return RequestResult(
            data=_html("shuma", _theme()),
            from_cache=False,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(taobao, "get", fake_get)
    result = await taobao.handle_route(_request(b"type=shuma"), True)

    assert result.name == "taobao"
    assert result.title == "淘宝逛一逛"
    assert result.type == "数码"
    assert result.total == 1


@pytest.mark.asyncio
async def test_taobao_route_excludes_personalized_all_board(monkeypatch) -> None:
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://guangtao.taobao.com/category-chuanda"
        return RequestResult(
            data=_html("chuanda", _theme()),
            from_cache=True,
            update_time=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
        )

    monkeypatch.setattr(taobao, "get", fake_get)
    result = await taobao.handle_route(_request(b"type=all"))
    assert "all" not in taobao.type_map
    assert result.type == "穿搭"

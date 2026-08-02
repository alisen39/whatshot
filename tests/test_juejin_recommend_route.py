from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import juejin
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_juejin_recommend_extracts_feed_items(monkeypatch):
    async def fake_post(**kwargs):  # noqa: ANN003
        assert kwargs["body"]["sort_type"] == 200
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "data": [
                    {
                        "item_info": {
                            "article_info": {
                                "article_id": "7520000000000000000",
                                "title": "推荐文章",
                                "brief_content": "摘要",
                                "digg_count": 42,
                            },
                            "author_user_info": {"user_name": "作者"},
                            "tags": [{"tag_name": "前端"}],
                        }
                    }
                ]
            },
        )

    async def fake_categories():
        return {"1": "综合", "recommend": "首页推荐"}

    monkeypatch.setattr(juejin, "post", fake_post)
    monkeypatch.setattr(juejin, "_get_category", fake_categories)
    request = Request(
        {"type": "http", "method": "GET", "path": "/juejin", "query_string": b"type=recommend", "headers": []}
    )
    route_data = await juejin.handle_route(request)

    assert route_data.type == "首页推荐"
    item = route_data.data[0]
    assert item.id == "7520000000000000000"
    assert item.author == "作者"
    assert item.hot == 42
    assert item.desc == "摘要 · 标签：前端"


@pytest.mark.asyncio
async def test_juejin_category_recommend_uses_current_category_api(monkeypatch):
    async def fake_post(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith("/article/recommend_cate_feed")
        assert kwargs["body"]["cate_id"] == "6809637769959178254"
        assert "client_type" not in kwargs["body"]
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "data": [
                    {
                        "article_info": {
                            "article_id": "456",
                            "title": "后端分类文章",
                            "brief_content": "摘要",
                            "digg_count": 88,
                        },
                        "author_user_info": {"user_name": "作者"},
                        "tags": [{"tag_name": "后端"}],
                    }
                ]
            },
        )

    async def fake_categories():
        return dict(juejin._SEED_TYPES)

    monkeypatch.setattr(juejin, "post", fake_post)
    monkeypatch.setattr(juejin, "_get_category", fake_categories)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/juejin",
            "query_string": b"type=recommend-backend",
            "headers": [],
        }
    )

    route_data = await juejin.handle_route(request)
    assert route_data.type == "后端推荐"
    assert route_data.data[0].id == "456"
    assert route_data.data[0].hot == 88


def test_juejin_advertises_fixed_category_recommendations():
    assert juejin.ROUTE_META["params"]["type"]["type"] == {
        "1": "综合",
        "hot": "全站热榜",
        "recommend": "首页推荐",
        "recommend-backend": "后端推荐",
        "recommend-frontend": "前端推荐",
        "recommend-ai": "人工智能推荐",
    }

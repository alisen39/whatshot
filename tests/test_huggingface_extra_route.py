from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import huggingface
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/huggingface",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _repo_row(repo_id: str, likes: int, trending: float) -> dict:
    return {
        "id": repo_id,
        "author": repo_id.split("/")[0],
        "likes": likes,
        "trendingScore": trending,
        "lastModified": "2026-09-30T12:00:00.000Z",
        "tags": ["text-generation", "license:apache-2.0"],
    }


@pytest.mark.asyncio
async def test_trending_models_board_uses_expand_params_and_trending_hot(monkeypatch):
    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(
            False,
            "2026-10-01T00:00:00+00:00",
            [_repo_row("org/model-a", 4321, 55.1), _repo_row("org/model-b", 100, 44.0)],
        )

    monkeypatch.setattr(huggingface, "get", fake_get)
    result = await huggingface.handle_route(_request("trending-models"), no_cache=True)

    # 扩展榜用 expand[](trendingScore 只在这个序列化里),而不是既有榜的 full=true
    assert captured["url"] == "https://huggingface.co/api/models"
    params = captured["params"]
    assert ("sort", "trendingScore") in params
    assert ("expand[]", "trendingScore") in params
    assert "full" not in [k for k, _ in params]
    assert result.type == "Trending 模型"
    assert result.data[0].hot == 55  # hot 字段 int 化;trendingScore 榜取该字段
    assert result.data[0].desc == "text-generation"  # license:* 标签被去掉
    assert result.data[0].timestamp == 1790769600000


@pytest.mark.asyncio
async def test_likes_models_board_hot_comes_from_likes(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, "t", [_repo_row("org/model-a", 4321, 55.1)])

    monkeypatch.setattr(huggingface, "get", fake_get)
    result = await huggingface.handle_route(_request("likes-models"), no_cache=True)
    assert result.data[0].hot == 4321


@pytest.mark.asyncio
async def test_trending_spaces_board_uses_card_title_and_description(monkeypatch):
    row = _repo_row("org/space-a", 88, 66.0)
    row["cardData"] = {"title": "我的空间", "short_description": "一句话简介"}

    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, "t", [row])

    monkeypatch.setattr(huggingface, "get", fake_get)
    result = await huggingface.handle_route(_request("trending-spaces"), no_cache=True)

    params = captured["params"]
    assert ("expand[]", "cardData") in params  # Spaces 额外取 cardData
    item = result.data[0]
    assert item.title == "我的空间"  # 页面/tophub 显示 README 的 title
    assert item.desc == "一句话简介"  # short_description 优先于标签
    assert item.url == "https://huggingface.co/spaces/org/space-a"
    assert item.hot == 66.0


@pytest.mark.asyncio
async def test_blog_zh_board_parses_all_blogs(monkeypatch):
    payload = {
        "allBlogs": [
            {
                "url": "/blog/zh/hello",
                "title": "中文博客",
                "upvotes": 12,
                "publishedAt": "2026-09-30T00:00:00.000Z",
                "thumbnail": "/blog/thumbs/1.png",
                "authorsData": [
                    {"fullname": "作者一"},
                    {"fullname": "作者二"},
                    {"fullname": "作者三"},
                    {"fullname": "作者四"},
                ],
            }
        ],
        "communityBlogPosts": [{"url": "/blog/zh/community", "title": "社区文章"}],
    }

    async def fake_get(**kwargs):
        return RequestResult(False, "2026-10-01T00:00:00+00:00", payload)

    monkeypatch.setattr(huggingface, "get", fake_get)
    result = await huggingface.handle_route(_request("blog-zh"), no_cache=True)

    assert result.type == "中文博客"
    assert result.total == 1  # communityBlogPosts 是侧栏,不属于中文博客列表
    item = result.data[0]
    assert item.id == "https://huggingface.co/blog/zh/hello"
    assert item.title == "中文博客"
    assert item.author == "作者一, 作者二, 作者三 et al."  # 与 huggingface-papers 一致
    assert item.cover == "https://huggingface.co/blog/thumbs/1.png"
    assert item.hot == 12
    assert item.timestamp == 1790726400000


@pytest.mark.asyncio
async def test_extra_board_empty_result_is_an_error(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, "t", [])

    monkeypatch.setattr(huggingface, "get", fake_get)
    with pytest.raises(ValueError, match="returned no valid rows"):
        await huggingface.handle_route(_request("trending-datasets"), no_cache=True)

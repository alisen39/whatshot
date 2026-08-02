from __future__ import annotations

from urllib.parse import urlencode

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import huggingface
from whats_hot_api.utils.http_client import RequestResult


def _request(board: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": urlencode({"type": board}).encode(), "headers": []})


@pytest.mark.asyncio
async def test_models_board_uses_fixed_download_ranking(monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_get(**kwargs):
        calls.append(kwargs)
        return RequestResult(False, "update", [{"id": "org/model", "downloads": 42, "likes": 3, "lastModified": "2026-07-18T00:00:00Z", "tags": ["text-generation", "license:mit"]}])

    monkeypatch.setattr(huggingface, "get", fake_get)
    result = await huggingface.handle_route(_request("models"))
    assert calls[0]["url"] == "https://huggingface.co/api/models"
    assert calls[0]["params"]["sort"] == "downloads"
    assert result.type == "热门模型"
    assert result.data[0].url == "https://huggingface.co/org/model"
    assert result.data[0].hot == 42


@pytest.mark.asyncio
async def test_spaces_board_uses_likes_and_spaces_urls(monkeypatch) -> None:
    async def fake_get(**kwargs):
        assert kwargs["url"] == "https://huggingface.co/api/spaces"
        assert kwargs["params"]["sort"] == "likes"
        return RequestResult(False, "update", [{"id": "org/demo", "likes": 7, "sdk": "gradio", "tags": []}])

    monkeypatch.setattr(huggingface, "get", fake_get)
    result = await huggingface.handle_route(_request("spaces"))
    assert result.data[0].url == "https://huggingface.co/spaces/org/demo"
    assert result.data[0].hot == 7

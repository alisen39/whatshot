from __future__ import annotations

import pytest

from whats_hot_api.routes.hotlist import smzdm
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
async def test_smzdm_sends_browser_headers_for_json(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_get(url, **kwargs):  # noqa: ANN001, ANN003
        captured["url"] = url
        captured.update(kwargs)
        return RequestResult(
            False,
            "2026-07-25T00:00:00+00:00",
            {
                "data": [
                    {
                        "article_id": "1",
                        "title": "值得买",
                        "collection_count": "12",
                        "jump_link": "https://post.smzdm.com/p/1/",
                    }
                ]
            },
        )

    monkeypatch.setattr(smzdm, "get", fake_get)

    result = await smzdm._get_list("1", True)

    assert captured["url"].endswith("unit=1")
    assert captured["no_cache"] is True
    headers = captured["headers"]
    assert headers["Accept"].startswith("application/json")
    assert headers["Referer"] == "https://post.smzdm.com/rank/"
    assert headers["User-Agent"].startswith("Mozilla/5.0")
    assert result["data"][0].title == "值得买"

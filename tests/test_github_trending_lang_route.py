from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import github_trending_lang
from whats_hot_api.utils.http_client import RequestResult


def _request(language: str, rng: str | None = None) -> Request:
    query = f"type={language}"
    if rng:
        query = f"{query}&range={rng}"
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/github-trending-lang",
        "query_string": query.encode(),
        "headers": [],
    })


def _article(anchor_text: str, href: str, description: str, stars: str) -> str:
    return f"""
    <article class="Box-row">
      <h2><a href="{href}">{anchor_text}</a></h2>
      <p class="col-9 color-fg-muted">{description}</p>
      <span itemprop="programmingLanguage">Python</span>
      <a href="/owner/repo/stargazers">{stars}</a>
      <a href="/owner/repo/forks">12</a>
    </article>
    """


def _trending_page(title: str, articles: str = "", empty_marker: bool = False) -> str:
    marker = "It looks like we don’t have any trending repositories here." if empty_marker else ""
    return f"""
    <html><head><title>{title}</title></head><body>
    {articles}{marker}
    </body></html>
    """


@pytest.fixture
def _no_sleep(monkeypatch):
    async def _sleep(_):
        return None

    monkeypatch.setattr(github_trending_lang.asyncio, "sleep", _sleep)


@pytest.fixture
def _no_cache(monkeypatch):
    async def _get(_key):
        return None

    async def _set(*_args, **_kwargs):
        return None

    monkeypatch.setattr(github_trending_lang.cache, "get", _get)
    monkeypatch.setattr(github_trending_lang.cache, "set", _set)


@pytest.mark.asyncio
async def test_python_daily_board_builds_language_url(monkeypatch, _no_cache):
    captured = {}

    async def fake_get(**kwargs):
        captured["url"] = kwargs["url"]
        return RequestResult(
            False,
            "2026-10-01T00:00:00+00:00",
            _trending_page(
                "Trending Python repositories on GitHub today",
                _article("owner1 / repo1", "/owner1/repo1", "A repo", "1,234")
                + _article("owner2 / repo2", "/owner2/repo2", "", "5"),
            ),
        )

    monkeypatch.setattr(github_trending_lang, "get", fake_get)
    result = await github_trending_lang.handle_route(_request("python"), no_cache=True)

    assert captured["url"] == "https://github.com/trending/python?since=daily"
    assert result.name == "github-trending-lang"
    assert result.type == "Python · 日榜"
    assert result.link == "https://github.com/trending/python?since=daily"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "/owner1/repo1"
    assert first.title == "repo1"
    assert first.author == "owner1"
    assert first.hot == 1234
    assert first.url == "https://github.com/owner1/repo1"
    assert first.desc == "A repo"
    assert result.message is None


@pytest.mark.asyncio
async def test_weekly_range_is_requested_and_labelled(monkeypatch, _no_cache):
    captured = {}

    async def fake_get(**kwargs):
        captured["url"] = kwargs["url"]
        return RequestResult(
            False,
            "2026-10-01T00:00:00+00:00",
            _trending_page(
                "Trending C# repositories on GitHub this week",
                _article("owner1 / repo1", "/owner1/repo1", "A repo", "1"),
            ),
        )

    monkeypatch.setattr(github_trending_lang, "get", fake_get)
    result = await github_trending_lang.handle_route(_request("csharp", "weekly"), no_cache=True)

    assert captured["url"] == "https://github.com/trending/c%23?since=weekly"
    assert result.type == "C# · 周榜"


@pytest.mark.asyncio
async def test_empty_trending_returns_zero_items_with_message(monkeypatch, _no_cache, _no_sleep):
    async def fake_get(**kwargs):
        return RequestResult(
            False,
            "2026-10-01T00:00:00+00:00",
            _trending_page("Trending Common Lisp repositories on GitHub today", empty_marker=True),
        )

    monkeypatch.setattr(github_trending_lang, "get", fake_get)
    result = await github_trending_lang.handle_route(_request("common-lisp"), no_cache=True)

    assert result.total == 0
    assert result.data == []
    assert result.message == "GitHub 当前没有 Common Lisp 的 Trending 仓库"


@pytest.mark.asyncio
async def test_unknown_language_is_rejected():
    with pytest.raises(ValueError, match="Unknown language 'ruby2'"):
        await github_trending_lang.handle_route(_request("ruby2"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_range_is_rejected():
    with pytest.raises(ValueError, match="Unknown range"):
        await github_trending_lang.handle_route(_request("python", "hourly"), no_cache=True)


@pytest.mark.asyncio
async def test_wrong_language_page_is_an_error(monkeypatch, _no_cache, _no_sleep):
    async def fake_get(**kwargs):
        return RequestResult(
            False,
            "2026-10-01T00:00:00+00:00",
            # c%23 这类标识写错时,GitHub 返回 200 但显示的是另一种语言的列表
            _trending_page("Trending C repositories on GitHub today", _article("owner / repo", "/o/r", "", "1")),
        )

    monkeypatch.setattr(github_trending_lang, "get", fake_get)
    with pytest.raises(RuntimeError, match="shows 'C' trending"):
        await github_trending_lang.handle_route(_request("csharp"), no_cache=True)


@pytest.mark.asyncio
async def test_silent_daily_fallback_is_an_error(monkeypatch, _no_cache, _no_sleep):
    async def fake_get(**kwargs):
        return RequestResult(
            False,
            "2026-10-01T00:00:00+00:00",
            _trending_page(
                "Trending Python repositories on GitHub today",
                _article("owner / repo", "/o/r", "", "1"),
            ),
        )

    monkeypatch.setattr(github_trending_lang, "get", fake_get)
    with pytest.raises(RuntimeError, match="since=weekly"):
        await github_trending_lang.handle_route(_request("python", "weekly"), no_cache=True)


def test_removed_languages_are_gone():
    boards = github_trending_lang.ROUTE_META["params"]["type"]["type"]
    assert {"codeql", "smarty"}.isdisjoint(boards)
    assert list(boards) == list(github_trending_lang.LANGUAGES)
    assert next(iter(boards)) == "python"

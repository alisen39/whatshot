from __future__ import annotations

import httpx
import pytest

from whats_hot_api.routes.hotlist import _arxiv_common


@pytest.fixture(autouse=True)
def _no_arxiv_retry_delay(monkeypatch):
    monkeypatch.setattr(_arxiv_common, "_RETRY_DELAYS_SECONDS", (0.0, 0.0))


@pytest.mark.asyncio
async def test_respect_spacing_waits_for_remaining_interval(monkeypatch) -> None:
    sleeps: list[float] = []
    times = iter([10.0, 12.0])

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(_arxiv_common, "_MIN_SPACING_SECONDS", 3.0)
    monkeypatch.setattr(_arxiv_common, "_last_request_at", 9.0)
    monkeypatch.setattr(_arxiv_common, "_monotonic", lambda: next(times))
    monkeypatch.setattr(_arxiv_common.asyncio, "sleep", fake_sleep)

    await _arxiv_common._respect_spacing()

    assert sleeps == [2.0]
    assert _arxiv_common._last_request_at == 12.0


def test_arxiv_headers_identifies_the_client() -> None:
    headers = _arxiv_common.arxiv_headers()

    assert headers == {
        "User-Agent": "whats-hot-api/0.2 (+https://github.com/alisen39/whatshot)"
    }


@pytest.mark.asyncio
async def test_fetch_with_spacing_retries_one_timeout(monkeypatch) -> None:
    calls = 0

    async def no_spacing() -> None:
        return None

    async def fetch() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("timed out")
        return "ok"

    monkeypatch.setattr(_arxiv_common, "_respect_spacing", no_spacing)
    assert await _arxiv_common.fetch_with_spacing(fetch) == "ok"
    assert calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [406, 429, 500, 503])
async def test_fetch_with_spacing_retries_retryable_status(monkeypatch, status: int) -> None:
    calls = 0
    request = httpx.Request("GET", "https://export.arxiv.org/api/query")

    async def no_spacing() -> None:
        return None

    async def fetch() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            response = httpx.Response(status, request=request)
            raise httpx.HTTPStatusError("retry", request=request, response=response)
        return "ok"

    monkeypatch.setattr(_arxiv_common, "_respect_spacing", no_spacing)
    assert await _arxiv_common.fetch_with_spacing(fetch) == "ok"
    assert calls == 2


@pytest.mark.asyncio
async def test_fetch_with_spacing_raises_after_exhausting_retries(monkeypatch) -> None:
    calls = 0
    request = httpx.Request("GET", "https://export.arxiv.org/api/query")

    async def no_spacing() -> None:
        return None

    async def fetch() -> None:
        nonlocal calls
        calls += 1
        response = httpx.Response(406, request=request)
        raise httpx.HTTPStatusError("edge glitch", request=request, response=response)

    monkeypatch.setattr(_arxiv_common, "_respect_spacing", no_spacing)
    with pytest.raises(httpx.HTTPStatusError):
        await _arxiv_common.fetch_with_spacing(fetch)
    assert calls == 3


@pytest.mark.asyncio
async def test_fetch_with_spacing_backs_off_before_each_retry(monkeypatch) -> None:
    request = httpx.Request("GET", "https://export.arxiv.org/api/query")
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def no_spacing() -> None:
        return None

    async def fetch() -> None:
        response = httpx.Response(406, request=request)
        raise httpx.HTTPStatusError("edge glitch", request=request, response=response)

    monkeypatch.setattr(_arxiv_common, "_respect_spacing", no_spacing)
    monkeypatch.setattr(_arxiv_common, "_RETRY_DELAYS_SECONDS", (15.0, 45.0))
    monkeypatch.setattr(_arxiv_common.asyncio, "sleep", fake_sleep)

    with pytest.raises(httpx.HTTPStatusError):
        await _arxiv_common.fetch_with_spacing(fetch)

    assert sleeps == [15.0, 45.0]


@pytest.mark.asyncio
async def test_fetch_with_spacing_does_not_retry_other_status(monkeypatch) -> None:
    calls = 0
    request = httpx.Request("GET", "https://export.arxiv.org/api/query")

    async def no_spacing() -> None:
        return None

    async def fetch() -> None:
        nonlocal calls
        calls += 1
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("fail", request=request, response=response)

    monkeypatch.setattr(_arxiv_common, "_respect_spacing", no_spacing)
    with pytest.raises(httpx.HTTPStatusError):
        await _arxiv_common.fetch_with_spacing(fetch)
    assert calls == 1

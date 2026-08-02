from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import bloomberg
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('board_type', 'feed_url'),
    [
        ('main', 'https://feeds.bloomberg.com/news.rss'),
        ('markets', 'https://feeds.bloomberg.com/markets/news.rss'),
        ('economics', 'https://feeds.bloomberg.com/economics/news.rss'),
        ('industries', 'https://feeds.bloomberg.com/industries/news.rss'),
        ('technology', 'https://feeds.bloomberg.com/technology/news.rss'),
        ('politics', 'https://feeds.bloomberg.com/politics/news.rss'),
        ('opinions', 'https://feeds.bloomberg.com/bview/news.rss'),
        ('crypto', 'https://feeds.bloomberg.com/crypto/news.rss'),
        (
            'google',
            'https://news.google.com/rss/search?'
            'q=site%3Abloomberg.com&hl=en-US&gl=US&ceid=US%3Aen',
        ),
    ],
)
async def test_bloomberg_section_boards(monkeypatch, board_type, feed_url):
    rss = """<rss><channel><item>
      <title>Bloomberg headline</title>
      <link>https://www.bloomberg.com/news/articles/example</link>
      <guid>bloomberg-example</guid>
    </item></channel></rss>"""

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs['url'] == feed_url
        return RequestResult(False, '2026-07-16T00:00:00+00:00', rss)

    monkeypatch.setattr(bloomberg, 'get', fake_get)
    request = Request({
        'type': 'http',
        'method': 'GET',
        'path': '/bloomberg',
        'query_string': f'type={board_type}'.encode(),
        'headers': [],
    })
    route_data = await bloomberg.handle_route(request)

    assert route_data.type == bloomberg.type_map[board_type]
    assert route_data.total == 1
    assert route_data.data[0].id == 'bloomberg-example'


@pytest.mark.asyncio
async def test_bloomberg_retries_transient_feed_failure(monkeypatch):
    rss = """<rss><channel><item>
      <title>Recovered headline</title>
      <link>https://www.bloomberg.com/news/articles/recovered</link>
      <guid>bloomberg-recovered</guid>
    </item></channel></rss>"""
    attempts = 0

    async def fake_get(**kwargs):  # noqa: ANN003
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError('transient Bloomberg feed timeout')
        return RequestResult(False, '2026-07-16T00:00:00+00:00', rss)

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(bloomberg, 'get', fake_get)
    monkeypatch.setattr(bloomberg.asyncio, 'sleep', no_sleep)
    request = Request({
        'type': 'http',
        'method': 'GET',
        'path': '/bloomberg',
        'query_string': b'type=main',
        'headers': [],
    })
    route_data = await bloomberg.handle_route(request)

    assert attempts == 3
    assert route_data.data[0].id == 'bloomberg-recovered'

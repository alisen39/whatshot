from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import bbc_news
from whats_hot_api.utils.http_client import RequestResult


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('board_type', 'feed_path'),
    [
        ('news', 'news/rss.xml'),
        ('world', 'news/world/rss.xml'),
        ('business', 'news/business/rss.xml'),
        ('politics', 'news/politics/rss.xml'),
        ('health', 'news/health/rss.xml'),
        ('education', 'news/education/rss.xml'),
        ('science-and-environment', 'news/science_and_environment/rss.xml'),
        ('technology', 'news/technology/rss.xml'),
        ('entertainment-and-arts', 'news/entertainment_and_arts/rss.xml'),
    ],
)
async def test_bbc_news_section_boards(monkeypatch, board_type, feed_path):
    rss = """<rss><channel><item>
      <title>BBC headline</title>
      <link>https://www.bbc.com/news/articles/example</link>
      <guid>bbc-example</guid>
    </item></channel></rss>"""

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs['url'] == f'https://feeds.bbci.co.uk/{feed_path}'
        return RequestResult(False, '2026-07-16T00:00:00+00:00', rss)

    monkeypatch.setattr(bbc_news, 'get', fake_get)
    request = Request({
        'type': 'http',
        'method': 'GET',
        'path': '/bbc-news',
        'query_string': f'type={board_type}'.encode(),
        'headers': [],
    })
    route_data = await bbc_news.handle_route(request)

    assert route_data.type == bbc_news.type_map[board_type]
    assert route_data.total == 1
    assert route_data.data[0].id == 'bbc-example'

from __future__ import annotations

from copy import deepcopy

import pytest
from starlette.requests import Request

from whats_hot_api.models import ListItem
from whats_hot_api.routes.hotlist import yahoo_finance
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str | None = None) -> Request:
    query = f"type={board_type}".encode() if board_type else b""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/yahoo-finance/default",
        "query_string": query,
        "headers": [],
    })


def _quote(index: int, **overrides: object) -> dict:
    row = {
        "symbol": f"STK{index}",
        "shortName": f"Stock {index}",
        "longName": f"Stock {index} Incorporated",
        "quoteType": "EQUITY",
        "regularMarketPrice": 100.0 + index,
        "regularMarketChangePercent": 5.0 - index / 10,
        "regularMarketVolume": 1_000_000 - index,
        "averageDailyVolume3Month": 800_000,
        "marketCap": 2_000_000_000,
        "fiftyTwoWeekChangePercent": 50.0 - index,
        "trendingScore": {"raw": 100.0 - index},
        "fullExchangeName": "NasdaqGS",
        "companyLogoUrl": f"https://s.yimg.com/logo/{index}.png",
    }
    row.update(overrides)
    return row


def _market_html(
    rows: list[dict] | None = None,
    board_type: str = "trending",
    *,
    active: bool = True,
) -> str:
    payload = rows or [_quote(index) for index in range(1, 26)]
    _, heading, tab_id = yahoo_finance._MARKET_TYPES[board_type]
    rendered_rows = "".join(
        f"""
        <tr data-testid="data-table-v2-row">
          <td data-testid-cell="ticker"><a href="/quote/{row['symbol']}/">{row['symbol']}</a></td>
          <td data-testid-cell="companyshortname.raw">{row['shortName']}</td>
          <td data-testid-cell="intradayprice">
            <span data-testid="change">{row['regularMarketPrice']}</span>
            <fin-streamer data-field="regularMarketChangePercent"
              data-value="{row['regularMarketChangePercent']}"></fin-streamer>
          </td>
          <td data-testid-cell="dayvolume">1.00M</td>
          <td data-testid-cell="avgdailyvol3m">800.00K</td>
          <td data-testid-cell="intradaymarketcap">2.00B</td>
          <td data-testid-cell="fiftytwowkpercentchange">+50.00%</td>
        </tr>
        """
        for row in payload
    )
    return f"""
      <html><h1>{heading}</h1>
      <a id="{tab_id}" aria-selected="{str(active).lower()}"></a>
      <div data-testid="markets-table-wrapper"><table><tbody>
      {rendered_rows}
      </tbody></table></div></html>
    """


@pytest.mark.asyncio
async def test_yahoo_finance_preserves_existing_news_default(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://finance.yahoo.com/news/rssindex"
        assert kwargs["no_cache"] is True
        return RequestResult(False, "2026-07-18T00:00:00+00:00", "<rss><channel><item><guid>same</guid><title>First story</title><link>https://example.com/news/first/?src=same</link></item><item><guid>same</guid><title>Second story</title><link>https://example.com/news/second/?src=same</link></item></channel></rss>")

    monkeypatch.setattr(yahoo_finance, "get", fake_get)
    result = await yahoo_finance.handle_route(_request(), True)

    assert result.type == "财经新闻"
    assert result.total == 2
    assert len({item.id for item in result.data}) == 2
    assert all(item.id.startswith("yf-") for item in result.data)


@pytest.mark.asyncio
async def test_yahoo_finance_fetches_official_market_table(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://finance.yahoo.com/markets/stocks/gainers/"
        assert kwargs["response_type"] == "text"
        assert kwargs["cache_key"] == "yahoo-finance:stocks:day-gainers:top-25"
        return RequestResult(
            False,
            "2026-07-18T00:00:00+00:00",
            _market_html(board_type="day-gainers"),
        )

    monkeypatch.setattr(yahoo_finance, "get", fake_get)
    result = await yahoo_finance.handle_route(_request("day-gainers"), True)

    assert result.type == "当日涨幅榜"
    assert result.total == 25
    assert result.data[0].id == "STK1"
    assert result.data[0].title == "STK1 · Stock 1"
    assert result.data[0].url == "https://finance.yahoo.com/quote/STK1/"
    assert "当日涨跌 +4.90%" in (result.data[0].desc or "")
    assert result.data[0].hot == 490


@pytest.mark.asyncio
async def test_yahoo_finance_fetches_trending_equities_from_official_page(monkeypatch):
    rows = [_quote(index) for index in range(1, 26)]

    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"] == "https://finance.yahoo.com/markets/stocks/trending/"
        assert kwargs["response_type"] == "text"
        return RequestResult(
            False,
            "2026-07-18T00:00:00+00:00",
            _market_html(rows),
        )

    monkeypatch.setattr(yahoo_finance, "get", fake_get)
    result = await yahoo_finance.handle_route(_request("trending"), True)

    assert result.type == "热门股票"
    assert result.total == 25
    assert result.data[0].id == "STK1"
    assert result.data[-1].id == "STK25"
    assert result.data[0].hot is None
    assert "成交量 1.00M" in (result.data[0].desc or "")
    assert "52 周涨跌 +50.00%" in (result.data[0].desc or "")


def test_yahoo_finance_market_parser_rejects_duplicate_or_wrong_link():
    rows = [_quote(index) for index in range(1, 26)]
    duplicate = deepcopy(rows)
    duplicate[1]["symbol"] = duplicate[0]["symbol"]
    assert yahoo_finance._parse_trending(_market_html(duplicate)) == []

    wrong_link = _market_html(rows).replace(
        'href="/quote/STK1/"', 'href="/quote/OTHER/"', 1
    )
    assert yahoo_finance._parse_trending(wrong_link) == []


def test_yahoo_finance_trending_rejects_wrong_page_and_short_universe():
    rows = [_quote(index) for index in range(1, 26)]
    wrong_page = _market_html(rows, active=False)
    assert yahoo_finance._parse_trending(wrong_page) == []
    assert yahoo_finance._parse_trending(_market_html(rows[:-1])) == []

from whats_hot_api.routes.hotlist.barchart import _build_items


def test_build_items_uses_contract_identity_and_metrics():
    rows = [
        {
            "baseSymbol": "TSLA",
            "optionType": "Call",
            "strikePrice": "382.50",
            "expirationDate": "07/29/26",
            "volumeOpenInterestRatio": "18.5",
            "volume": "12,345",
            "openInterest": "667",
            "lastPrice": "4.25",
            "volatility": "42.1",
        },
        {
            "baseSymbol": "TSLA",
            "optionType": "Call",
            "strikePrice": "382.50",
            "expirationDate": "07/29/26",
            "volumeOpenInterestRatio": "18.5",
        },
        {"baseSymbol": "bad symbol", "optionType": "Put", "strikePrice": "1", "expirationDate": "07/29/26", "volumeOpenInterestRatio": "1"},
    ]

    items = _build_items(rows, "all")

    assert len(items) == 1
    assert items[0].id == "TSLA:call:382.50:07/29/26"
    assert items[0].title == "TSLA Call $382.50"
    # ListItem's shared ``hot`` field is integer-normalized; the exact ratio
    # remains in the visible description.
    assert items[0].hot == 18
    assert items[0].url == "https://www.barchart.com/stocks/quotes/TSLA/options"
    assert "成交量：12,345" in items[0].desc
    assert "量/OI：18.5" in items[0].desc


def test_build_items_filters_option_type_after_fetching_shared_list():
    rows = [
        {"baseSymbol": "ABC", "optionType": "Call", "strikePrice": "1", "expirationDate": "08/01/26", "volumeOpenInterestRatio": "9"},
        {"baseSymbol": "XYZ", "optionType": "Put", "strikePrice": "2", "expirationDate": "08/01/26", "volumeOpenInterestRatio": "8"},
    ]

    items = _build_items(rows, "put")

    assert [item.id for item in items] == ["XYZ:put:2:08/01/26"]

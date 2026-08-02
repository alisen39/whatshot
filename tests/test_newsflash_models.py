from __future__ import annotations

from whats_hot_api.models import GoldItem, ListItem, NewsFlashItem, RouterData


def test_gold_item_has_independent_contract():
    item = GoldItem(
        id="shipin",
        title="足金（饰品、工艺品）",
        desc="销售价：1262 元/克，回收价：879 元/克",
        sellPrice="1262",
        recyclePrice="879",
        url="",
    )

    dumped = item.model_dump()
    assert dumped["sellPrice"] == 1262
    assert dumped["recyclePrice"] == 879
    assert "hot" not in dumped


def test_newsflash_item_has_independent_contract():
    item = NewsFlashItem(
        id=123,
        title="快讯标题",
        content="完整快讯正文",
        source="",
        tags=None,
        images=None,
        symbols=None,
        metrics=None,
        timestamp="1782668759",
        url="https://example.com/news",
        hot=999,
    )

    dumped = item.model_dump()
    assert dumped["id"] == "123"
    assert dumped["source"] is None
    assert dumped["tags"] == []
    assert dumped["images"] == []
    assert dumped["symbols"] == []
    assert dumped["metrics"] == {}
    # 秒级输入（10 位）由 coerce_timestamp 自动补齐为毫秒（13 位）
    assert dumped["timestamp"] == 1782668759000
    assert dumped["mobileUrl"] is None
    assert "mobileUrl" not in item.model_dump(exclude_none=True)
    assert "hot" not in dumped


def test_timestamp_normalizes_seconds_to_milliseconds():
    """数据标准：timestamp 统一为 Unix 毫秒级整数。"""
    # ListItem 秒级 → 毫秒
    list_item = ListItem(
        id="1",
        title="热搜",
        url="",
        timestamp=1783231621,  # 秒级
    )
    assert list_item.timestamp == 1783231621000

    # NewsFlashItem 毫秒级原样保留
    flash_item = NewsFlashItem(
        id="2",
        title="快讯",
        content="正文",
        url="",
        mobileUrl="",
        timestamp=1783231621000,  # 已是毫秒
    )
    assert flash_item.timestamp == 1783231621000

    # GoldItem 秒级 → 毫秒
    gold_item = GoldItem(
        id="3",
        title="足金",
        url="",
        mobileUrl="",
        timestamp=1783231621,
    )
    assert gold_item.timestamp == 1783231621000


def test_router_data_accepts_newsflash_items():
    item = NewsFlashItem(
        id="1",
        title="快讯标题",
        content="完整快讯正文",
        url="https://example.com/news",
        mobileUrl="https://example.com/news",
    )

    data = RouterData(
        kind="newsflash",
        name="demo-flash",
        title="Demo 快讯",
        type="7x24",
        total=1,
        fromCache=False,
        updateTime="2026-06-29T00:00:00+00:00",
        data=[item],
    )

    assert data.kind == "newsflash"
    assert isinstance(data.data[0], NewsFlashItem)


def test_router_data_accepts_gold_items_and_round_trips():
    item = GoldItem(
        id="shipin",
        title="足金",
        sellPrice=1262,
        recyclePrice=879,
        url="",
    )

    data = RouterData(
        kind="gold",
        name="zdf",
        title="周大福",
        type="金价实时行情",
        total=1,
        fromCache=False,
        updateTime="2026-07-30T00:00:00+00:00",
        data=[item],
    )
    restored = RouterData.model_validate(data.model_dump())

    assert restored.kind == "gold"
    assert isinstance(restored.data[0], GoldItem)

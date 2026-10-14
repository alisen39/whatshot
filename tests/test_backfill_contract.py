from __future__ import annotations

import importlib
import pkgutil
import sys
from dataclasses import dataclass
from types import ModuleType
from uuid import uuid4

import pytest

import whats_hot_api.routes.newsflash as newsflash_routes
from whats_hot_api.backfill import (
    BackfillPage,
    BackfillSpec,
    BackfillStrategy,
    decode_cursor,
    encode_cursor,
    resolve_spec,
    snapshot,
    unsupported,
)
from whats_hot_api.catalog import RouteCatalog
from whats_hot_api.fetch import (
    FetchBackfillUnsupportedError,
    FetchInvalidRequestError,
    FetchRequest,
    FetchService,
)
from whats_hot_api.fetch.service import _ordered_path_types
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils import http_client


def _newsflash_modules() -> list[ModuleType]:
    modules = []
    for info in pkgutil.iter_modules(newsflash_routes.__path__):
        if info.name.startswith("_"):
            continue
        modules.append(importlib.import_module(f"{newsflash_routes.__name__}.{info.name}"))
    return modules


@pytest.mark.parametrize("module", _newsflash_modules(), ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_every_newsflash_route_declares_backfill_for_every_type(module: ModuleType) -> None:
    declared = getattr(module, "BACKFILL", None)
    assert isinstance(declared, dict) and declared, (
        f"{module.__name__} must declare BACKFILL (see whats_hot_api/backfill.py)"
    )
    for path_type in _ordered_path_types(getattr(module, "ROUTE_META", None)):
        spec = resolve_spec(declared, path_type)
        assert isinstance(spec, BackfillSpec), f"{module.__name__}:{path_type} has no backfill spec"
        assert spec.notes.strip()
        if spec.strategy is not BackfillStrategy.UNSUPPORTED:
            assert spec.verified_at, f"{module.__name__}:{path_type} must record verified_at"


def test_spec_requires_notes_and_positive_page_cap() -> None:
    with pytest.raises(ValueError):
        BackfillSpec(strategy=BackfillStrategy.TIME_CURSOR, notes=" ")
    with pytest.raises(ValueError):
        BackfillSpec(strategy=BackfillStrategy.PAGE_NUMBER, notes="x", max_pages=0)
    assert snapshot("rss").strategy is BackfillStrategy.SNAPSHOT
    assert unsupported("rank").as_dict()["strategy"] == "unsupported"


def test_cursor_round_trip_and_rejects_garbage() -> None:
    cursor = encode_cursor({"lastTime": 1, "page": 2})
    assert decode_cursor(cursor) == {"lastTime": 1, "page": 2}
    assert decode_cursor(None) == {}
    with pytest.raises(ValueError):
        decode_cursor("[1]")


@dataclass
class _RouteInfo:
    handle_route: object
    category: str = "newsflash"
    category_label: str = "快讯"


def _flash_data(*stamps: int) -> RouterData:
    return RouterData(
        kind="newsflash",
        name="demo",
        title="Demo",
        type="快讯",
        total=len(stamps),
        fromCache=False,
        updateTime="2026-10-14T00:00:00+00:00",
        data=[
            NewsFlashItem(id=str(ts), title=f"t{ts}", content="c", url="https://e.com", timestamp=ts)
            for ts in stamps
        ],
    )


def _service(handler, *, backfill: dict, backfill_page=None) -> FetchService:
    module_name = f"_backfill_test_{uuid4().hex}"
    module = ModuleType(module_name)
    module.ROUTE_META = {
        "name": "demo",
        "title": "Demo",
        "params": {"type": {"name": "榜单", "type": {"hot": "快讯", "rank": "热门"}}},
    }
    module.BACKFILL = backfill
    if backfill_page is not None:
        module.backfill_page = backfill_page
    sys.modules[module_name] = module
    handler.__module__ = module_name
    return FetchService(RouteCatalog({"demo": _RouteInfo(handler)}))


async def _handler(request, no_cache: bool = False):
    return _flash_data(3_000, 2_000)


async def test_backfill_page_passes_cursor_outside_board_identity() -> None:
    seen: dict = {}

    async def page(path_type, params, cursor, *, before):
        seen.update(path_type=path_type, params=params, cursor=cursor, before=before)
        return BackfillPage(data=_flash_data(1_000), next_cursor=None, raw_digest="d")

    service = _service(
        _handler,
        backfill={"*": BackfillSpec(strategy=BackfillStrategy.TIME_CURSOR, notes="n")},
        backfill_page=page,
    )
    result = await service.backfill_page(
        FetchRequest(site="demo", path_type="hot"), cursor='{"t":1}'
    )
    assert seen == {"path_type": "hot", "params": {}, "cursor": '{"t":1}', "before": None}
    assert result.next_cursor is None and result.data.data[0].id == "1000"
    assert service.backfill_implemented("demo", "hot")


async def test_backfill_page_forwards_before_only_when_declared() -> None:
    from datetime import UTC, datetime

    seen: dict = {}

    async def page(path_type, params, cursor, *, before):
        seen["before"] = before
        return BackfillPage(data=_flash_data(1_000), next_cursor=None)

    until = datetime(2026, 10, 13, tzinfo=UTC)
    service = _service(
        _handler,
        backfill={"*": BackfillSpec(strategy=BackfillStrategy.TIME_CURSOR, notes="n", supports_before=True)},
        backfill_page=page,
    )
    await service.backfill_page(FetchRequest(site="demo", path_type="hot"), before=until)
    assert seen["before"] == until


async def test_backfill_rejects_unsupported_and_unimplemented() -> None:
    service = _service(
        _handler,
        backfill={
            "*": BackfillSpec(strategy=BackfillStrategy.OPAQUE_CURSOR, notes="n"),
            "rank": unsupported("rank"),
        },
    )
    with pytest.raises(FetchBackfillUnsupportedError):
        await service.backfill_page(FetchRequest(site="demo", path_type="rank"))
    with pytest.raises(FetchBackfillUnsupportedError):
        await service.backfill_page(FetchRequest(site="demo", path_type="hot"))
    assert not service.backfill_implemented("demo", "hot")
    assert service.describe_backfill("demo", "rank").strategy is BackfillStrategy.UNSUPPORTED


async def test_backfill_rejects_undeclared_board_dimensions() -> None:
    service = _service(_handler, backfill={"*": snapshot("rss")})
    with pytest.raises(FetchInvalidRequestError):
        await service.backfill_page(
            FetchRequest(site="demo", path_type="hot", params={"cursor": "1"})
        )


async def test_snapshot_reuses_handle_route_without_cache(monkeypatch) -> None:
    seen: dict = {}

    async def handler(request, no_cache: bool = False):
        seen["no_cache"] = no_cache
        seen["bypass"] = http_client._cache_bypass_mode.get()
        return _flash_data(5_000)

    service = _service(handler, backfill={"*": snapshot("rss")})
    page = await service.backfill_page(FetchRequest(site="demo", path_type="hot"))
    assert seen == {"no_cache": True, "bypass": True}
    assert page.next_cursor is None and page.raw_digest
    assert service.backfill_implemented("demo", "hot")
    with pytest.raises(FetchInvalidRequestError):
        await service.backfill_page(FetchRequest(site="demo", path_type="hot"), cursor="x")


async def test_bypass_cache_neither_reads_nor_writes(monkeypatch) -> None:
    calls: list[str] = []

    class _Cache:
        async def get(self, key):
            calls.append("get")
            return None

        async def set(self, key, value, ttl):
            calls.append("set")

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class _Client:
        async def get(self, url, headers=None, params=None):
            return _Response()

    async def fake_client(url, proxy):
        return _Client()

    monkeypatch.setattr(http_client, "cache", _Cache())
    monkeypatch.setattr(http_client, "_get_client", fake_client)
    with http_client.bypass_cache():
        result = await http_client.get("https://example.com/api", params={"p": 2})
    assert result.data == {"ok": True} and calls == []
    await http_client.get("https://example.com/api", params={"p": 2})
    assert calls == ["get", "set"]

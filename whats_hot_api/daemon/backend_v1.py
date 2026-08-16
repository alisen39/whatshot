"""Public Core Backend implementation of WhatsHot HTTP Contract v1."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from itertools import product
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl
from uuid import uuid4

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from whats_hot_api._version import get_version
from whats_hot_api.fetch import (
    BOARD_KEY_VERSION,
    BoardIdentityError,
    CachePolicy,
    FetchCacheMissError,
    FetchError,
    FetchInvalidRequestError,
    FetchRequest,
    FetchResult,
    FetchSourceNotFoundError,
    FetchTypeNotFoundError,
    FetchUpstreamError,
    SourceDescriptor,
    canonical_board_key,
)
from whats_hot_api.history.errors import (
    HistoryCursorError,
    HistoryCursorExpiredError,
    HistoryDisabledError,
    HistoryError,
    HistoryQueryError,
    HistoryRangeError,
    HistoryUnavailableError,
)
from whats_hot_api.models import GoldItem, ListItem, NewsFlashItem
from whats_hot_api.scheduler.config import AppConfig

CONTRACT_VERSION = "1"
MAX_BATCH_TARGETS = 12
_KINDS = frozenset({"hotlist", "newsflash", "gold"})
ItemKind = Literal["hotlist", "newsflash", "gold"]
TrendBucket = Literal["10m", "1h", "6h", "1d"]


class Freshness(StrEnum):
    CACHE_ONLY = "cache_only"
    PREFER_CACHE = "prefer_cache"
    LIVE = "live"


class _ContractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CurrentRequestBody(_ContractRequest):
    site: Annotated[str, Field(min_length=1, max_length=120)]
    board_key: Annotated[
        str | None,
        Field(default=None, alias="boardKey", max_length=2048),
    ]
    freshness: Freshness = Freshness.PREFER_CACHE
    limit: Annotated[int, Field(ge=1, le=200)] = 50


class BatchCurrentTarget(_ContractRequest):
    site: Annotated[str, Field(min_length=1, max_length=120)]
    board_key: Annotated[
        str | None,
        Field(default=None, alias="boardKey", max_length=2048),
    ]


class BatchCurrentRequestBody(_ContractRequest):
    targets: Annotated[list[BatchCurrentTarget], Field(min_length=1, max_length=100)]
    freshness: Freshness = Freshness.PREFER_CACHE
    limit_per_board: Annotated[
        int,
        Field(default=50, alias="limitPerBoard", ge=1, le=200),
    ]


class BackendContractError(Exception):
    """Stable error emitted by the public Backend Contract router."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details


@dataclass(frozen=True, slots=True)
class BoardTarget:
    board_key: str
    title: str
    kind: str
    path_type: str
    params: dict[str, str]
    is_default: bool

    def as_descriptor(self) -> dict[str, Any]:
        return {
            "boardKey": self.board_key,
            "title": self.title,
            "kind": self.kind,
            "pathType": self.path_type,
            "params": self.params,
            "isDefault": self.is_default,
            "liveFetchSupported": True,
        }


def create_backend_v1_router(
    config: AppConfig,
    *,
    fetch_service: Any,
    history_service: Any,
) -> APIRouter:
    """Build the unauthenticated, read-only Core Contract v1 router."""

    router = APIRouter(prefix="/api/v1")
    batch_semaphore = asyncio.Semaphore(config.scheduler.max_fetch_concurrency)
    history_enabled = config.storage.enabled

    @router.get("/capabilities")
    async def capabilities(request: Request) -> dict[str, Any]:
        _reject_query_parameters(request)
        return _success(
            request,
            {
                "backend": {
                    "name": "whatshot-local",
                    "version": get_version(),
                },
                "boardKeyVersion": BOARD_KEY_VERSION,
                "profiles": [
                    "core-read",
                    *(["history-read"] if history_enabled else []),
                ],
                "features": {
                    "sources": True,
                    "sourceSchema": True,
                    "current": True,
                    "liveFetch": True,
                    "batchCurrent": True,
                    "history": history_enabled,
                    "historySearch": history_enabled,
                    "trendSeries": history_enabled,
                    "coverage": history_enabled,
                    "navigation": False,
                    "semanticSearch": False,
                    "kinds": sorted(_KINDS),
                },
                "limits": {
                    "maxResultItems": config.backend_api.max_result_items,
                    "maxBatchTargets": MAX_BATCH_TARGETS,
                    "defaultHistoryDays": config.backend_api.default_history_days,
                    "maxHistoryDays": config.backend_api.max_history_days,
                },
            },
        )

    @router.get("/sources")
    async def list_sources(
        request: Request,
        kind: ItemKind | None = None,
        cursor: str | None = None,
        limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        _reject_query_parameters(request, allowed={"kind", "cursor", "limit"})
        if kind is not None and kind not in _KINDS:
            raise BackendContractError(
                "INVALID_ARGUMENT",
                "Invalid source kind.",
                status_code=400,
                details={"kind": kind},
            )

        descriptors = sorted(fetch_service.list_sources(), key=lambda row: row.name)
        if kind is not None:
            descriptors = [row for row in descriptors if row.category == kind]
        offset = _decode_source_cursor(cursor, kind=kind)
        if offset > len(descriptors):
            raise BackendContractError(
                "INVALID_CURSOR",
                "Source cursor is out of range.",
                status_code=400,
            )

        page = descriptors[offset : offset + limit]
        next_offset = offset + len(page)
        truncated = next_offset < len(descriptors)
        return _success(
            request,
            {
                "sources": [
                    _source_summary(row, history_enabled=history_enabled)
                    for row in page
                ],
                "nextCursor": (
                    _encode_source_cursor(next_offset, kind=kind) if truncated else None
                ),
                "truncated": truncated,
            },
        )

    @router.get("/sources/{site}")
    async def get_source(request: Request, site: str) -> dict[str, Any]:
        _reject_query_parameters(request)
        descriptor = _describe_source(fetch_service, site)
        return _success(request, _source_detail(descriptor))

    @router.post("/current")
    async def current(
        request: Request,
        body: CurrentRequestBody,
    ) -> dict[str, Any]:
        _reject_query_parameters(request)
        _validate_result_limit(body.limit, config=config)
        data = await _fetch_current(
            fetch_service,
            site=body.site,
            board_key=body.board_key,
            freshness=body.freshness,
            limit=body.limit,
        )
        return _success(request, data)

    @router.post("/current/batch")
    async def current_batch(
        request: Request,
        body: BatchCurrentRequestBody,
    ) -> dict[str, Any]:
        _reject_query_parameters(request)
        _validate_result_limit(body.limit_per_board, config=config)
        if len(body.targets) > MAX_BATCH_TARGETS:
            raise BackendContractError(
                "INVALID_ARGUMENT",
                f"A batch may contain at most {MAX_BATCH_TARGETS} targets.",
                status_code=400,
                details={"maxBatchTargets": MAX_BATCH_TARGETS},
            )

        async def fetch_target(target: BatchCurrentTarget) -> dict[str, Any]:
            async with batch_semaphore:
                return await _fetch_current(
                    fetch_service,
                    site=target.site,
                    board_key=target.board_key,
                    freshness=body.freshness,
                    limit=body.limit_per_board,
                )

        settled = await asyncio.gather(
            *(fetch_target(target) for target in body.targets),
            return_exceptions=True,
        )
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for target, outcome in zip(body.targets, settled, strict=True):
            if isinstance(outcome, Exception):
                error = _as_contract_error(outcome)
                errors.append(
                    {
                        "site": target.site,
                        "boardKey": target.board_key,
                        "code": error.code,
                        "message": error.message,
                        "retryable": error.retryable,
                    }
                )
            else:
                results.append(outcome)
        return _success(
            request,
            {"results": results, "errors": errors, "truncated": False},
        )

    @router.get("/history")
    async def query_history(
        request: Request,
        site: Annotated[
            str | None,
            Query(min_length=1, max_length=120),
        ] = None,
        board_key: Annotated[
            str | None,
            Query(alias="boardKey", min_length=1, max_length=2048),
        ] = None,
        kind: ItemKind | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = Query(50, ge=1, le=200),
        cursor: Annotated[str | None, Query(min_length=1, max_length=4096)] = None,
    ) -> dict[str, Any]:
        _reject_query_parameters(
            request,
            allowed={"site", "boardKey", "kind", "since", "until", "limit", "cursor"},
        )
        _validate_result_limit(limit, config=config)
        resolved_board_key, _target = _resolve_history_target(
            fetch_service,
            site=site,
            board_key=board_key,
        )
        data = await _history_call(
            history_service,
            "query_history",
            site=site,
            board_key=resolved_board_key,
            kind=kind,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )
        return _success(request, data)

    @router.get("/history/search")
    async def search_history(
        request: Request,
        keyword: Annotated[str, Query(min_length=1, max_length=500)],
        site: Annotated[
            str | None,
            Query(min_length=1, max_length=120),
        ] = None,
        board_key: Annotated[
            str | None,
            Query(alias="boardKey", min_length=1, max_length=2048),
        ] = None,
        kind: ItemKind | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = Query(50, ge=1, le=200),
        cursor: Annotated[str | None, Query(min_length=1, max_length=4096)] = None,
    ) -> dict[str, Any]:
        _reject_query_parameters(
            request,
            allowed={
                "keyword",
                "site",
                "boardKey",
                "kind",
                "since",
                "until",
                "limit",
                "cursor",
            },
        )
        _validate_result_limit(limit, config=config)
        resolved_board_key, _target = _resolve_history_target(
            fetch_service,
            site=site,
            board_key=board_key,
        )
        data = await _history_call(
            history_service,
            "search_history",
            keyword,
            site=site,
            board_key=resolved_board_key,
            kind=kind,
            since=since,
            until=until,
            limit=limit,
            cursor=cursor,
        )
        return _success(request, data)

    @router.get("/history/trends")
    async def trend_history(
        request: Request,
        site: Annotated[str, Query(min_length=1, max_length=120)],
        board_key: Annotated[
            str,
            Query(alias="boardKey", min_length=1, max_length=2048),
        ],
        item_id: Annotated[
            str,
            Query(alias="itemId", min_length=1, max_length=2048),
        ],
        bucket: TrendBucket = "1h",
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        _reject_query_parameters(
            request,
            allowed={"site", "boardKey", "itemId", "bucket", "since", "until"},
        )
        resolved_board_key, target = _resolve_history_target(
            fetch_service,
            site=site,
            board_key=board_key,
        )
        assert resolved_board_key is not None and target is not None
        if target.kind == "newsflash":
            raise BackendContractError(
                "CAPABILITY_UNAVAILABLE",
                "Trend series are unavailable for newsflash boards.",
                status_code=503,
            )
        data = await _history_call(
            history_service,
            "get_trend_series",
            site=site,
            board_key=resolved_board_key,
            item_id=item_id,
            bucket=bucket,
            since=since,
            until=until,
        )
        return _success(request, data)

    @router.get("/coverage")
    async def data_coverage(
        request: Request,
        site: Annotated[
            str | None,
            Query(min_length=1, max_length=120),
        ] = None,
        board_key: Annotated[
            str | None,
            Query(alias="boardKey", min_length=1, max_length=2048),
        ] = None,
        kind: ItemKind | None = None,
    ) -> dict[str, Any]:
        _reject_query_parameters(
            request,
            allowed={"site", "boardKey", "kind"},
        )
        resolved_board_key, _target = _resolve_history_target(
            fetch_service,
            site=site,
            board_key=board_key,
        )
        data = await _history_call(
            history_service,
            "get_data_coverage",
            site=site,
            board_key=resolved_board_key,
            kind=kind,
        )
        return _success(request, data)

    return router


async def _history_call(
    history_service: Any,
    method: str,
    *args: Any,
    **kwargs: Any,
) -> Any:
    try:
        return await history_service.call(method, *args, **kwargs)
    except Exception as exc:
        raise _as_contract_error(exc) from exc


async def _fetch_current(
    fetch_service: Any,
    *,
    site: str,
    board_key: str | None,
    freshness: Freshness,
    limit: int,
) -> dict[str, Any]:
    descriptor = _describe_source(fetch_service, site)
    target = _resolve_board(descriptor, board_key)
    cache_policy = {
        Freshness.CACHE_ONLY: CachePolicy.ONLY,
        Freshness.PREFER_CACHE: CachePolicy.PREFER,
        Freshness.LIVE: CachePolicy.REFRESH,
    }[freshness]
    try:
        result = await fetch_service.fetch(
            FetchRequest(
                site=site,
                path_type=target.path_type,
                params=target.params,
                limit=limit,
                cache_policy=cache_policy,
            )
        )
        return _current_data(result, board_key=target.board_key)
    except Exception as exc:
        raise _as_contract_error(exc) from exc


def _describe_source(fetch_service: Any, site: str) -> SourceDescriptor:
    try:
        return fetch_service.describe_source(site)
    except FetchSourceNotFoundError as exc:
        raise BackendContractError(
            "UNKNOWN_SOURCE",
            "Unknown source.",
            status_code=404,
            details={"site": site},
        ) from exc


def _source_summary(
    descriptor: SourceDescriptor,
    *,
    history_enabled: bool,
) -> dict[str, Any]:
    capabilities = {"current", "liveFetch"}
    if history_enabled:
        capabilities.update({"history", "historySearch"})
        if descriptor.category != "newsflash":
            capabilities.add("trendSeries")
    return {
        "site": descriptor.name,
        "title": descriptor.title,
        "description": descriptor.description,
        "kinds": [descriptor.category],
        "boardCount": len(_boards_for(descriptor)),
        "enabled": True,
        "capabilities": sorted(capabilities),
    }


def _source_detail(descriptor: SourceDescriptor) -> dict[str, Any]:
    return {
        "site": descriptor.name,
        "title": descriptor.title,
        "description": descriptor.description,
        "kinds": [descriptor.category],
        "dimensions": _source_dimensions(descriptor),
        "boards": [board.as_descriptor() for board in _boards_for(descriptor)],
    }


def _source_dimensions(descriptor: SourceDescriptor) -> list[dict[str, Any]]:
    dimensions: list[dict[str, Any]] = []
    for key, metadata in (descriptor.params or {}).items():
        choices = _dimension_choices(metadata)
        label: str | None = None
        if isinstance(metadata, str):
            label = metadata
        elif isinstance(metadata, Mapping) and metadata.get("name") is not None:
            label = str(metadata["name"])
        dimensions.append(
            {
                "key": key,
                "label": label,
                "location": "path" if key == "type" else "query",
                "dynamic": not bool(choices),
                "options": [
                    {"value": value, "label": choice_label}
                    for value, choice_label in choices
                ],
            }
        )
    return dimensions


def _boards_for(descriptor: SourceDescriptor) -> tuple[BoardTarget, ...]:
    declared = descriptor.params or {}
    dimensions: list[tuple[str, list[tuple[str, str]]]] = []
    ordered_names = sorted(declared, key=lambda name: (name != "type", name))
    for name in ordered_names:
        choices = _dimension_choices(declared[name])
        if choices:
            dimensions.append((name, choices))

    if not dimensions:
        return (
            BoardTarget(
                board_key="hot",
                title=descriptor.title,
                kind=descriptor.category,
                path_type=descriptor.default_type,
                params={},
                is_default=True,
            ),
        )

    values = [choices for _, choices in dimensions]
    boards: list[BoardTarget] = []
    for index, combination in enumerate(product(*values)):
        selected = {
            name: choice[0]
            for (name, _choices), choice in zip(dimensions, combination, strict=True)
        }
        labels = [choice[1] for choice in combination]
        path_type = selected.pop("type", descriptor.default_type)
        boards.append(
            BoardTarget(
                board_key=canonical_board_key(
                    path_type=path_type,
                    params=selected,
                    declared_dimensions=declared.keys(),
                ),
                title=" · ".join(labels)[:200] or descriptor.title,
                kind=descriptor.category,
                path_type=path_type,
                params=selected,
                is_default=index == 0,
            )
        )
    return tuple(boards)


def _dimension_choices(metadata: Any) -> list[tuple[str, str]]:
    if not isinstance(metadata, Mapping):
        return []
    choices = metadata.get("type")
    if isinstance(choices, Mapping):
        return [(str(value), str(label)) for value, label in choices.items()]
    if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes)):
        return [(str(value), str(value)) for value in choices]
    return []


def _resolve_board(
    descriptor: SourceDescriptor,
    requested_key: str | None,
) -> BoardTarget:
    boards = _boards_for(descriptor)
    if requested_key is None:
        return next(board for board in boards if board.is_default)
    for board in boards:
        if board.board_key == requested_key:
            return board

    dynamic = _dynamic_board(descriptor, requested_key)
    if dynamic is not None:
        return dynamic
    raise BackendContractError(
        "UNKNOWN_BOARD",
        "Unknown board.",
        status_code=404,
        details={"site": descriptor.name, "boardKey": requested_key},
    )


def _resolve_history_target(
    fetch_service: Any,
    *,
    site: str | None,
    board_key: str | None,
) -> tuple[str | None, BoardTarget | None]:
    """Validate Contract history identity without coupling storage to routes.

    Every value must be canonical boardKey v1. When a site is present,
    its current source schema is also the authority for whether that board is
    known.  A site-less board filter is accepted only when at least one current
    source declares the same finite or dynamic board identity.
    """

    descriptor = _describe_source(fetch_service, site) if site is not None else None
    if board_key is None:
        return None, None

    canonical = _canonical_history_board_key(board_key)
    candidates = (
        (descriptor,) if descriptor is not None else tuple(fetch_service.list_sources())
    )
    for candidate in candidates:
        try:
            target = _resolve_board(candidate, canonical)
        except BackendContractError as exc:
            if exc.code != "UNKNOWN_BOARD":
                raise
            continue
        return target.board_key, target

    raise BackendContractError(
        "UNKNOWN_BOARD",
        "Unknown board.",
        status_code=404,
        details={"site": site, "boardKey": board_key},
    )


def _canonical_history_board_key(board_key: str) -> str:
    if board_key == "hot":
        return board_key
    try:
        pairs = parse_qsl(
            board_key,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
        )
        if not pairs or len({key for key, _value in pairs}) != len(pairs):
            raise ValueError
        values = dict(pairs)
        has_type = "type" in values
        path_type = values.pop("type", "hot")
        declared_dimensions = {*values}
        if has_type:
            declared_dimensions.add("type")
        canonical = canonical_board_key(
            path_type=path_type,
            params=values,
            declared_dimensions=declared_dimensions,
        )
    except (BoardIdentityError, UnicodeDecodeError, ValueError):
        canonical = ""
    if canonical != board_key:
        raise BackendContractError(
            "UNKNOWN_BOARD",
            "Unknown board.",
            status_code=404,
            details={"boardKey": board_key},
        )
    return canonical


def _dynamic_board(
    descriptor: SourceDescriptor,
    board_key: str,
) -> BoardTarget | None:
    declared = descriptor.params or {}
    dynamic_dimensions = {
        name for name, metadata in declared.items() if not _dimension_choices(metadata)
    }
    if not dynamic_dimensions or board_key == "hot":
        return None
    try:
        pairs = parse_qsl(
            board_key,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
        )
    except (UnicodeDecodeError, ValueError):
        return None
    if not pairs or len({key for key, _value in pairs}) != len(pairs):
        return None
    raw = dict(pairs)
    has_type = "type" in raw
    path_type = raw.pop("type", descriptor.default_type)
    required_params = set(declared) - {"type"}
    if set(raw) != required_params:
        return None
    if "type" in declared and not has_type:
        return None
    if descriptor.validate_type and path_type not in descriptor.types:
        return None
    for name, value in raw.items():
        choices = _dimension_choices(declared[name])
        if choices and value not in {choice for choice, _label in choices}:
            return None
    try:
        canonical = canonical_board_key(
            path_type=path_type,
            params=raw,
            declared_dimensions=declared.keys(),
        )
    except ValueError:
        return None
    if canonical != board_key:
        return None
    return BoardTarget(
        board_key=canonical,
        title=" · ".join(raw[name] for name in sorted(raw))[:200],
        kind=descriptor.category,
        path_type=path_type,
        params=raw,
        is_default=False,
    )


def _current_data(result: FetchResult, *, board_key: str) -> dict[str, Any]:
    return {
        "site": result.request.site,
        "boardKey": board_key,
        "kind": result.data.kind,
        "title": result.data.title,
        "type": result.data.type,
        "updateTime": _iso_datetime(result.data.updateTime),
        "observedAt": _iso_datetime(result.observed_at),
        "sourceMode": "memory_cache" if result.from_cache else "live",
        "items": [
            _current_item(item, rank=rank, board_key=board_key)
            for rank, item in enumerate(result.data.data, start=1)
        ],
    }


def _current_item(
    item: ListItem | NewsFlashItem | GoldItem,
    *,
    rank: int,
    board_key: str,
) -> dict[str, Any]:
    if not item.id or not item.title:
        raise BackendContractError(
            "UPSTREAM_UNAVAILABLE",
            "The upstream source returned an invalid item.",
            status_code=503,
            retryable=True,
        )
    extra: dict[str, Any] = {}
    description: str | None
    hot: int | float | str | None = None
    if isinstance(item, NewsFlashItem):
        description = item.summary or item.content
        extra = {
            "content": item.content,
            "contentStatus": item.contentStatus,
            "source": item.source,
            "isImportant": item.isImportant,
            "tags": item.tags,
            "images": item.images,
            "symbols": item.symbols,
            "metrics": item.metrics,
        }
    elif isinstance(item, GoldItem):
        description = item.desc
        extra = {
            "metal": item.metal,
            "quotes": [
                {
                    **quote.model_dump(),
                    "seriesKey": (
                        f"{board_key}:{item.id}:{quote.quoteType}:"
                        f"{quote.currency}:{quote.unit}"
                    ),
                }
                for quote in item.quotes
            ],
            "sellPrice": item.sellPrice,
            "recyclePrice": item.recyclePrice,
        }
    else:
        description = item.desc
        hot = item.hot
        extra = {"cover": item.cover, "author": item.author}
    extra = {key: value for key, value in extra.items() if value is not None}
    return {
        "itemId": item.id,
        "rank": rank,
        "title": item.title,
        "url": item.url,
        "mobileUrl": item.mobileUrl,
        "hot": hot,
        "description": description,
        "publishedAt": _timestamp_iso(item.timestamp),
        "extra": extra,
    }


def _timestamp_iso(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, UTC).isoformat()


def _iso_datetime(value: datetime | str) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()


def _validate_result_limit(limit: int, *, config: AppConfig) -> None:
    if limit > config.backend_api.max_result_items:
        raise BackendContractError(
            "INVALID_ARGUMENT",
            "Requested result limit exceeds Backend capability.",
            status_code=400,
            details={"maxResultItems": config.backend_api.max_result_items},
        )


def _reject_query_parameters(
    request: Request,
    *,
    allowed: set[str] | None = None,
) -> None:
    unknown = set(request.query_params) - (allowed or set())
    if unknown:
        raise BackendContractError(
            "INVALID_ARGUMENT",
            "Unknown query parameter.",
            status_code=400,
            details={"parameters": sorted(unknown)},
        )
    duplicates = sorted(
        name
        for name in request.query_params
        if len(request.query_params.getlist(name)) > 1
    )
    if duplicates:
        raise BackendContractError(
            "INVALID_ARGUMENT",
            "Query parameters must not be repeated.",
            status_code=400,
            details={"parameters": duplicates},
        )


def _as_contract_error(exc: Exception) -> BackendContractError:
    if isinstance(exc, BackendContractError):
        return exc
    if isinstance(exc, HistoryCursorExpiredError):
        return BackendContractError(
            "CURSOR_EXPIRED",
            "History cursor has expired.",
            status_code=409,
        )
    if isinstance(exc, HistoryCursorError):
        return BackendContractError(
            "INVALID_CURSOR",
            "Invalid history cursor.",
            status_code=400,
        )
    if isinstance(exc, (HistoryDisabledError, HistoryUnavailableError)):
        return BackendContractError(
            "CAPABILITY_UNAVAILABLE",
            "History capability is unavailable.",
            status_code=503,
        )
    if isinstance(exc, HistoryRangeError):
        return BackendContractError(
            "INVALID_ARGUMENT",
            exc.message,
            status_code=400,
        )
    if isinstance(exc, HistoryQueryError):
        return BackendContractError(
            "INVALID_ARGUMENT",
            exc.message,
            status_code=400,
        )
    if isinstance(exc, HistoryError):
        return BackendContractError(
            "INTERNAL_ERROR",
            "History query failed.",
            status_code=500,
        )
    if isinstance(exc, FetchSourceNotFoundError):
        return BackendContractError(
            "UNKNOWN_SOURCE",
            "Unknown source.",
            status_code=404,
            details=exc.details,
        )
    if isinstance(exc, FetchTypeNotFoundError):
        return BackendContractError(
            "UNKNOWN_BOARD",
            "Unknown board.",
            status_code=404,
            details=exc.details,
        )
    if isinstance(exc, FetchInvalidRequestError):
        return BackendContractError(
            "INVALID_ARGUMENT",
            exc.message,
            status_code=400,
            details=exc.details,
        )
    if isinstance(exc, FetchCacheMissError):
        return BackendContractError(
            "CAPABILITY_UNAVAILABLE",
            "No cached value is available for this board.",
            status_code=503,
            details=exc.details,
        )
    if isinstance(exc, FetchUpstreamError):
        return BackendContractError(
            "UPSTREAM_UNAVAILABLE",
            "The upstream source is unavailable.",
            status_code=503,
            retryable=True,
            details=exc.details,
        )
    if isinstance(exc, FetchError):
        return BackendContractError(
            "INTERNAL_ERROR",
            "The Backend could not complete the request.",
            status_code=500,
            retryable=exc.retryable,
        )
    return BackendContractError(
        "INTERNAL_ERROR",
        "The Backend could not complete the request.",
        status_code=500,
    )


def error_envelope(request: Request, error: BackendContractError) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "code": error.code,
        "message": error.message,
        "retryable": error.retryable,
        "details": error.details,
    }
    return {"error": detail, "meta": _response_meta(request)}


def _success(request: Request, data: Any) -> dict[str, Any]:
    return {"data": data, "meta": _response_meta(request)}


def _response_meta(request: Request) -> dict[str, Any]:
    candidate = request.headers.get("x-request-id", "")
    request_id = candidate if 1 <= len(candidate) <= 128 else uuid4().hex
    return {
        "requestId": request_id,
        "contractVersion": CONTRACT_VERSION,
        "generatedAt": datetime.now(UTC).isoformat(),
    }


def _encode_source_cursor(offset: int, *, kind: str | None) -> str:
    raw = json.dumps(
        {"v": 1, "offset": offset, "kind": kind},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _decode_source_cursor(cursor: str | None, *, kind: str | None) -> int:
    if cursor is None:
        return 0
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        payload = json.loads(raw)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"v", "offset", "kind"}
            or payload.get("v") != 1
            or payload.get("kind") != kind
            or not isinstance(payload.get("offset"), int)
            or isinstance(payload["offset"], bool)
            or payload["offset"] < 0
        ):
            raise ValueError
        return payload["offset"]
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise BackendContractError(
            "INVALID_CURSOR",
            "Invalid source cursor.",
            status_code=400,
        ) from None

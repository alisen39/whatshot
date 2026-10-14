"""Single route execution path used by HTTP, CLI, Scheduler, and Backend APIs."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from starlette.requests import Request

from whats_hot_api.backfill import (
    PAGED_STRATEGIES,
    BackfillPage,
    BackfillSpec,
    BackfillStrategy,
    payload_digest,
    resolve_spec,
)
from whats_hot_api.catalog import RouteCatalog, RouteSpec, route_catalog
from whats_hot_api.fetch.errors import (
    FetchBackfillUnsupportedError,
    FetchCacheMissError,
    FetchError,
    FetchInvalidRequestError,
    FetchSourceNotFoundError,
    FetchTypeNotFoundError,
    FetchUpstreamError,
)
from whats_hot_api.fetch.identity import BoardIdentityError, canonical_board_key
from whats_hot_api.fetch.models import (
    CachePolicy,
    FetchRequest,
    FetchResult,
    SourceDescriptor,
)
from whats_hot_api.models import RouterData
from whats_hot_api.utils.http_client import (
    CacheOnlyMiss,
    bypass_cache,
    force_cache_only,
)

DEFAULT_PATH_TYPE = "hot"


def _ordered_path_types(metadata: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not metadata:
        return (DEFAULT_PATH_TYPE,)
    params = metadata.get("params") or {}
    type_param = params.get("type") if isinstance(params, Mapping) else None
    if isinstance(type_param, Mapping):
        type_options = type_param.get("type")
        if isinstance(type_options, Mapping):
            values = tuple(str(value) for value in type_options)
            return values or (DEFAULT_PATH_TYPE,)
        if isinstance(type_options, (list, tuple)):
            values = tuple(str(value) for value in type_options)
            return values or (DEFAULT_PATH_TYPE,)
    return (DEFAULT_PATH_TYPE,)


def _request_for(fetch_request: FetchRequest) -> Request:
    query_items = [("type", fetch_request.path_type)]
    query_items.extend(
        (str(key), str(value))
        for key, value in fetch_request.params.items()
        if key != "type"
    )
    path = f"/{fetch_request.site}/{fetch_request.path_type}"
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": urlencode(query_items).encode(),
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("whatshot.local", 80),
    }
    return Request(scope)


class FetchService:
    """Validate, execute, and normalize one Core route fetch."""

    def __init__(self, routes: RouteCatalog | None = None) -> None:
        self._routes = routes or route_catalog

    def list_sources(self) -> tuple[SourceDescriptor, ...]:
        return tuple(self._describe(spec) for spec in self._routes.specs())

    def describe_source(self, site: str) -> SourceDescriptor:
        return self._describe(self._get_spec(site))

    async def fetch(self, request: FetchRequest) -> FetchResult:
        spec, _descriptor = self._resolve_board(request)
        no_cache = request.cache_policy is CachePolicy.REFRESH
        cache_context = (
            force_cache_only()
            if request.cache_policy is CachePolicy.ONLY
            else nullcontext()
        )
        try:
            with cache_context:
                route_data = await spec.handle_route(
                    _request_for(request),
                    no_cache,
                )
        except CacheOnlyMiss as exc:
            raise FetchCacheMissError(
                "No cached data available for this source.",
                details={
                    "site": request.site,
                    "pathType": request.path_type,
                },
            ) from exc
        except FetchError:
            raise
        except Exception as exc:
            raise FetchUpstreamError(
                f"Source '{request.site}' failed.",
                details={
                    "site": request.site,
                    "pathType": request.path_type,
                },
            ) from exc

        route_data = self._checked_route_data(request, route_data)
        observed_at = datetime.now(UTC)
        if not route_data.fromCache:
            route_data = route_data.model_copy(
                update={"updateTime": observed_at.isoformat()}
            )

        if request.limit is not None and len(route_data.data) > request.limit:
            route_data = route_data.model_copy(
                update={
                    "total": request.limit,
                    "data": route_data.data[: request.limit],
                }
            )

        return FetchResult(
            request=request,
            data=route_data,
            observed_at=observed_at,
        )

    def describe_backfill(self, site: str, path_type: str) -> BackfillSpec | None:
        """Declared backfill capability for one route type (None = undeclared)."""
        return resolve_spec(self._get_spec(site).backfill, path_type)

    def backfill_implemented(self, site: str, path_type: str) -> bool:
        spec = self._get_spec(site)
        declared = resolve_spec(spec.backfill, path_type)
        if declared is None:
            return False
        if declared.strategy is BackfillStrategy.SNAPSHOT:
            return True
        return declared.strategy in PAGED_STRATEGIES and spec.backfill_page is not None

    async def backfill_page(
        self,
        request: FetchRequest,
        cursor: str | None = None,
        before: datetime | None = None,
    ) -> BackfillPage:
        """Fetch one historical page without touching any response cache.

        The cursor is not a board dimension, so board identity is validated
        exactly like ``fetch`` and the cursor never reaches ``board_key``.
        """
        spec, _descriptor = self._resolve_board(request)
        declared = resolve_spec(spec.backfill, request.path_type)
        details = {"site": request.site, "pathType": request.path_type}
        if declared is None or declared.strategy is BackfillStrategy.UNSUPPORTED:
            raise FetchBackfillUnsupportedError(
                f"Source '{request.site}' does not support backfill.",
                details={**details, "notes": declared.notes if declared else None},
            )
        try:
            with bypass_cache():
                if declared.strategy is BackfillStrategy.SNAPSHOT:
                    if cursor:
                        raise FetchInvalidRequestError(
                            "Snapshot sources have a single page.", details=details
                        )
                    route_data = await spec.handle_route(_request_for(request), True)
                    page = BackfillPage(
                        data=route_data,
                        next_cursor=None,
                        raw_digest=payload_digest(
                            [item.model_dump() for item in route_data.data]
                        )
                        if isinstance(route_data, RouterData)
                        else None,
                    )
                else:
                    if spec.backfill_page is None:
                        raise FetchBackfillUnsupportedError(
                            f"Backfill for '{request.site}' is declared but not implemented.",
                            details={**details, "strategy": declared.strategy.value},
                        )
                    params = {
                        str(key): str(value)
                        for key, value in request.params.items()
                        if key != "type"
                    }
                    page = await spec.backfill_page(
                        request.path_type,
                        params,
                        cursor,
                        before=before if declared.supports_before else None,
                    )
        except FetchError:
            raise
        except Exception as exc:
            raise FetchUpstreamError(
                f"Source '{request.site}' backfill page failed.",
                details={**details, "cursor": cursor, "error": type(exc).__name__},
            ) from exc
        if not isinstance(page, BackfillPage):
            raise FetchUpstreamError(
                f"Source '{request.site}' returned an invalid backfill page.",
                details=details,
            )
        data = self._checked_route_data(request, page.data)
        return BackfillPage(data=data, next_cursor=page.next_cursor, raw_digest=page.raw_digest)

    def _resolve_board(self, request: FetchRequest) -> tuple[RouteSpec, SourceDescriptor]:
        self._validate_request(request)
        spec = self._get_spec(request.site)
        descriptor = self._describe(spec)
        if descriptor.validate_type and request.path_type not in descriptor.types:
            raise FetchTypeNotFoundError(
                (f"Unknown type '{request.path_type}' for source '{request.site}'."),
                details={
                    "site": request.site,
                    "pathType": request.path_type,
                    "validTypes": list(descriptor.types),
                },
            )
        try:
            canonical_board_key(
                path_type=request.path_type,
                params=request.params,
                declared_dimensions=(descriptor.params or {}).keys(),
            )
        except BoardIdentityError as exc:
            raise FetchInvalidRequestError(
                str(exc),
                details={
                    "site": request.site,
                    "declaredDimensions": list((descriptor.params or {}).keys()),
                },
            ) from exc

        return spec, descriptor

    @staticmethod
    def _checked_route_data(request: FetchRequest, route_data: object) -> RouterData:
        if not isinstance(route_data, RouterData):
            raise FetchUpstreamError(
                f"Source '{request.site}' returned invalid data.",
                details={
                    "site": request.site,
                    "pathType": request.path_type,
                },
            )
        return route_data

    def _get_spec(self, site: str) -> RouteSpec:
        spec = self._routes.get(site)
        if spec is None:
            raise FetchSourceNotFoundError(
                f"Unknown source '{site}'.",
                details={"site": site},
            )
        return spec

    @staticmethod
    def _describe(spec: RouteSpec) -> SourceDescriptor:
        metadata = spec.metadata or {}
        types = _ordered_path_types(metadata)
        raw_params = metadata.get("params")
        params = dict(raw_params) if isinstance(raw_params, Mapping) else None
        return SourceDescriptor(
            name=spec.name,
            title=str(metadata.get("title") or spec.name),
            description=(
                str(metadata["description"])
                if metadata.get("description") is not None
                else None
            ),
            link=str(metadata["link"]) if metadata.get("link") is not None else None,
            category=spec.category,
            category_label=spec.category_label,
            params=params,
            types=types,
            default_type=types[0],
            validate_type=spec.validate_type,
            data_path=f"/{spec.name}/{{type}}",
        )

    @staticmethod
    def _validate_request(request: FetchRequest) -> None:
        if not request.site or not request.site.strip():
            raise FetchInvalidRequestError("site must not be empty")
        if not request.path_type or not request.path_type.strip():
            raise FetchInvalidRequestError("path_type must not be empty")
        if request.limit is not None and not 1 <= request.limit <= 200:
            raise FetchInvalidRequestError(
                "limit must be between 1 and 200",
                details={"limit": request.limit},
            )

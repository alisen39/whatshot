from __future__ import annotations

import importlib
import pkgutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from whats_hot_api.catalog import route_catalog
from whats_hot_api.config import config
from whats_hot_api.fetch import CachePolicy, FetchError, FetchRequest, FetchService
from whats_hot_api.utils.get_rss import get_rss
from whats_hot_api.utils.logger import logger

DEFAULT_PATH_TYPE = "hot"

router = APIRouter()


@dataclass(frozen=True, slots=True)
class RouteHandlerInfo:
    handle_route: Callable
    category: str
    category_label: str
    metadata: dict[str, Any] | None = None
    validate_type: bool = True


# Store all registered routes with category metadata
all_routes: list[dict[str, str]] = []

# Map route_name -> handler info for scheduler access
route_handlers: dict[str, RouteHandlerInfo] = {}
route_catalog.bind(route_handlers)
fetch_service = FetchService(route_catalog)

# Cached categories response (built once after discovery)
_categories_cache: list[dict[str, Any]] | None = None

# Track registered route names to avoid duplicates
_registered_names: set[str] = set()

# Track successfully scanned packages so repeated app/CLI bootstrap is cheap.
_scanned_packages: set[str] = set()


def discover_and_register_routes(
    extra_packages: list[str] | None = None,
) -> None:
    """Recursively discover route modules inside category sub-packages.

    Scans the built-in ``whats_hot_api.routes`` package first, then any
    additional packages listed in *extra_packages*.  Each extra package
    follows the same convention: sub-packages with ``CATEGORY`` /
    ``CATEGORY_LABEL`` attributes, containing modules with ``ROUTE_NAME``
    and ``handle_route``.
    """
    import whats_hot_api.routes as routes_pkg

    packages_to_scan: list[tuple[str, Any]] = [
        ("whats_hot_api.routes", routes_pkg),
    ]

    for pkg_path in extra_packages or []:
        try:
            pkg = importlib.import_module(pkg_path)
            packages_to_scan.append((pkg_path, pkg))
        except Exception as e:  # noqa: BLE001 - isolate optional route packages
            logger.error(f"❌ Failed to import extra package {pkg_path}: {e}")

    for base_path, base_pkg in packages_to_scan:
        if base_path in _scanned_packages:
            continue
        _scan_package(base_path, base_pkg)
        _scanned_packages.add(base_path)

    _build_categories_cache()


def _scan_package(base_path: str, base_pkg: Any) -> None:
    """Scan a single top-level routes package for category sub-packages."""
    for _importer, pkg_name, is_pkg in pkgutil.iter_modules(base_pkg.__path__):
        if pkg_name.startswith("_") or not is_pkg:
            continue
        try:
            sub_pkg = importlib.import_module(f"{base_path}.{pkg_name}")
        except Exception as e:  # noqa: BLE001 - isolate one category package
            logger.error(f"❌ Failed to load sub-package {pkg_name}: {e}")
            continue

        category = str(getattr(sub_pkg, "CATEGORY", pkg_name))
        category_label = str(getattr(sub_pkg, "CATEGORY_LABEL", pkg_name))

        for _, modname, mod_is_pkg in pkgutil.iter_modules(sub_pkg.__path__):
            if modname.startswith("_") or mod_is_pkg:
                continue
            try:
                module = importlib.import_module(f"{base_path}.{pkg_name}.{modname}")
                route_name = getattr(module, "ROUTE_NAME", modname.replace("_", "-"))
                handle_route = getattr(module, "handle_route", None)
                if handle_route is None:
                    logger.warning(
                        f"⚠️ Route module {pkg_name}.{modname} has no handle_route"
                    )
                    continue

                if route_name in _registered_names:
                    logger.warning(
                        f"⚠️ Duplicate route name '{route_name}' in {base_path}.{pkg_name}.{modname}, skipping"
                    )
                    continue

                _register_route(
                    route_name,
                    handle_route,
                    category=category,
                    category_label=category_label,
                )
                _registered_names.add(route_name)
                all_routes.append(
                    {
                        "name": route_name,
                        "path": f"/{route_name}",
                        "dataPath": f"/{route_name}/{{type}}",
                        "category": category,
                        "category_label": category_label,
                    }
                )
                logger.trace(f"📝 Registered route: /{route_name} [{category_label}]")
            except Exception as e:  # noqa: BLE001 - isolate one route module
                logger.error(f"❌ Failed to load route {pkg_name}.{modname}: {e}")


def _build_categories_cache() -> None:
    global _categories_cache
    categories: dict[str, dict[str, Any]] = {}
    for route in all_routes:
        cat = route["category"]
        if cat not in categories:
            categories[cat] = {
                "category": cat,
                "category_label": route["category_label"],
                "count": 0,
                "routes": [],
            }
        categories[cat]["count"] += 1
        categories[cat]["routes"].append(
            {
                "name": route["name"],
                "path": route["path"],
                "dataPath": route.get("dataPath", f"/{route['name']}/{{type}}"),
            }
        )
    _categories_cache = list(categories.values())


def _get_route_meta(handle_route: Any) -> dict | None:
    """Return the route module's ``ROUTE_META`` constant, or None (e.g. test fixtures)."""
    module = sys.modules.get(getattr(handle_route, "__module__", ""))
    return getattr(module, "ROUTE_META", None) if module is not None else None


def _ordered_path_types(meta: dict | None) -> list[str]:
    """Ordered list of valid path ``type`` values; ``['hot']`` when no ``type`` param."""
    if not meta:
        return [DEFAULT_PATH_TYPE]
    params = meta.get("params") or {}
    type_param = params.get("type")
    if isinstance(type_param, dict):
        type_options = type_param.get("type")
        if isinstance(type_options, dict):
            return list(type_options.keys())
        if isinstance(type_options, (list, tuple)):
            return list(type_options)
    return [DEFAULT_PATH_TYPE]


def _allowed_path_types(meta: dict | None) -> set[str]:
    return set(_ordered_path_types(meta))


def _build_metadata_response(route_name: str, meta: dict | None) -> dict[str, Any]:
    """Cheap site metadata — advertises the available ``type`` space, no upstream fetch."""
    types = _ordered_path_types(meta)
    meta = meta or {}
    return {
        "code": 200,
        "name": route_name,
        "title": meta.get("title") or route_name,
        "description": meta.get("description"),
        "link": meta.get("link"),
        "params": meta.get("params"),
        "defaultType": types[0],
        "types": types,
        "dataPath": f"/{route_name}/{{type}}",
    }


def _register_route(
    route_name: str,
    handle_route: Any,
    *,
    category: str = "hotlist",
    category_label: str = "热榜",
) -> None:
    meta = _get_route_meta(handle_route)
    module = sys.modules.get(getattr(handle_route, "__module__", ""))
    validate_type = (
        getattr(module, "ROUTE_VALIDATE_TYPE", True) if module is not None else True
    )
    route_handlers[route_name] = RouteHandlerInfo(
        handle_route=handle_route,
        category=category,
        category_label=category_label,
        metadata=meta,
        validate_type=validate_type,
    )
    # Both handlers close over route_name/meta/handle_route/validate_type. Each
    # _register_route call gets its own frame, so the closures are per-route (no
    # late-binding). Captures are NOT declared as function params — FastAPI would
    # otherwise treat typed scalars/dicts (str, dict) as query/body params.

    # (1) Metadata endpoint — cheap, does not call handle_route.
    @router.get(f"/{route_name}", name=route_name)
    async def metadata_route_handler() -> JSONResponse:
        return JSONResponse(_build_metadata_response(route_name, meta))

    # (2) Data endpoint — inject path ``type`` into query, call unchanged handle_route.
    @router.get(f"/{route_name}/{{type}}", name=f"{route_name}:data")
    async def data_route_handler(
        request: Request,
        type: str,
        cache: str | None = Query(None),
        limit: int | None = Query(None, ge=1, le=200),
        rss: str | None = Query(None),
    ) -> Response:
        if validate_type:
            advertised = _allowed_path_types(meta)
            if type not in advertised:
                return JSONResponse(
                    {
                        "code": 400,
                        "message": (
                            f"Unknown type '{type}' for route '{route_name}'. "
                            f"Valid types: {sorted(advertised)}"
                        ),
                    },
                    status_code=400,
                )
        cache_mode = (cache or "").lower()
        cache_policy = (
            CachePolicy.REFRESH
            if cache_mode == "false"
            else CachePolicy.ONLY
            if cache_mode == "only"
            else CachePolicy.PREFER
        )
        params = {
            key: value
            for key, value in request.query_params.multi_items()
            if key not in {"type", "cache", "limit", "rss"}
        }
        try:
            result = await fetch_service.fetch(
                FetchRequest(
                    site=route_name,
                    path_type=type,
                    params=params,
                    limit=limit,
                    cache_policy=cache_policy,
                )
            )
            route_data = result.data
        except FetchError as exc:
            if exc.code == "CACHE_ONLY_MISS":
                logger.info(f"💾 [CACHE_ONLY_MISS] {exc.message}")
                return JSONResponse(
                    {
                        "code": 404,
                        "message": "No cached data available for this route.",
                        "fromCache": False,
                    },
                    status_code=404,
                )
            if exc.status_code < 500:
                return JSONResponse(
                    {"code": exc.status_code, "message": exc.message},
                    status_code=exc.status_code,
                )
            logger.exception(f"❌ Route '{route_name}' failed")
            return JSONResponse(
                {"code": 500, "message": "Internal Server Error"},
                status_code=500,
            )

        # RSS output
        if rss == "true" or config.RSS_MODE:
            rss_content = get_rss(route_data)
            if isinstance(rss_content, str):
                return Response(
                    content=rss_content,
                    media_type="application/xml; charset=utf-8",
                )
            return JSONResponse(
                {"code": 500, "message": "RSS generation failed"},
                status_code=500,
            )

        return JSONResponse(
            {
                "code": 200,
                **route_data.model_dump(exclude={"params"}, exclude_none=True),
            }
        )


@router.get("/all")
async def get_all_routes() -> JSONResponse:
    return JSONResponse(
        {
            "code": 200,
            "count": len(all_routes),
            "routes": all_routes,
        }
    )


@router.get("/categories")
async def get_categories() -> JSONResponse:
    return JSONResponse(
        {
            "code": 200,
            "categories": _categories_cache or [],
        }
    )

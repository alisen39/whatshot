from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager
from inspect import isawaitable
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from whats_hot_api._version import get_version
from whats_hot_api.catalog import route_catalog
from whats_hot_api.config import Settings, config, replace_config
from whats_hot_api.registry import discover_and_register_routes, fetch_service, router
from whats_hot_api.runtime import CoreRuntime
from whats_hot_api.utils.cache import cache
from whats_hot_api.utils.http_client import close_client
from whats_hot_api.utils.logger import logger


def _cors_origins(raw_value: str) -> list[str]:
    """Parse a comma-separated origin allowlist without accepting empty values."""
    values = [value.strip() for value in raw_value.split(",") if value.strip()]
    return values or []


async def _safe_cleanup(name: str, callback: Callable[[], Any]) -> None:
    """Run one lifecycle cleanup without blocking the remaining stack."""
    try:
        result = callback()
        if isawaitable(result):
            await result
    except Exception:  # noqa: BLE001 - cleanup failures must not skip later hooks
        logger.exception(f"❌ Lifecycle cleanup failed: {name}")


def create_app(
    *,
    settings: Settings | None = None,
    extra_routers: list[APIRouter] | None = None,
    extra_startup: list[Callable] | None = None,
    extra_shutdown: list[Callable] | None = None,
    extra_route_packages: list[str] | None = None,
    cors_allow_methods: list[str] | None = None,
    cors_allow_headers: list[str] | None = None,
    title: str = "WhatsHot API",
    version: str | None = None,
) -> FastAPI:
    """Application factory.

    Parameters
    ----------
    settings:
        Custom :class:`Settings` (or subclass) instance.  When provided the
        module-level ``config`` singleton is replaced so every core module
        sees the extended settings.
    extra_routers:
        Additional :class:`APIRouter` instances to include (e.g. extension
        API endpoints).
    extra_startup / extra_shutdown:
        Async callables executed during the lifespan startup / shutdown
        phases, **after** core initialisation.
    extra_route_packages:
        Dotted import paths of additional route packages to scan.  Each
        package follows the same convention as ``whats_hot_api.routes``.
    cors_allow_methods / cors_allow_headers:
        CORS permissions required by an embedding application. Core defaults
        to read-only browser access; extensions opt into their own API needs.
    title / version:
        FastAPI app metadata.
    """

    # ------------------------------------------------------------------
    # 1. Replace config singleton if extension provides custom settings
    # ------------------------------------------------------------------
    effective_config = settings or config
    if settings is not None:
        replace_config(settings)

    # ------------------------------------------------------------------
    # 2. Discover & register routes (core + extensions)
    # ------------------------------------------------------------------
    discover_and_register_routes(extra_packages=extra_route_packages)

    # ------------------------------------------------------------------
    # 3. Build lifespan
    # ------------------------------------------------------------------
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with AsyncExitStack() as lifecycle:
            # Register core cleanup before any startup hook can acquire these
            # lazy resources. AsyncExitStack executes in reverse order.
            lifecycle.push_async_callback(_safe_cleanup, "cache", cache.close)
            lifecycle.push_async_callback(_safe_cleanup, "http_client", close_client)

            # Shutdown hooks are pre-registered so a startup hook that fails
            # halfway through can still roll back partially acquired resources.
            for index, hook in enumerate(extra_shutdown or []):
                lifecycle.push_async_callback(
                    _safe_cleanup,
                    f"extension_shutdown[{index}]",
                    hook,
                )

            for hook in extra_startup or []:
                await hook()

            logger.info(
                f"🔥 WhatsHot API successfully runs on port {effective_config.PORT}"
            )
            logger.info(f"🔗 Local: 👉 http://localhost:{effective_config.PORT}")
            yield

    # ------------------------------------------------------------------
    # 4. Create FastAPI instance
    # ------------------------------------------------------------------
    application = FastAPI(
        title=title,
        version=version or get_version(),
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    application.state.core_runtime = CoreRuntime(
        settings=effective_config,
        routes=route_catalog,
        cache=cache,
        fetch=fetch_service,
    )

    # GZip compression
    application.add_middleware(GZipMiddleware, minimum_size=1000)

    # CORS
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(effective_config.ALLOWED_DOMAIN),
        allow_credentials=False,
        allow_methods=cors_allow_methods or ["GET"],
        allow_headers=cors_allow_headers or ["Content-Type"],
    )

    # Include core route registry.
    application.include_router(router)

    # Include extension routers
    for extra_router in extra_routers or []:
        application.include_router(extra_router)

    # ------------------------------------------------------------------
    # 5. Register API error handlers
    # ------------------------------------------------------------------
    @application.exception_handler(404)
    async def not_found_handler(request: Request, _exc: Any) -> Any:
        return JSONResponse(
            {"code": 404, "message": "Not Found", "path": request.url.path},
            status_code=404,
        )

    @application.exception_handler(500)
    async def error_handler(request: Request, exc: Any) -> Any:
        logger.exception(f"❌ [ERROR] Unhandled request failure: {request.url.path}")
        return JSONResponse(
            {"code": 500, "message": "Internal Server Error", "path": request.url.path},
            status_code=500,
        )

    return application

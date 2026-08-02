"""Tests for create_app() factory, config replacement, and extension hooks."""

from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

from whats_hot_api.config import Settings, replace_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# create_app() basics
# ---------------------------------------------------------------------------


class TestCreateAppDefaults:
    """Test create_app() with default arguments."""

    async def test_default_title_and_version(self):
        from whats_hot_api.app import create_app

        app = create_app()
        assert app.title == "WhatsHot API"
        assert app.version == "0.1.0"

    async def test_all_routes_registered(self):
        from whats_hot_api.app import create_app

        app = create_app()
        async with _make_client(app) as client:
            resp = await client.get("/all")
            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == 200
            assert data["count"] == len(data["routes"])
            assert data["count"] >= 56

    async def test_categories_endpoint(self):
        from whats_hot_api.app import create_app

        app = create_app()
        async with _make_client(app) as client:
            resp = await client.get("/categories")
            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == 200
            assert isinstance(data["categories"], list)
            assert len(data["categories"]) > 0

    async def test_root_is_api_404(self):
        from whats_hot_api.app import create_app

        app = create_app()
        async with _make_client(app) as client:
            resp = await client.get("/")
            assert resp.status_code == 404
            assert resp.headers["content-type"].startswith("application/json")
            assert resp.json()["code"] == 404

    async def test_robots_txt_not_registered(self):
        from whats_hot_api.app import create_app

        app = create_app()
        async with _make_client(app) as client:
            resp = await client.get("/robots.txt")
            assert resp.status_code == 404
            assert resp.headers["content-type"].startswith("application/json")
            assert resp.json()["code"] == 404

    async def test_html_docs_are_disabled(self):
        from whats_hot_api.app import create_app

        app = create_app()
        async with _make_client(app) as client:
            for path in ("/docs", "/redoc"):
                resp = await client.get(path)
                assert resp.status_code == 404
                assert resp.headers["content-type"].startswith("application/json")
                assert resp.json()["code"] == 404

    async def test_404_handler(self):
        from whats_hot_api.app import create_app

        app = create_app()
        async with _make_client(app) as client:
            resp = await client.get("/nonexistent-xyz-abc")
            assert resp.status_code == 404
            assert resp.headers["content-type"].startswith("application/json")
            assert resp.json() == {
                "code": 404,
                "message": "Not Found",
                "path": "/nonexistent-xyz-abc",
            }


class TestCreateAppCustomMetadata:
    """Test create_app() with custom title and version."""

    async def test_custom_title(self):
        from whats_hot_api.app import create_app

        app = create_app(title="My Custom API")
        assert app.title == "My Custom API"

    async def test_custom_version(self):
        from whats_hot_api.app import create_app

        app = create_app(version="9.9.9")
        assert app.version == "9.9.9"

    async def test_custom_title_and_version(self):
        from whats_hot_api.app import create_app

        app = create_app(title="Extension App", version="3.0.0")
        assert app.title == "Extension App"
        assert app.version == "3.0.0"


# ---------------------------------------------------------------------------
# Extra routers
# ---------------------------------------------------------------------------


class TestCreateAppExtraRouters:
    """Test create_app(extra_routers=[...])."""

    async def test_extra_router_endpoint_accessible(self):
        from whats_hot_api.app import create_app

        extra = APIRouter()

        @extra.get("/custom-extension")
        async def custom_endpoint():
            return {"hello": "extension"}

        app = create_app(extra_routers=[extra])
        async with _make_client(app) as client:
            resp = await client.get("/custom-extension")
            assert resp.status_code == 200
            assert resp.json() == {"hello": "extension"}

    async def test_extra_router_does_not_shadow_core_routes(self):
        from whats_hot_api.app import create_app

        extra = APIRouter()

        @extra.get("/ping")
        async def ping():
            return {"pong": True}

        app = create_app(extra_routers=[extra])
        async with _make_client(app) as client:
            # Core routes still work
            resp_all = await client.get("/all")
            assert resp_all.status_code == 200
            assert resp_all.json()["code"] == 200
            # Extra route works too
            resp_ping = await client.get("/ping")
            assert resp_ping.status_code == 200
            assert resp_ping.json()["pong"] is True

    async def test_multiple_extra_routers(self):
        from whats_hot_api.app import create_app

        r1 = APIRouter()
        r2 = APIRouter()

        @r1.get("/ext-one")
        async def ext_one():
            return {"router": 1}

        @r2.get("/ext-two")
        async def ext_two():
            return {"router": 2}

        app = create_app(extra_routers=[r1, r2])
        async with _make_client(app) as client:
            resp1 = await client.get("/ext-one")
            resp2 = await client.get("/ext-two")
            assert resp1.json()["router"] == 1
            assert resp2.json()["router"] == 2


# ---------------------------------------------------------------------------
# Custom settings
# ---------------------------------------------------------------------------


class TestCreateAppCustomSettings:
    """Test create_app(settings=custom_settings)."""

    async def test_custom_settings_replaces_config(self):
        import whats_hot_api.config as config_mod

        original = config_mod.config
        try:
            custom = Settings(PORT=9999)
            from whats_hot_api.app import create_app

            create_app(settings=custom)

            assert config_mod.config is custom
            assert config_mod.config.PORT == 9999
        finally:
            config_mod.config = original

    async def test_none_settings_keeps_default(self):
        import whats_hot_api.config as config_mod

        original = config_mod.config
        from whats_hot_api.app import create_app

        create_app(settings=None)
        # Config should not have been replaced
        assert config_mod.config is original


# ---------------------------------------------------------------------------
# replace_config()
# ---------------------------------------------------------------------------


class TestReplaceConfig:
    """Test replace_config() directly."""

    async def test_replaces_module_singleton(self):
        import whats_hot_api.config as config_mod

        original = config_mod.config
        try:
            new_settings = Settings(PORT=1234, CACHE_TTL=999)
            replace_config(new_settings)

            assert config_mod.config is new_settings
            assert config_mod.config.PORT == 1234
            assert config_mod.config.CACHE_TTL == 999
        finally:
            config_mod.config = original

    async def test_visible_through_module_reimport(self):
        import importlib

        import whats_hot_api.config as config_mod

        original = config_mod.config
        try:
            new_settings = Settings(PORT=5555)
            replace_config(new_settings)

            reloaded = importlib.import_module("whats_hot_api.config")
            assert reloaded.config.PORT == 5555
        finally:
            config_mod.config = original

    async def test_updates_stale_imported_config_references(self):
        import whats_hot_api.config as config_mod
        import whats_hot_api.registry as registry_mod

        original = config_mod.config
        stale_ref = registry_mod.config
        try:
            new_settings = Settings(PORT=7777, CACHE_TTL=321)
            replace_config(new_settings)

            assert config_mod.config is new_settings
            assert stale_ref.PORT == 7777
            assert stale_ref.CACHE_TTL == new_settings.CACHE_TTL
        finally:
            config_mod.config = original


# ---------------------------------------------------------------------------
# __init__.py exports
# ---------------------------------------------------------------------------


class TestInitExports:
    """Test whats_hot_api.__init__.py public API."""

    def test_create_app_exported(self):
        import whats_hot_api

        assert callable(whats_hot_api.create_app)

    def test_settings_exported(self):
        import whats_hot_api

        assert whats_hot_api.Settings is Settings

    def test_replace_config_exported(self):
        import whats_hot_api

        assert whats_hot_api.replace_config is replace_config

    def test_discover_and_register_routes_exported(self):
        from whats_hot_api import discover_and_register_routes

        assert callable(discover_and_register_routes)

    def test_all_routes_exported(self):
        from whats_hot_api import all_routes

        assert isinstance(all_routes, list)

    def test_route_handlers_exported(self):
        from whats_hot_api import route_handlers

        assert isinstance(route_handlers, dict)

    def test_fetch_service_types_exported(self):
        import whats_hot_api

        assert callable(whats_hot_api.FetchService)
        assert callable(whats_hot_api.FetchRequest)
        assert whats_hot_api.CachePolicy.REFRESH.value == "refresh"

    def test_create_app_via_init_returns_fastapi(self):
        """create_app() accessed via __init__ should produce a FastAPI app."""
        import whats_hot_api

        app = whats_hot_api.create_app(title="Via Init", version="0.0.1")
        assert isinstance(app, FastAPI)
        assert app.title == "Via Init"


# ---------------------------------------------------------------------------
# Registry duplicate detection
# ---------------------------------------------------------------------------


class TestRegistryDuplicateDetection:
    """Test that discover_and_register_routes() handles duplicates correctly."""

    async def test_double_discovery_does_not_duplicate(self):
        from whats_hot_api.app import create_app
        from whats_hot_api.registry import (
            _registered_names,
            all_routes,
            discover_and_register_routes,
        )

        # Ensure routes are discovered
        create_app()
        count_before = len(all_routes)
        names_before = len(_registered_names)

        # Call discover again — should be a no-op
        discover_and_register_routes()

        assert len(all_routes) == count_before
        assert len(_registered_names) == names_before

    async def test_all_routes_have_required_fields(self):
        from whats_hot_api.app import create_app
        from whats_hot_api.registry import all_routes

        create_app()

        for route in all_routes:
            assert "name" in route
            assert "path" in route
            assert "dataPath" in route
            assert "category" in route
            assert "category_label" in route
            assert route["path"] == f"/{route['name']}"
            assert route["dataPath"] == f"/{route['name']}/{{type}}"

    async def test_route_handlers_populated(self):
        from whats_hot_api.app import create_app
        from whats_hot_api.registry import RouteHandlerInfo, route_handlers

        create_app()

        assert len(route_handlers) >= 56
        for info in route_handlers.values():
            assert isinstance(info, RouteHandlerInfo)
            assert callable(info.handle_route)
            assert isinstance(info.category, str)
            assert isinstance(info.category_label, str)


# ---------------------------------------------------------------------------
# Extension lifespan hooks
# ---------------------------------------------------------------------------


class TestExtensionLifespanHooks:
    """Test extra_startup and extra_shutdown hooks via lifespan."""

    async def test_startup_hook_called(self):
        from whats_hot_api.app import create_app

        called: list[str] = []

        async def my_startup():
            called.append("started")

        app = create_app(
            extra_startup=[my_startup],
            settings=Settings(),
        )

        # Manually invoke lifespan context manager
        async with app.router.lifespan_context(app):
            assert "started" in called

    async def test_shutdown_hook_called(self):
        from whats_hot_api.app import create_app

        called: list[str] = []

        async def my_shutdown():
            called.append("stopped")

        app = create_app(
            extra_shutdown=[my_shutdown],
            settings=Settings(),
        )

        async with app.router.lifespan_context(app):
            assert "stopped" not in called  # not yet
        # After exiting context, shutdown hook should have run
        assert "stopped" in called

    async def test_multiple_hooks_called_in_order(self):
        from whats_hot_api.app import create_app

        order: list[int] = []

        async def hook_1():
            order.append(1)

        async def hook_2():
            order.append(2)

        app = create_app(
            extra_startup=[hook_1, hook_2],
            settings=Settings(),
        )

        async with app.router.lifespan_context(app):
            assert order == [1, 2]

    async def test_startup_failure_rolls_back_extension_and_core_resources(
        self,
        monkeypatch,
    ):
        import whats_hot_api.app as app_mod

        events: list[str] = []

        async def close_http():
            events.append("http.close")

        async def close_cache():
            events.append("cache.close")

        async def startup_one():
            events.append("startup.1")

        async def startup_two():
            events.append("startup.2")
            raise RuntimeError("startup failed")

        async def extension_shutdown():
            events.append("extension.close")

        monkeypatch.setattr(app_mod, "close_client", close_http)
        monkeypatch.setattr(app_mod.cache, "close", close_cache)
        app = app_mod.create_app(
            settings=Settings(),
            extra_startup=[startup_one, startup_two],
            extra_shutdown=[extension_shutdown],
        )

        with pytest.raises(RuntimeError, match="startup failed"):
            async with app.router.lifespan_context(app):
                raise AssertionError("lifespan must not yield after startup failure")

        assert events == [
            "startup.1",
            "startup.2",
            "extension.close",
            "http.close",
            "cache.close",
        ]

    async def test_shutdown_failure_does_not_skip_remaining_cleanup(
        self,
        monkeypatch,
    ):
        import whats_hot_api.app as app_mod

        events: list[str] = []

        async def close_http():
            events.append("http.close")

        async def close_cache():
            events.append("cache.close")

        async def surviving_shutdown():
            events.append("extension.survived")

        async def failing_shutdown():
            events.append("extension.failed")
            raise RuntimeError("shutdown failed")

        monkeypatch.setattr(app_mod, "close_client", close_http)
        monkeypatch.setattr(app_mod.cache, "close", close_cache)
        app = app_mod.create_app(
            settings=Settings(),
            extra_shutdown=[surviving_shutdown, failing_shutdown],
        )

        async with app.router.lifespan_context(app):
            pass

        assert events == [
            "extension.failed",
            "extension.survived",
            "http.close",
            "cache.close",
        ]

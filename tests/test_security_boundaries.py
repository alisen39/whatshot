from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from whats_hot_api.app import create_app
import whats_hot_api.app as app_module


async def test_cors_never_allows_credentials_with_wildcard_origin(monkeypatch) -> None:
    monkeypatch.setattr(app_module.config, "ALLOWED_DOMAIN", "*")
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.options(
            "/all",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers


async def test_cors_parses_explicit_origin_allowlist(monkeypatch) -> None:
    monkeypatch.setattr(
        app_module.config,
        "ALLOWED_DOMAIN",
        "https://whatshot.top, https://admin.whatshot.top",
    )
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        allowed = await client.options(
            "/all",
            headers={
                "Origin": "https://admin.whatshot.top",
                "Access-Control-Request-Method": "GET",
            },
        )
        denied = await client.options(
            "/all",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.headers["access-control-allow-origin"] == "https://admin.whatshot.top"
    assert "access-control-allow-origin" not in denied.headers


async def test_core_cors_is_read_only_by_default() -> None:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.options(
            "/all",
            headers={
                "Origin": "https://whatshot.top",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 400

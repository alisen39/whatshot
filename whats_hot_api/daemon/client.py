"""Synchronous local Control API client used by the CLI."""

from __future__ import annotations

from typing import Any

import httpx


class DaemonClientError(RuntimeError):
    def __init__(self, message: str, *, code: str = "DAEMON_UNAVAILABLE") -> None:
        super().__init__(message)
        self.code = code


class DaemonClient:
    def __init__(self, base_url: str, *, timeout: float = 35.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> Any:
        return self._request("POST", path, json=json)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                params={
                    key: value
                    for key, value in (params or {}).items()
                    if value is not None
                },
                json=json,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise DaemonClientError(
                f"Unable to reach WhatsHot daemon at {self.base_url}."
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise DaemonClientError(
                "WhatsHot daemon returned an invalid response.",
                code="DAEMON_INVALID_RESPONSE",
            ) from exc
        if response.is_error:
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            raise DaemonClientError(
                str(
                    error.get("message")
                    or f"Daemon returned HTTP {response.status_code}."
                ),
                code=str(error.get("code") or "DAEMON_REQUEST_FAILED"),
            )
        return payload

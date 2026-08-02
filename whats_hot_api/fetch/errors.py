"""Domain errors emitted by the reusable fetch service."""

from __future__ import annotations

from typing import Any


class FetchError(Exception):
    """Base class with stable machine-readable error metadata."""

    code = "FETCH_ERROR"
    status_code = 500
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


class FetchInvalidRequestError(FetchError):
    code = "INVALID_FETCH_REQUEST"
    status_code = 400


class FetchSourceNotFoundError(FetchError):
    code = "UNKNOWN_SOURCE"
    status_code = 404


class FetchTypeNotFoundError(FetchError):
    code = "UNKNOWN_TYPE"
    status_code = 400


class FetchCacheMissError(FetchError):
    code = "CACHE_ONLY_MISS"
    status_code = 404


class FetchUpstreamError(FetchError):
    code = "UPSTREAM_FAILURE"
    status_code = 502
    retryable = True

"""Reusable route fetching facade for HTTP, CLI, Scheduler, and MCP."""

from whats_hot_api.fetch.errors import (
    FetchCacheMissError,
    FetchError,
    FetchInvalidRequestError,
    FetchSourceNotFoundError,
    FetchTypeNotFoundError,
    FetchUpstreamError,
)
from whats_hot_api.fetch.identity import canonical_board_key
from whats_hot_api.fetch.models import (
    CachePolicy,
    FetchRequest,
    FetchResult,
    SourceDescriptor,
)
from whats_hot_api.fetch.service import FetchService

__all__ = [
    "CachePolicy",
    "FetchCacheMissError",
    "FetchError",
    "FetchInvalidRequestError",
    "FetchRequest",
    "FetchResult",
    "FetchService",
    "FetchSourceNotFoundError",
    "FetchTypeNotFoundError",
    "FetchUpstreamError",
    "SourceDescriptor",
    "canonical_board_key",
]

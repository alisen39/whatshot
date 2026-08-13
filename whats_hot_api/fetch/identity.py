"""Canonical board identity shared by CLI, Scheduler, history, and MCP.

``boardKey`` v1 is deliberately derived only from dimensions declared by a
source.  This keeps transport options (for example ``limit`` or ``cache``)
out of persistent board identity and gives the DuckDB and PostgreSQL backends
one deterministic representation.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from urllib.parse import quote, urlencode

BOARD_KEY_VERSION = 1
SUPPORTED_BOARD_DIMENSIONS = frozenset(
    {"type", "game", "range", "sort", "province", "day", "month"}
)


class BoardIdentityError(ValueError):
    """A board identity contains an unsupported or ambiguous dimension."""


def canonical_board_key(
    *,
    path_type: str,
    params: Mapping[str, str],
    declared_dimensions: Collection[str],
) -> str:
    """Return the canonical v1 identity for one source board.

    A declared ``type`` dimension is encoded first using ``path_type``.  All
    other supplied dimensions are encoded by dimension-name order.  Values use
    UTF-8 RFC 3986 percent encoding (spaces are ``%20``, never ``+``).  A
    source with no board dimensions has the fixed identity ``hot``.

    ``params`` must not repeat ``type`` because its sole value is
    ``path_type``.  Unknown dimensions, dimensions not declared by the source,
    and empty keys/values are rejected instead of being silently folded into a
    different board.
    """

    declared = tuple(declared_dimensions)
    if any(not isinstance(key, str) or not key for key in declared):
        raise BoardIdentityError(
            "declared board dimensions must be non-empty strings"
        )
    if len(declared) != len(set(declared)):
        raise BoardIdentityError(
            "declared board dimensions must not contain duplicates"
        )

    unsupported_declared = set(declared) - SUPPORTED_BOARD_DIMENSIONS
    if unsupported_declared:
        raise BoardIdentityError(
            "unsupported declared board dimensions: "
            f"{sorted(unsupported_declared)}"
        )

    provided_keys = set(params)
    if any(not isinstance(key, str) or not key for key in provided_keys):
        raise BoardIdentityError("board dimension keys must be non-empty strings")
    if "type" in provided_keys:
        raise BoardIdentityError("type must be supplied only as path_type")

    unsupported_provided = provided_keys - SUPPORTED_BOARD_DIMENSIONS
    if unsupported_provided:
        raise BoardIdentityError(
            f"unsupported board dimensions: {sorted(unsupported_provided)}"
        )

    undeclared = provided_keys - set(declared)
    if undeclared:
        raise BoardIdentityError(
            f"board dimensions not declared by source: {sorted(undeclared)}"
        )

    dimensions: list[tuple[str, str]] = []
    if "type" in declared:
        if not isinstance(path_type, str) or not path_type:
            raise BoardIdentityError("path_type must be a non-empty string")
        dimensions.append(("type", path_type))
    for key in sorted(provided_keys):
        value = params[key]
        if not isinstance(value, str) or not value:
            raise BoardIdentityError(
                f"board dimension '{key}' must have a non-empty string value"
            )
        dimensions.append((key, value))

    if not dimensions:
        return "hot"
    return urlencode(
        dimensions,
        doseq=False,
        safe="",
        encoding="utf-8",
        errors="strict",
        quote_via=quote,
    )


def board_key_read_candidates(board_key: str) -> tuple[str, ...]:
    """Return exact keys to try while the legacy ``default`` alias exists.

    New writes must always use :func:`canonical_board_key`.  This helper is
    intentionally non-destructive: a later DuckDB migration can use it for the
    compatibility window without rewriting existing rows in place.
    """

    if board_key in {"hot", "default"}:
        return ("hot", "default")
    return (board_key,)

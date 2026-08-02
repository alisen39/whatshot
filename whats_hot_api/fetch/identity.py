"""Canonical board identity shared by CLI, Scheduler, history, and MCP."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlencode


def canonical_board_key(
    *,
    path_type: str,
    params: Mapping[str, str],
    has_type_dimension: bool,
) -> str:
    dimensions: list[tuple[str, str]] = []
    if has_type_dimension:
        dimensions.append(("type", path_type))
    dimensions.extend(
        sorted((str(key), str(value)) for key, value in params.items() if key != "type")
    )
    return urlencode(dimensions) if dimensions else "hot"

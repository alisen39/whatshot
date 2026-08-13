"""Contract v1 text normalization shared by migration, writes, and queries."""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_search_text(value: str) -> str:
    """Apply Unicode NFKC, casefold, and whitespace normalization."""

    if not isinstance(value, str):
        raise TypeError("search text must be a string")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def evidence_search_text(
    title: str,
    description: str | None,
) -> str:
    """Build the normalized literal-search document for one evidence row."""

    document = " ".join(value for value in (title, description) if value)
    return normalize_search_text(document)

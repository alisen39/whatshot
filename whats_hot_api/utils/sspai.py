"""Utilities for public data returned by the 少数派 API."""

from __future__ import annotations

import re
from typing import Any

_CDNFILE_DATED_BANNER = re.compile(
    r"^https?://cdnfile\.sspai\.com/(?=(?:\d{4}/\d{1,2}/\d{1,2}|\d{1,2}/\d{1,2}/\d{4})/)",
    re.IGNORECASE,
)


def sspai_cover_url(path: Any) -> str | None:
    """Resolve 少数派's relative banner paths against its image CDN."""
    if not isinstance(path, str) or not path:
        return None
    # Existing caches or upstream payloads can already contain the old CDN
    # absolute URL. Restrict rewriting to the verified host and date paths.
    if _CDNFILE_DATED_BANNER.match(path):
        return _CDNFILE_DATED_BANNER.sub("https://rssfile.sspai.com/", path, count=1)
    if path.startswith("http"):
        return path
    # The original article's og:image uses the public RSS image host. Unlike
    # cdnfile, the sampled RSS resources also serve requests without Referer.
    return "https://rssfile.sspai.com/" + path.lstrip("/")

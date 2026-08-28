from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

from bs4 import BeautifulSoup

from whats_hot_api.models import ListItem


def parse_feed(xml: str, *, limit: int = 30) -> list[ListItem]:
    """Parse RSS/Atom XML into the common hot-list item model."""
    soup = BeautifulSoup(xml, "xml")
    nodes = soup.find_all("item") or soup.find_all("entry")
    items: list[ListItem] = []
    for node in nodes:
        title = _normalize(_tag_text(node, "title"))
        url = _feed_link(node)
        if not title or not _valid_url(url):
            continue
        description = (
            _tag_text(node, "description")
            or _tag_text(node, "summary")
            or _tag_text(node, "content")
            or _tag_text(node, "content:encoded")
        )
        items.append(
            ListItem(
                id=_tag_text(node, "guid") or _tag_text(node, "id") or url,
                title=title,
                author=(
                    _tag_text(node, "dc:creator")
                    or _author_text(node)
                    or _tag_text(node, "source")
                    or None
                ),
                desc=_clean_html(description),
                cover=_feed_image(node, description),
                timestamp=_parse_timestamp(
                    _tag_text(node, "pubDate")
                    or _tag_text(node, "pubdate")
                    or _tag_text(node, "published")
                    or _tag_text(node, "updated")
                    or _tag_text(node, "dc:date")
                ),
                url=url,
                mobileUrl=url,
            )
        )
    if any(item.timestamp for item in items):
        items.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return items[:limit]


def _feed_link(node) -> str:
    link = node.find("link")
    if not link:
        return ""
    href = link.get("href")
    return href.strip() if href else link.get_text("", strip=True)


def _feed_image(node, description: str) -> str | None:
    for tag_name in ("media:thumbnail", "media:content", "image"):
        tag = node.find(tag_name)
        if tag:
            candidate = tag.get("url") or tag.get_text("", strip=True)
            if _valid_url(candidate):
                return candidate
    enclosure = node.find("enclosure")
    if enclosure:
        candidate = enclosure.get("url")
        media_type = enclosure.get("type") or ""
        if (not media_type or media_type.startswith("image/")) and _valid_url(candidate):
            return candidate
    html = BeautifulSoup(description or "", "lxml")
    image = html.find("img")
    candidate = image.get("src") if image else None
    return candidate if _valid_url(candidate) else None


def _author_text(node) -> str:
    author = node.find("author")
    if not author:
        return ""
    name = author.find("name")
    return name.get_text(" ", strip=True) if name else author.get_text(" ", strip=True)


def _tag_text(node, name: str) -> str:
    tag = node.find(name)
    return tag.get_text(" ", strip=True) if tag else ""


def _parse_timestamp(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(parsedate_to_datetime(text).timestamp() * 1000)
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    try:
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except ValueError:
        return None


def _clean_html(value: Any, *, limit: int = 500) -> str | None:
    text = BeautifulSoup(str(value or ""), "lxml").get_text(" ", strip=True)
    normalized = _normalize(text)
    return normalized[:limit] or None


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _valid_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))

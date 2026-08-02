from __future__ import annotations

import html
import re
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_TRUNCATED_SUFFIXES = ("...", "…", "……")


def strip_html(value: object) -> str:
    text = "" if value is None else str(value)
    return html.unescape(_TAG_RE.sub("", text)).replace("\xa0", " ").strip()


def text_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def to_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    match = _NUMBER_RE.search(str(value))
    if not match:
        return None
    try:
        return int(float(match.group(0)))
    except ValueError:
        return None


def truthy_flag(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if not text:
        return False
    if text in {"false", "no", "none", "null"}:
        return False
    number = to_int(text)
    return number != 0 if number is not None else text in {"true", "yes", "y"}


def content_status(
    text: str,
    *,
    fallback: str = "full",
    has_more: object = None,
) -> str:
    stripped = text.strip()
    if truthy_flag(has_more) or stripped.endswith(_TRUNCATED_SUFFIXES):
        return "truncated"
    return fallback


def metrics(**values: object) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def compact_strings(items: object, keys: tuple[str, ...] = ("name", "title", "text", "label", "tag_name")) -> list[str]:
    if not items:
        return []
    if isinstance(items, (str, int, float)):
        return [str(items).strip()] if str(items).strip() else []
    if not isinstance(items, list):
        items = [items]

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value: object = None
        if isinstance(item, dict):
            for key in keys:
                if item.get(key):
                    value = item[key]
                    break
        else:
            value = item
        text = str(value).strip() if value is not None else ""
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def compact_urls(items: object) -> list[str]:
    if not items:
        return []
    if isinstance(items, str):
        return [items.strip()] if items.strip() else []
    if not isinstance(items, list):
        items = [items]

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value: object = item
        if isinstance(item, dict):
            value = (
                item.get("url")
                or item.get("uri")
                or item.get("src")
                or item.get("image")
                or item.get("img")
                or item.get("cover")
            )
        text = str(value).strip() if value is not None else ""
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def compact_objects(items: object) -> list[dict[str, Any]]:
    if not items:
        return []
    if isinstance(items, (str, int, float)):
        return [{"name": str(items).strip()}] if str(items).strip() else []
    if not isinstance(items, list):
        items = [items]

    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            compact = {
                str(key): value
                for key, value in item.items()
                if value not in (None, "", [])
                and isinstance(value, (str, int, float, bool))
            }
            if compact:
                result.append(compact)
        else:
            text = str(item).strip()
            if text:
                result.append({"name": text})
    return result

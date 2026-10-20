"""Data embedded in Next.js App Router pages (React Server Components flight payload).

Server-rendered pages push their data as JS string chunks
(``self.__next_f.push([1,"..."])``). Joining and JSON-decoding the chunks gives
text in which page data appears as plain JSON values after their keys.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)


def flight_text(html: str) -> str:
    parts = []
    for chunk in _CHUNK.findall(html or ""):
        try:
            parts.append(json.loads(f'"{chunk}"'))
        except json.JSONDecodeError:
            continue
    return "".join(parts)


def json_values(text: str, key: str) -> Iterator[Any]:
    """Every JSON value that follows ``"key":`` in text, in order."""
    marker = f'"{key}":'
    decoder = json.JSONDecoder()
    start = text.find(marker)
    while start >= 0:
        position = start + len(marker)
        while position < len(text) and text[position] in " \t\r\n":
            position += 1
        try:
            value, _ = decoder.raw_decode(text, position)
        except json.JSONDecodeError:
            pass
        else:
            yield value
        start = text.find(marker, start + len(marker))


def first_list(html: str, key: str) -> list:
    """The longest list stored under key (pages may also embed shorter featured lists)."""
    lists = [v for v in json_values(flight_text(html), key) if isinstance(v, list)]
    return max(lists, key=len) if lists else []

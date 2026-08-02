"""Stable CLI output renderers."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import orjson
import yaml
from wcwidth import wcswidth

OutputFormat = Literal["table", "plain", "json", "jsonl", "yaml", "markdown", "csv"]
OUTPUT_FORMATS: tuple[OutputFormat, ...] = (
    "table",
    "plain",
    "json",
    "jsonl",
    "yaml",
    "markdown",
    "csv",
)


def render(value: Any, output_format: OutputFormat) -> str:
    if output_format == "json":
        return orjson.dumps(
            value,
            option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE,
        ).decode()
    if output_format == "jsonl":
        rows = _rows(value)
        return "".join(orjson.dumps(row).decode() + "\n" for row in rows)
    if output_format == "yaml":
        return yaml.safe_dump(
            value,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    if output_format == "csv":
        return _render_csv(_rows(value))
    if output_format == "markdown":
        return _render_markdown(_rows(value))
    if output_format == "plain":
        return _render_plain(_rows(value))
    return _render_table(_rows(value))


def normalize_rows(
    items: Sequence[Any],
    *,
    site: str | None = None,
    board_key: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, item in enumerate(items, start=1):
        if hasattr(item, "model_dump"):
            row = item.model_dump(exclude_none=True)
        elif isinstance(item, Mapping):
            row = dict(item)
        else:
            row = {"value": item}
        row = {"rank": rank, **row}
        if site is not None:
            row["site"] = site
        if board_key is not None:
            row["boardKey"] = board_key
        rows.append(row)
    return rows


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [
            dict(row) if isinstance(row, Mapping) else {"value": row} for row in value
        ]
    if isinstance(value, Mapping):
        return [dict(value)]
    return [{"value": value}]


def _columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    preferred = [
        "rank",
        "id",
        "title",
        "hot",
        "sellPrice",
        "recyclePrice",
        "author",
        "source",
        "isImportant",
        "timestamp",
        "observedAt",
        "site",
        "boardKey",
        "url",
    ]
    available = {key for row in rows for key in row}
    result = [key for key in preferred if key in available]
    result.extend(sorted(available - set(result)))
    return result


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value).replace("\r", " ").replace("\n", " ")


def _width(value: str) -> int:
    measured = wcswidth(value)
    return len(value) if measured < 0 else measured


def _pad(value: str, width: int) -> str:
    return value + " " * max(0, width - _width(value))


def _render_table(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return ""
    columns = _columns(rows)
    widths = {
        column: max(
            _width(column),
            *(_width(_cell(row.get(column))) for row in rows),
        )
        for column in columns
    }
    header = "  ".join(_pad(column, widths[column]) for column in columns)
    rule = "  ".join("-" * widths[column] for column in columns)
    body = [
        "  ".join(_pad(_cell(row.get(column)), widths[column]) for column in columns)
        for row in rows
    ]
    return "\n".join([header, rule, *body]) + "\n"


def _render_plain(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return ""
    lines = []
    for row in rows:
        title = row.get("title")
        if title is not None:
            prefix = f"{row['rank']}. " if row.get("rank") is not None else ""
            lines.append(f"{prefix}{_cell(title)}")
        else:
            lines.append(
                " ".join(f"{key}={_cell(value)}" for key, value in row.items())
            )
    return "\n".join(lines) + "\n"


def _render_csv(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return ""
    output = io.StringIO()
    columns = _columns(rows)
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(
        {column: _cell(row.get(column)) for column in columns} for row in rows
    )
    return output.getvalue()


def _render_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return ""
    columns = _columns(rows)

    def escaped(value: Any) -> str:
        return _cell(value).replace("|", "\\|")

    header = "| " + " | ".join(columns) + " |"
    rule = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(escaped(row.get(column)) for column in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, rule, *body]) + "\n"

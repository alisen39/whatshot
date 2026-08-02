from __future__ import annotations

import csv
import io

import orjson
import pytest
import yaml

from whats_hot_api.cli.output import render

ROWS = [
    {
        "rank": 1,
        "id": "one",
        "title": "中文标题",
        "hot": 100,
        "url": "https://example.com/one",
    }
]


@pytest.mark.parametrize(
    ("output_format", "expected"),
    [
        ("plain", "1. 中文标题"),
        ("table", "中文标题"),
        ("markdown", "| rank | id | title | hot | url |"),
    ],
)
def test_human_output_formats(output_format: str, expected: str) -> None:
    assert expected in render(ROWS, output_format)  # type: ignore[arg-type]


def test_json_output() -> None:
    assert orjson.loads(render(ROWS, "json")) == ROWS


def test_jsonl_output() -> None:
    lines = render(ROWS, "jsonl").splitlines()
    assert len(lines) == 1
    assert orjson.loads(lines[0]) == ROWS[0]


def test_yaml_output() -> None:
    assert yaml.safe_load(render(ROWS, "yaml")) == ROWS


def test_csv_output() -> None:
    parsed = list(csv.DictReader(io.StringIO(render(ROWS, "csv"))))
    assert parsed[0]["title"] == "中文标题"
    assert parsed[0]["hot"] == "100"

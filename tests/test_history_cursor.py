from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from whats_hot_api.daemon.query_actor import _load_cursor_secret
from whats_hot_api.history import cursor as cursor_module
from whats_hot_api.history.cursor import HistoryCursorCodec
from whats_hot_api.history.errors import HistoryCursorError

NOW = datetime(2026, 8, 13, tzinfo=UTC)


def _token(codec: HistoryCursorCodec) -> str:
    return codec.encode(
        query="history",
        filters={
            "site": "demo",
            "boardKey": "hot",
            "kind": None,
            "since": None,
            "until": None,
        },
        since=NOW - timedelta(days=1),
        until=NOW,
        as_of=NOW,
        watermark=10,
        after_observed_at=NOW - timedelta(hours=1),
        after_ingest_sequence=5,
    )


@pytest.mark.parametrize(
    ("attribute", "replacement"),
    [
        ("CURSOR_CONTRACT_MAJOR", "2"),
        ("CURSOR_SORT", "observedAt:asc,evidenceId:asc"),
    ],
)
def test_cursor_binds_contract_major_and_sort(
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    replacement: str,
) -> None:
    codec = HistoryCursorCodec(b"cursor-codec-test-secret-value")
    token = _token(codec)
    monkeypatch.setattr(cursor_module, attribute, replacement)

    with pytest.raises(HistoryCursorError):
        codec.decode(
            token,
            query="history",
            filters={
                "site": "demo",
                "boardKey": "hot",
                "kind": None,
                "since": None,
                "until": None,
            },
            now=NOW,
        )


def test_cursor_signature_rejects_tampering() -> None:
    codec = HistoryCursorCodec(b"cursor-codec-test-secret-value")
    token = _token(codec)
    payload, signature = token.split(".")
    replacement = "A" if payload[0] != "A" else "B"
    tampered = f"{replacement}{payload[1:]}.{signature}"

    with pytest.raises(HistoryCursorError):
        codec.decode(
            tampered,
            query="history",
            filters={
                "site": "demo",
                "boardKey": "hot",
                "kind": None,
                "since": None,
                "until": None,
            },
            now=NOW,
        )


def test_daemon_cursor_secret_is_persistent_and_private(tmp_path: Path) -> None:
    path = tmp_path / "state" / "history_cursor.key"

    first = _load_cursor_secret(path)
    second = _load_cursor_secret(path)

    assert len(first) == 32
    assert second == first
    assert path.stat().st_mode & 0o777 == 0o600

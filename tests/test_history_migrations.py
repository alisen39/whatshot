from __future__ import annotations

import hashlib
import json
from collections import namedtuple
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from whats_hot_api.history.migrations import (
    MigrationAmbiguityError,
    MigrationDiskSpaceError,
    MigrationError,
    restore_database_backup,
)
from whats_hot_api.history.schema import SCHEMA_V1_SQL
from whats_hot_api.history.text import normalize_search_text
from whats_hot_api.scheduler.storage import SchedulerDuckDBWriter

NOW = datetime(2026, 8, 13, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  OpenAI\t发布  GPT  ", "openai 发布 gpt"),
        ("ＡＩ NEWS", "ai news"),
        ("Straße", "strasse"),
        ("① 热点", "1 热点"),
    ],
)
def test_search_normalization_matches_contract_vectors(
    value: str,
    expected: str,
) -> None:
    assert normalize_search_text(value) == expected


def _create_v1_fixture(
    path: Path,
    *,
    ambiguous: bool = False,
) -> None:
    connection = duckdb.connect(str(path))
    connection.execute("SET TimeZone = 'UTC'")
    connection.execute(SCHEMA_V1_SQL)
    connection.execute(
        """
        INSERT INTO schema_migrations (version, name, applied_at)
        VALUES (1, 'initial_history_schema', ?)
        """,
        [NOW],
    )
    captures = [
        (
            "capture-hot",
            "run-hot",
            "demo",
            "default",
            "hot",
            '{"range":"WEEK"}' if ambiguous else "{}",
            "hotlist",
            2,
        ),
        (
            "capture-news",
            "run-news",
            "flash",
            "range=WEEK&type=1",
            "1",
            '{"range":"WEEK"}',
            "newsflash",
            1,
        ),
        (
            "capture-gold",
            "run-gold",
            "gold",
            "hot",
            "hot",
            "{}",
            "gold",
            1,
        ),
    ]
    for (
        capture_id,
        run_key,
        site,
        board_key,
        path_type,
        params,
        kind,
        count,
    ) in captures:
        connection.execute(
            """
            INSERT INTO captures (
                capture_id, run_key, job_id, site, board_key, path_type,
                params_json, kind, title, type_label, scheduled_for,
                observed_at, response_update_at, item_count, content_hash
            ) VALUES (?, ?, 'fixture-job', ?, ?, ?, ?, ?, ?, 'fixture', ?, ?, ?, ?, ?)
            """,
            [
                capture_id,
                run_key,
                site,
                board_key,
                path_type,
                params,
                kind,
                f"{site} title",
                NOW,
                NOW,
                NOW,
                count,
                f"hash-{capture_id}",
            ],
        )
    connection.execute(
        """
        INSERT INTO hotlist_observations (
            capture_id, site, board_key, observed_at, position,
            source_item_id, title, url, description
        ) VALUES
            ('capture-hot', 'demo', 'default', ?, 1, 'same',
             'ＡＩ  NEWS', 'https://example.com/1', 'Straße'),
            ('capture-hot', 'demo', 'default', ?, 2, 'same',
             '第二条', 'https://example.com/2', '  OpenAI\t发布  GPT  ')
        """,
        [NOW, NOW],
    )
    connection.execute(
        """
        INSERT INTO newsflash_occurrences (
            capture_id, site, board_key, observed_at, position,
            source_item_id, title, content, summary, content_status,
            url, is_important, tags_json, images_json, symbols_json,
            metrics_json
        ) VALUES (
            'capture-news', 'flash', 'range=WEEK&type=1', ?, 1,
            'news-1', '① 热点', '正文内容', NULL, 'full',
            'https://example.com/news', false, '[]', '[]', '[]', '{}'
        )
        """,
        [NOW],
    )
    connection.execute(
        """
        INSERT INTO gold_observations (
            capture_id, site, board_key, observed_at, source_item_id,
            title, sell_price, recycle_price, description, url
        ) VALUES (
            'capture-gold', 'gold', 'hot', ?, 'au9999',
            '足金', 800, 700, '今日 金价', 'https://example.com/gold'
        )
        """,
        [NOW],
    )
    connection.execute("CHECKPOINT")
    connection.close()


def _content_checksum(path: Path) -> str:
    connection = duckdb.connect(str(path), read_only=True)
    rows: list[tuple] = []
    rows.extend(
        connection.execute(
            """
            SELECT 'capture', capture_id, site, path_type,
                   CAST(params_json AS VARCHAR), kind, item_count, content_hash
            FROM captures ORDER BY capture_id
            """
        ).fetchall()
    )
    rows.extend(
        connection.execute(
            """
            SELECT 'hotlist', capture_id, position, source_item_id,
                   title, url, description
            FROM hotlist_observations ORDER BY capture_id, position
            """
        ).fetchall()
    )
    rows.extend(
        connection.execute(
            """
            SELECT 'newsflash', capture_id, position, source_item_id,
                   title, content, summary, url
            FROM newsflash_occurrences ORDER BY capture_id, position
            """
        ).fetchall()
    )
    rows.extend(
        connection.execute(
            """
            SELECT 'gold', capture_id, source_item_id, title,
                   sell_price, recycle_price, description, url
            FROM gold_observations ORDER BY capture_id, source_item_id
            """
        ).fetchall()
    )
    connection.close()
    payload = json.dumps(rows, ensure_ascii=False, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def _columns(path: Path, table: str) -> set[str]:
    connection = duckdb.connect(str(path), read_only=True)
    values = {
        row[0]
        for row in connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = ?
            """,
            [table],
        ).fetchall()
    }
    connection.close()
    return values


def test_v1_fixture_migrates_with_backup_backfill_and_validation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.duckdb"
    _create_v1_fixture(database)
    before_checksum = _content_checksum(database)

    writer = SchedulerDuckDBWriter(database)
    writer.close()

    assert _content_checksum(database) == before_checksum
    connection = duckdb.connect(str(database), read_only=True)
    migrations = connection.execute(
        """
        SELECT version, name, status, backup_path, backup_sha256
        FROM schema_migrations ORDER BY version
        """
    ).fetchall()
    assert [(row[0], row[1], row[2]) for row in migrations] == [
        (1, "initial_history_schema", "completed"),
        (2, "evidence_identity_and_search", "completed"),
        (3, "structured_gold_quotes", "completed"),
    ]
    backup = Path(migrations[1][3])
    assert backup.is_file()
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == migrations[1][4]
    gold_backup = Path(migrations[2][3])
    assert gold_backup.is_file()
    assert hashlib.sha256(gold_backup.read_bytes()).hexdigest() == migrations[2][4]
    assert connection.execute(
        "SELECT capture_id, board_key FROM captures ORDER BY capture_id"
    ).fetchall() == [
        ("capture-gold", "hot"),
        ("capture-hot", "hot"),
        ("capture-news", "type=1&range=WEEK"),
    ]
    for table in (
        "hotlist_observations",
        "newsflash_occurrences",
        "gold_observations",
    ):
        mismatches = connection.execute(
            f"""
            SELECT COUNT(*) FROM {table}
            JOIN captures USING (capture_id)
            WHERE {table}.board_key <> captures.board_key
            """
        ).fetchone()[0]
        assert mismatches == 0
    sequence_values = connection.execute(
        "SELECT ingest_sequence FROM history_items ORDER BY ingest_sequence"
    ).fetchall()
    assert sequence_values == [(1,), (2,), (3,), (4,)]
    assert connection.execute(
        """
        SELECT title, search_text_normalized
        FROM hotlist_observations ORDER BY position
        """
    ).fetchall() == [
        ("ＡＩ  NEWS", "ai news strasse"),
        ("第二条", "第二条 openai 发布 gpt"),
    ]
    assert (
        connection.execute(
            """
        SELECT search_text_normalized FROM newsflash_occurrences
        """
        ).fetchone()[0]
        == "1 热点 正文内容"
    )
    connection.close()

    backups_before = sorted(tmp_path.glob("legacy.duckdb.pre-v2.*.bak"))
    writer = SchedulerDuckDBWriter(database)
    writer.close()
    assert sorted(tmp_path.glob("legacy.duckdb.pre-v2.*.bak")) == backups_before


def test_verified_backup_can_restore_legacy_fixture(tmp_path: Path) -> None:
    database = tmp_path / "restore.duckdb"
    _create_v1_fixture(database)
    before_checksum = _content_checksum(database)
    writer = SchedulerDuckDBWriter(database)
    writer.close()
    connection = duckdb.connect(str(database), read_only=True)
    backup_path, backup_hash = connection.execute(
        """
        SELECT backup_path, backup_sha256
        FROM schema_migrations WHERE version = 2
        """
    ).fetchone()
    connection.close()

    restore_database_backup(
        database,
        backup_path,
        expected_sha256=backup_hash,
    )

    assert _content_checksum(database) == before_checksum
    assert "ingest_sequence" not in _columns(database, "hotlist_observations")
    connection = duckdb.connect(str(database), read_only=True)
    assert connection.execute(
        "SELECT version, status FROM schema_migrations ORDER BY version"
    ).fetchall() == [(1, "completed")]
    connection.close()


def test_insufficient_space_records_failure_and_never_opens_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "no-space.duckdb"
    _create_v1_fixture(database)
    before_checksum = _content_checksum(database)
    DiskUsage = namedtuple("DiskUsage", "total used free")
    monkeypatch.setattr(
        "whats_hot_api.history.migrations.shutil.disk_usage",
        lambda _path: DiskUsage(1, 1, 0),
    )

    with pytest.raises(MigrationDiskSpaceError):
        SchedulerDuckDBWriter(database)

    assert _content_checksum(database) == before_checksum
    assert "ingest_sequence" not in _columns(database, "hotlist_observations")
    connection = duckdb.connect(str(database), read_only=True)
    status, error_message, backup_path = connection.execute(
        """
        SELECT status, error_message, backup_path
        FROM schema_migrations WHERE version = 2
        """
    ).fetchone()
    connection.close()
    assert status == "failed"
    assert "Insufficient free space" in error_message
    assert backup_path is not None
    assert Path(backup_path).exists() is False


def test_ambiguous_legacy_identity_rolls_back_and_keeps_verified_backup(
    tmp_path: Path,
) -> None:
    database = tmp_path / "ambiguous.duckdb"
    _create_v1_fixture(database, ambiguous=True)
    before_checksum = _content_checksum(database)

    with pytest.raises(MigrationAmbiguityError):
        SchedulerDuckDBWriter(database)

    assert _content_checksum(database) == before_checksum
    assert "ingest_sequence" not in _columns(database, "hotlist_observations")
    connection = duckdb.connect(str(database), read_only=True)
    status, backup_path, backup_hash = connection.execute(
        """
        SELECT status, backup_path, backup_sha256
        FROM schema_migrations WHERE version = 2
        """
    ).fetchone()
    connection.close()
    assert status == "failed"
    backup = Path(backup_path)
    assert backup.is_file()
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == backup_hash


def test_failed_index_finalizer_blocks_writer_and_resumes_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "finalizer-failure.duckdb"
    _create_v1_fixture(database)

    with monkeypatch.context() as context:
        context.setattr(
            "whats_hot_api.history.migrations.V2_INDEXES_SQL",
            "CREATE INDEX invalid_migration_sql",
        )
        with pytest.raises(MigrationError):
            SchedulerDuckDBWriter(database)

    connection = duckdb.connect(str(database), read_only=True)
    assert (
        connection.execute(
            "SELECT status FROM schema_migrations WHERE version = 2"
        ).fetchone()[0]
        == "failed"
    )
    assert "ingest_sequence" in _columns(database, "hotlist_observations")
    connection.close()

    writer = SchedulerDuckDBWriter(database)
    writer.close()

    connection = duckdb.connect(str(database), read_only=True)
    assert (
        connection.execute(
            "SELECT status FROM schema_migrations WHERE version = 2"
        ).fetchone()[0]
        == "completed"
    )
    assert (
        connection.execute(
            "SELECT COUNT(DISTINCT ingest_sequence) FROM history_items"
        ).fetchone()[0]
        == 4
    )
    connection.close()
    assert len(list(tmp_path.glob("finalizer-failure.duckdb.pre-v2.*.bak"))) == 1

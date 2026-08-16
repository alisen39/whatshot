"""Ordered, fail-closed DuckDB history schema migrations."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from whats_hot_api.fetch import canonical_board_key
from whats_hot_api.history.schema import (
    GOLD_QUOTES_V3_SQL,
    HISTORY_ITEMS_V2_SQL,
    HISTORY_ITEMS_V3_SQL,
    SCHEMA_MIGRATIONS_SQL,
    SCHEMA_V1_SQL,
    SCHEMA_VERSION,
    V2_INDEXES_SQL,
)
from whats_hot_api.history.text import evidence_search_text

_EVIDENCE_TABLES = (
    "hotlist_observations",
    "newsflash_occurrences",
    "gold_observations",
)
_MIN_FREE_BYTES = 1024 * 1024


class MigrationError(RuntimeError):
    """A schema migration could not be applied or safely verified."""


class MigrationDiskSpaceError(MigrationError):
    """The database volume cannot safely hold a backup and migration work."""


class MigrationAmbiguityError(MigrationError):
    """Legacy identity data cannot be mapped without guessing."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Any], None]
    backup: bool = True
    finalize: Callable[[Any], None] | None = None


@dataclass(frozen=True, slots=True)
class BackupArtifact:
    path: Path
    sha256: str


def _apply_v1(connection: Any) -> None:
    connection.execute(SCHEMA_V1_SQL)


def _apply_v2(connection: Any) -> None:
    connection.execute("DROP VIEW IF EXISTS history_items")
    connection.execute("DROP INDEX IF EXISTS idx_hotlist_site_board_time")
    connection.execute("DROP INDEX IF EXISTS idx_hotlist_item_time")
    _add_v2_columns(connection)
    mappings = _canonical_capture_mappings(connection)
    _backfill_board_keys(connection, mappings)
    _backfill_ingest_sequences(connection)
    _backfill_search_text(connection)
    connection.execute(HISTORY_ITEMS_V2_SQL)
    _validate_v2(connection, mappings)


def _finalize_v2(connection: Any) -> None:
    # DuckDB rejects CREATE INDEX while the same transaction still has
    # outstanding UPDATEs. Build indexes only after the validated data
    # transaction commits; the migration remains "running" until this
    # idempotent finalizer succeeds, so a failure never opens the writer.
    connection.execute(V2_INDEXES_SQL)


def _apply_v3(connection: Any) -> None:
    connection.execute("DROP VIEW IF EXISTS history_items")
    connection.execute("DROP INDEX IF EXISTS idx_gold_site_board_sequence")
    connection.execute("DROP INDEX IF EXISTS idx_gold_ingest_sequence")
    connection.execute(GOLD_QUOTES_V3_SQL)
    connection.execute(
        """
        INSERT INTO gold_quote_observations (
            capture_id, site, board_key, observed_at, source_item_id,
            quote_index, series_key, quote_type, label, price, currency,
            unit, source_quote_at, source_quote_time_trusted
        )
        SELECT
            capture_id,
            site,
            board_key,
            observed_at,
            source_item_id,
            0,
            board_key || ':' || source_item_id || ':retail_sell:CNY:gram',
            'retail_sell',
            '销售价',
            sell_price,
            'CNY',
            'gram',
            price_date,
            price_date IS NOT NULL
        FROM gold_observations
        WHERE sell_price IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM gold_quote_observations q
              WHERE q.capture_id = gold_observations.capture_id
                AND q.source_item_id = gold_observations.source_item_id
                AND q.quote_index = 0
          )
        UNION ALL
        SELECT
            capture_id,
            site,
            board_key,
            observed_at,
            source_item_id,
            1,
            board_key || ':' || source_item_id || ':buyback:CNY:gram',
            'buyback',
            '回收价',
            recycle_price,
            'CNY',
            'gram',
            price_date,
            price_date IS NOT NULL
        FROM gold_observations
        WHERE recycle_price IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM gold_quote_observations q
              WHERE q.capture_id = gold_observations.capture_id
                AND q.source_item_id = gold_observations.source_item_id
                AND q.quote_index = 1
          )
        """
    )
    connection.execute(HISTORY_ITEMS_V3_SQL)
    columns = {
        row[0]
        for row in connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main'
              AND table_name = 'gold_observations'
            """
        ).fetchall()
    }
    if not {"metal", "quotes_json"}.issubset(columns):
        raise MigrationError("Gold quote migration did not add required columns.")


def _finalize_v3(connection: Any) -> None:
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_gold_site_board_sequence
        ON gold_observations(site, board_key, observed_at, ingest_sequence);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_gold_ingest_sequence
        ON gold_observations(ingest_sequence);

        CREATE INDEX IF NOT EXISTS idx_gold_quote_series_time
        ON gold_quote_observations(site, board_key, series_key, observed_at);
        """
    )


MIGRATIONS = (
    Migration(1, "initial_history_schema", _apply_v1, backup=False),
    Migration(
        2,
        "evidence_identity_and_search",
        _apply_v2,
        finalize=_finalize_v2,
    ),
    Migration(
        3,
        "structured_gold_quotes",
        _apply_v3,
        finalize=_finalize_v3,
    ),
)


class MigrationRunner:
    """Apply every pending migration in order before writes are allowed."""

    def __init__(
        self,
        connection: Any,
        database_path: str | Path,
        *,
        database_existed: bool,
    ) -> None:
        self.connection = connection
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_existed = database_existed

    def run(self) -> None:
        self._bootstrap_metadata()
        self._validate_chain()
        for migration in MIGRATIONS:
            row = self._migration_row(migration.version)
            if row and row[1] == "completed":
                if row[0] != migration.name:
                    raise MigrationError(
                        f"Migration {migration.version} name mismatch: {row[0]!r}."
                    )
                continue
            self._run_one(migration, row)

        completed = self.connection.execute(
            "SELECT MAX(version) FROM schema_migrations WHERE status = 'completed'"
        ).fetchone()[0]
        if completed != SCHEMA_VERSION:
            raise MigrationError(
                f"History schema stopped at version {completed!r}; "
                f"expected {SCHEMA_VERSION}."
            )

    def _bootstrap_metadata(self) -> None:
        self.connection.execute(SCHEMA_MIGRATIONS_SQL)
        columns = {
            row[0]
            for row in self.connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'main'
                  AND table_name = 'schema_migrations'
                """
            ).fetchall()
        }
        additions = {
            "status": "VARCHAR DEFAULT 'completed'",
            "started_at": "TIMESTAMPTZ",
            "finished_at": "TIMESTAMPTZ",
            "error_message": "VARCHAR",
            "backup_path": "VARCHAR",
            "backup_sha256": "VARCHAR",
        }
        for name, definition in additions.items():
            if name not in columns:
                self.connection.execute(
                    f"ALTER TABLE schema_migrations ADD COLUMN {name} {definition}"
                )
        self.connection.execute(
            """
            UPDATE schema_migrations
            SET status = COALESCE(status, 'completed'),
                started_at = COALESCE(started_at, applied_at),
                finished_at = CASE
                    WHEN COALESCE(status, 'completed') = 'completed'
                    THEN COALESCE(finished_at, applied_at)
                    ELSE finished_at
                END
            """
        )

    def _validate_chain(self) -> None:
        rows = self.connection.execute(
            "SELECT version, name, status FROM schema_migrations ORDER BY version"
        ).fetchall()
        known = {migration.version: migration for migration in MIGRATIONS}
        for version, name, status in rows:
            migration = known.get(version)
            if migration is None:
                raise MigrationError(
                    f"Database schema version {version} is newer than this application."
                )
            if name != migration.name:
                raise MigrationError(f"Migration {version} name mismatch: {name!r}.")
            if status not in {"running", "completed", "failed"}:
                raise MigrationError(
                    f"Migration {version} has invalid status {status!r}."
                )
        completed = [
            version for version, _name, status in rows if status == "completed"
        ]
        if completed and completed != list(range(1, max(completed) + 1)):
            raise MigrationError("Completed migrations are not a contiguous sequence.")

    def _migration_row(
        self, version: int
    ) -> tuple[str, str, str | None, str | None] | None:
        row = self.connection.execute(
            """
            SELECT name, status, backup_path, backup_sha256
            FROM schema_migrations
            WHERE version = ?
            """,
            [version],
        ).fetchone()
        return tuple(row) if row else None

    def _run_one(
        self,
        migration: Migration,
        existing: tuple[str, str, str | None, str | None] | None,
    ) -> None:
        backup: BackupArtifact | None = None
        backup_path = Path(existing[2]) if existing and existing[2] else None
        if migration.backup and self.database_existed and backup_path is None:
            backup_path = self._new_backup_path(migration.version)
        try:
            if migration.backup and self.database_existed:
                backup = self._prepare_backup(
                    migration.version,
                    existing_path=backup_path,
                )
            self._record_started(migration, backup)
            self.connection.execute("BEGIN TRANSACTION")
            try:
                migration.apply(self.connection)
                self.connection.execute("COMMIT")
            except Exception:
                self.connection.execute("ROLLBACK")
                raise
            if migration.finalize is not None:
                migration.finalize(self.connection)
            self.connection.execute(
                """
                UPDATE schema_migrations
                SET status = 'completed',
                    finished_at = ?,
                    applied_at = ?,
                    error_message = NULL
                WHERE version = ?
                """,
                [datetime.now(UTC), datetime.now(UTC), migration.version],
            )
        except Exception as exc:
            self._record_failed(migration, exc, backup or backup_path)
            if isinstance(exc, MigrationError):
                raise
            raise MigrationError(
                f"Migration {migration.version} ({migration.name}) failed."
            ) from exc

    def _prepare_backup(
        self,
        version: int,
        *,
        existing_path: Path | None,
    ) -> BackupArtifact:
        self.connection.execute("CHECKPOINT")
        database_size = self.database_path.stat().st_size
        required = max(database_size * 3, _MIN_FREE_BYTES)
        available = shutil.disk_usage(self.database_path.parent).free
        if available < required:
            raise MigrationDiskSpaceError(
                "Insufficient free space for a verified database backup: "
                f"need {required} bytes, have {available}."
            )

        backup_path = existing_path or self._new_backup_path(version)
        if backup_path.exists():
            return BackupArtifact(backup_path, _sha256_file(backup_path))
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = backup_path.with_suffix(backup_path.suffix + ".tmp")
        shutil.copy2(self.database_path, temporary)
        source_hash = _sha256_file(self.database_path)
        backup_hash = _sha256_file(temporary)
        if source_hash != backup_hash:
            temporary.unlink(missing_ok=True)
            raise MigrationError("Database backup checksum verification failed.")
        os.replace(temporary, backup_path)
        return BackupArtifact(backup_path, backup_hash)

    def _new_backup_path(self, version: int) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        return self.database_path.with_name(
            f"{self.database_path.name}.pre-v{version}.{stamp}.bak"
        )

    def _record_started(
        self,
        migration: Migration,
        backup: BackupArtifact | None,
    ) -> None:
        now = datetime.now(UTC)
        self.connection.execute(
            """
            INSERT INTO schema_migrations (
                version, name, applied_at, status, started_at, finished_at,
                error_message, backup_path, backup_sha256
            ) VALUES (?, ?, ?, 'running', ?, NULL, NULL, ?, ?)
            ON CONFLICT (version) DO UPDATE SET
                name = excluded.name,
                status = 'running',
                started_at = excluded.started_at,
                finished_at = NULL,
                error_message = NULL,
                backup_path = COALESCE(excluded.backup_path, schema_migrations.backup_path),
                backup_sha256 = COALESCE(
                    excluded.backup_sha256,
                    schema_migrations.backup_sha256
                )
            """,
            [
                migration.version,
                migration.name,
                now,
                now,
                str(backup.path) if backup else None,
                backup.sha256 if backup else None,
            ],
        )

    def _record_failed(
        self,
        migration: Migration,
        error: Exception,
        backup: BackupArtifact | Path | None,
    ) -> None:
        now = datetime.now(UTC)
        path = backup.path if isinstance(backup, BackupArtifact) else backup
        sha256 = backup.sha256 if isinstance(backup, BackupArtifact) else None
        self.connection.execute(
            """
            INSERT INTO schema_migrations (
                version, name, applied_at, status, started_at, finished_at,
                error_message, backup_path, backup_sha256
            ) VALUES (?, ?, ?, 'failed', ?, ?, ?, ?, ?)
            ON CONFLICT (version) DO UPDATE SET
                status = 'failed',
                finished_at = excluded.finished_at,
                error_message = excluded.error_message,
                backup_path = COALESCE(excluded.backup_path, schema_migrations.backup_path),
                backup_sha256 = COALESCE(
                    excluded.backup_sha256,
                    schema_migrations.backup_sha256
                )
            """,
            [
                migration.version,
                migration.name,
                now,
                now,
                now,
                str(error)[:1000],
                str(path) if path else None,
                sha256,
            ],
        )


def restore_database_backup(
    database_path: str | Path,
    backup_path: str | Path,
    *,
    expected_sha256: str | None = None,
) -> None:
    """Restore a closed database from one verified migration backup."""

    target = Path(database_path).expanduser().resolve()
    source = Path(backup_path).expanduser().resolve()
    if not source.is_file():
        raise MigrationError(f"Migration backup does not exist: {source}")
    source_hash = _sha256_file(source)
    if expected_sha256 is not None and source_hash != expected_sha256:
        raise MigrationError("Migration backup checksum does not match its record.")
    wal = Path(f"{target}.wal")
    if wal.exists():
        raise MigrationError("Refusing restore while a DuckDB WAL file exists.")
    temporary = target.with_suffix(target.suffix + ".restore.tmp")
    shutil.copy2(source, temporary)
    if _sha256_file(temporary) != source_hash:
        temporary.unlink(missing_ok=True)
        raise MigrationError("Restored database checksum verification failed.")
    os.replace(temporary, target)


def _add_v2_columns(connection: Any) -> None:
    for table in _EVIDENCE_TABLES:
        columns = _table_columns(connection, table)
        if "ingest_sequence" not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN ingest_sequence BIGINT")
        if "search_text_normalized" not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN search_text_normalized VARCHAR"
            )


def _canonical_capture_mappings(connection: Any) -> list[tuple[str, str, str, str]]:
    rows = connection.execute(
        """
        SELECT capture_id, site, board_key, path_type, CAST(params_json AS VARCHAR)
        FROM captures
        ORDER BY capture_id
        """
    ).fetchall()
    mappings: list[tuple[str, str, str, str]] = []
    identities: dict[tuple[str, str], set[str]] = {}
    for capture_id, site, legacy_key, path_type, params_json in rows:
        canonical = _canonical_legacy_key(
            legacy_key=str(legacy_key),
            path_type=str(path_type),
            params_json=str(params_json),
        )
        mappings.append((str(capture_id), str(site), str(legacy_key), canonical))
        identities.setdefault((str(site), str(legacy_key)), set()).add(canonical)
    collisions = {
        identity: values for identity, values in identities.items() if len(values) > 1
    }
    if collisions:
        raise MigrationAmbiguityError(
            "A legacy (site, board_key) identity maps to multiple canonical keys: "
            f"{collisions!r}"
        )
    return mappings


def _canonical_legacy_key(
    *,
    legacy_key: str,
    path_type: str,
    params_json: str,
) -> str:
    try:
        decoded = json.loads(params_json)
    except json.JSONDecodeError as exc:
        raise MigrationAmbiguityError(
            "captures.params_json is not valid JSON."
        ) from exc
    if not isinstance(decoded, dict):
        raise MigrationAmbiguityError("captures.params_json must be a JSON object.")
    if any(
        not isinstance(key, str) or not key or not isinstance(value, str) or not value
        for key, value in decoded.items()
    ):
        raise MigrationAmbiguityError(
            "Legacy capture params must contain non-empty string keys and values."
        )
    if "type" in decoded:
        raise MigrationAmbiguityError(
            "Legacy capture params repeat the path type dimension."
        )
    params = dict(decoded)
    if legacy_key in {"hot", "default"}:
        if params:
            raise MigrationAmbiguityError(
                f"Legacy key {legacy_key!r} omits stored params {sorted(params)}."
            )
        return "hot"

    try:
        pairs = parse_qsl(
            legacy_key,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise MigrationAmbiguityError(
            f"Legacy board key {legacy_key!r} is not a query-string identity."
        ) from exc
    if not pairs or len({key for key, _value in pairs}) != len(pairs):
        raise MigrationAmbiguityError(
            f"Legacy board key {legacy_key!r} contains duplicate or empty dimensions."
        )
    encoded = dict(pairs)
    encoded_type = encoded.pop("type", None)
    if encoded_type is not None and encoded_type != path_type:
        raise MigrationAmbiguityError(
            f"Legacy board key type {encoded_type!r} disagrees with path_type "
            f"{path_type!r}."
        )
    if encoded != params:
        raise MigrationAmbiguityError(
            f"Legacy board key dimensions {encoded!r} disagree with params {params!r}."
        )
    declared = set(params)
    if encoded_type is not None:
        declared.add("type")
    try:
        return canonical_board_key(
            path_type=path_type,
            params=params,
            declared_dimensions=declared,
        )
    except ValueError as exc:
        raise MigrationAmbiguityError(
            f"Legacy board key {legacy_key!r} cannot become Contract v1 identity."
        ) from exc


def _backfill_board_keys(
    connection: Any,
    mappings: list[tuple[str, str, str, str]],
) -> None:
    mismatches = connection.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT capture_id, board_key FROM hotlist_observations
            UNION ALL
            SELECT capture_id, board_key FROM newsflash_occurrences
            UNION ALL
            SELECT capture_id, board_key FROM gold_observations
        ) evidence
        JOIN captures USING (capture_id)
        WHERE evidence.board_key <> captures.board_key
        """
    ).fetchone()[0]
    if mismatches:
        raise MigrationAmbiguityError(
            f"{mismatches} evidence rows disagree with their capture board key."
        )
    for capture_id, _site, _legacy, canonical in mappings:
        connection.execute(
            "UPDATE captures SET board_key = ? WHERE capture_id = ?",
            [canonical, capture_id],
        )
        for table in _EVIDENCE_TABLES:
            connection.execute(
                f"UPDATE {table} SET board_key = ? WHERE capture_id = ?",
                [canonical, capture_id],
            )


def _backfill_ingest_sequences(connection: Any) -> None:
    total = sum(
        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in _EVIDENCE_TABLES
    )
    populated = sum(
        connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE ingest_sequence IS NOT NULL"
        ).fetchone()[0]
        for table in _EVIDENCE_TABLES
    )
    if populated not in {0, total}:
        raise MigrationError("Evidence ingest_sequence backfill is partial.")
    if total and populated == 0:
        connection.execute(
            """
            CREATE TEMP TABLE migration_v2_ingest AS
            SELECT
                kind,
                capture_id,
                row_key,
                row_number() OVER (
                    ORDER BY observed_at, capture_id, kind, row_key
                ) AS ingest_sequence
            FROM (
                SELECT
                    'hotlist' AS kind,
                    capture_id,
                    lpad(CAST(position AS VARCHAR), 12, '0') AS row_key,
                    observed_at
                FROM hotlist_observations
                UNION ALL
                SELECT
                    'newsflash' AS kind,
                    capture_id,
                    lpad(CAST(position AS VARCHAR), 12, '0') AS row_key,
                    observed_at
                FROM newsflash_occurrences
                UNION ALL
                SELECT
                    'gold' AS kind,
                    capture_id,
                    source_item_id AS row_key,
                    observed_at
                FROM gold_observations
            ) evidence
            """
        )
        connection.execute(
            """
            UPDATE hotlist_observations AS target
            SET ingest_sequence = migration.ingest_sequence
            FROM migration_v2_ingest AS migration
            WHERE migration.kind = 'hotlist'
              AND migration.capture_id = target.capture_id
              AND migration.row_key = lpad(CAST(target.position AS VARCHAR), 12, '0')
            """
        )
        connection.execute(
            """
            UPDATE newsflash_occurrences AS target
            SET ingest_sequence = migration.ingest_sequence
            FROM migration_v2_ingest AS migration
            WHERE migration.kind = 'newsflash'
              AND migration.capture_id = target.capture_id
              AND migration.row_key = lpad(CAST(target.position AS VARCHAR), 12, '0')
            """
        )
        connection.execute(
            """
            UPDATE gold_observations AS target
            SET ingest_sequence = migration.ingest_sequence
            FROM migration_v2_ingest AS migration
            WHERE migration.kind = 'gold'
              AND migration.capture_id = target.capture_id
              AND migration.row_key = target.source_item_id
            """
        )
        connection.execute("DROP TABLE migration_v2_ingest")

    next_value = total + 1
    connection.execute(
        f"CREATE SEQUENCE IF NOT EXISTS evidence_ingest_sequence START {next_value}"
    )
    for table in _EVIDENCE_TABLES:
        connection.execute(
            f"ALTER TABLE {table} ALTER COLUMN ingest_sequence "
            "SET DEFAULT nextval('evidence_ingest_sequence')"
        )


def _backfill_search_text(connection: Any) -> None:
    definitions = (
        ("hotlist_observations", "position", "description"),
        (
            "newsflash_occurrences",
            "position",
            "COALESCE(summary, content)",
        ),
        ("gold_observations", "source_item_id", "description"),
    )
    for table, row_key, description_sql in definitions:
        rows = connection.execute(
            f"""
            SELECT capture_id, {row_key}, title, {description_sql}
            FROM {table}
            WHERE search_text_normalized IS NULL
            """
        ).fetchall()
        for capture_id, row_id, title, description in rows:
            normalized = evidence_search_text(str(title), description)
            connection.execute(
                f"""
                UPDATE {table}
                SET search_text_normalized = ?
                WHERE capture_id = ? AND {row_key} = ?
                """,
                [normalized, capture_id, row_id],
            )


def _validate_v2(
    connection: Any,
    mappings: list[tuple[str, str, str, str]],
) -> None:
    total = sum(
        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in _EVIDENCE_TABLES
    )
    stats = connection.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT ingest_sequence),
            MIN(ingest_sequence),
            MAX(ingest_sequence),
            COUNT(*) FILTER (WHERE search_text_normalized IS NULL)
        FROM history_items
        """
    ).fetchone()
    expected_min = 1 if total else None
    expected_max = total if total else None
    if tuple(stats) != (total, total, expected_min, expected_max, 0):
        raise MigrationError(f"Evidence v2 validation failed: {tuple(stats)!r}.")

    expected = {
        capture_id: canonical for capture_id, _site, _old, canonical in mappings
    }
    actual = dict(
        connection.execute("SELECT capture_id, board_key FROM captures").fetchall()
    )
    for capture_id, canonical in expected.items():
        if actual.get(capture_id) != canonical:
            raise MigrationError(
                f"Capture {capture_id!r} was not assigned canonical board key."
            )
    mismatches = connection.execute(
        """
        SELECT COUNT(*)
        FROM history_items
        JOIN captures USING (capture_id)
        WHERE history_items.board_key <> captures.board_key
        """
    ).fetchone()[0]
    if mismatches:
        raise MigrationError(f"{mismatches} evidence rows failed board key validation.")


def _table_columns(connection: Any, table: str) -> set[str]:
    return {
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

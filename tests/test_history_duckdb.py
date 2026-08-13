from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from whats_hot_api.fetch import FetchRequest, FetchResult
from whats_hot_api.history import HistoryReader
from whats_hot_api.history.errors import (
    HistoryCursorError,
    HistoryCursorExpiredError,
)
from whats_hot_api.history.models import CaptureBatch, RunStart
from whats_hot_api.models import GoldItem, ListItem, NewsFlashItem, RouterData
from whats_hot_api.scheduler.storage import SchedulerDuckDBWriter


def _run(key: str, observed_at: datetime) -> RunStart:
    return RunStart(
        run_id=f"run-{key}",
        run_key=key,
        job_id="demo-job",
        trigger_kind="interval",
        scheduled_for=observed_at,
        started_at=observed_at,
    )


def _hotlist_batch(key: str, observed_at: datetime) -> CaptureBatch:
    request = FetchRequest(
        site="demo",
        path_type="hot",
    )
    return CaptureBatch(
        capture_id=f"capture-{key}",
        run=_run(key, observed_at),
        board_key="hot",
        fetch_result=FetchResult(
            request=request,
            observed_at=observed_at,
            data=RouterData(
                name="demo",
                title="Demo",
                type="热门",
                total=2,
                fromCache=False,
                updateTime=observed_at.isoformat(),
                data=[
                    ListItem(
                        id="one",
                        title="人工智能",
                        hot=100,
                        url="https://example.com/one",
                    ),
                    ListItem(
                        id="two",
                        title="第二条",
                        hot=50,
                        url="https://example.com/two",
                    ),
                ],
            ),
        ),
    )


def _newsflash_batch(key: str, observed_at: datetime) -> CaptureBatch:
    request = FetchRequest(
        site="flash",
        path_type="global",
    )
    return CaptureBatch(
        capture_id=f"capture-{key}",
        run=_run(key, observed_at),
        board_key="type=global",
        fetch_result=FetchResult(
            request=request,
            observed_at=observed_at,
            data=RouterData(
                kind="newsflash",
                name="flash",
                title="Flash",
                type="全球",
                total=1,
                fromCache=False,
                updateTime=observed_at.isoformat(),
                data=[
                    NewsFlashItem(
                        id="flash-one",
                        title="AI 快讯",
                        content="人工智能取得新进展",
                        source="测试源",
                        url="https://example.com/flash",
                    )
                ],
            ),
        ),
    )


def _gold_batch(key: str, observed_at: datetime) -> CaptureBatch:
    request = FetchRequest(
        site="gold",
        path_type="hot",
    )
    return CaptureBatch(
        capture_id=f"capture-{key}",
        run=_run(key, observed_at),
        board_key="hot",
        fetch_result=FetchResult(
            request=request,
            observed_at=observed_at,
            data=RouterData(
                kind="gold",
                name="gold",
                title="Gold",
                type="金价",
                total=1,
                fromCache=False,
                updateTime=observed_at.isoformat(),
                data=[
                    GoldItem(
                        id="au9999",
                        title="足金",
                        sellPrice=800,
                        recyclePrice=700,
                        url="https://example.com/gold",
                    )
                ],
            ),
        ),
    )


def test_new_database_uses_one_complete_initial_schema(tmp_path: Path) -> None:
    database = tmp_path / "whatshot.duckdb"
    writer = SchedulerDuckDBWriter(database)
    writer.close()

    connection = duckdb.connect(str(database), read_only=True)
    versions = connection.execute(
        "SELECT version, name FROM schema_migrations ORDER BY version"
    ).fetchall()
    tables = {
        row[0]
        for row in connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
              AND table_type = 'BASE TABLE'
            """
        ).fetchall()
    }
    occurrence_columns = {
        row[0]
        for row in connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main'
              AND table_name = 'newsflash_occurrences'
            """
        ).fetchall()
    }
    connection.close()

    assert versions == [
        (1, "initial_history_schema"),
        (2, "evidence_identity_and_search"),
    ]
    assert "scheduler_jobs" not in tables
    assert "newsflash_item_sightings" not in tables
    assert {
        "title",
        "content",
        "summary",
        "url",
        "tags_json",
        "published_at",
        "ingest_sequence",
        "search_text_normalized",
    } <= occurrence_columns


def test_scheduler_writer_and_history_reader_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "whatshot.duckdb"
    writer = SchedulerDuckDBWriter(database)
    observed_at = datetime.now(UTC) - timedelta(minutes=5)
    batch = _hotlist_batch("one", observed_at)

    writer.record_run_started(batch.run)
    assert writer.persist_capture(batch) == batch.capture_id
    assert writer.persist_capture(batch) == batch.capture_id

    reader = HistoryReader(database)
    page = reader.query_history(
        site="demo",
        board_key="hot",
        since=observed_at - timedelta(minutes=1),
        until=observed_at + timedelta(minutes=1),
        limit=1,
    )
    assert len(page["items"]) == 1
    assert page["truncated"] is True
    assert page["nextCursor"]
    assert page["items"][0]["captureId"] == batch.capture_id

    second = reader.query_history(
        site="demo",
        board_key="hot",
        since=observed_at - timedelta(minutes=1),
        until=observed_at + timedelta(minutes=1),
        limit=1,
        cursor=page["nextCursor"],
    )
    assert len(second["items"]) == 1

    search = reader.search_history(
        "人工智能",
        since=observed_at - timedelta(minutes=1),
        until=observed_at + timedelta(minutes=1),
    )
    assert search["items"][0]["itemId"] == "one"

    trend = reader.get_trend_series(
        site="demo",
        board_key="hot",
        item_id="one",
        since=observed_at - timedelta(minutes=1),
        until=observed_at + timedelta(minutes=1),
    )
    assert trend["series"][0]["samples"] == 1
    stats = reader.get_storage_stats()
    assert stats["enabled"] is True
    assert stats["captures"] == 1
    capture = reader.get_capture(batch.capture_id)
    assert capture["captureId"] == batch.capture_id
    assert len(capture["items"]) == 2
    assert reader.get_capture("missing") is None
    reader.close()
    writer.close()

    connection = duckdb.connect(str(database), read_only=True)
    assert connection.execute(
        """
        SELECT ingest_sequence, search_text_normalized
        FROM hotlist_observations
        ORDER BY ingest_sequence
        """
    ).fetchall() == [
        (1, "人工智能"),
        (2, "第二条"),
    ]
    connection.close()


def test_history_reads_legacy_default_rows_through_hot_alias(tmp_path: Path) -> None:
    database = tmp_path / "whatshot.duckdb"
    writer = SchedulerDuckDBWriter(database)
    observed_at = datetime.now(UTC) - timedelta(minutes=1)
    batch = _hotlist_batch("legacy-default", observed_at)
    writer.persist_capture(batch)
    writer.close()

    connection = duckdb.connect(str(database))
    connection.execute(
        "UPDATE captures SET board_key = 'default' WHERE capture_id = ?",
        [batch.capture_id],
    )
    connection.execute(
        "UPDATE hotlist_observations SET board_key = 'default' WHERE capture_id = ?",
        [batch.capture_id],
    )
    connection.close()

    reader = HistoryReader(database)
    page = reader.query_history(
        site="demo",
        board_key="hot",
        since=observed_at - timedelta(minutes=1),
        until=observed_at + timedelta(minutes=1),
    )
    assert len(page["items"]) == 2
    assert {item["boardKey"] for item in page["items"]} == {"hot"}
    reader.close()


def test_newsflash_is_deduplicated_but_occurrences_are_preserved(
    tmp_path: Path,
) -> None:
    database = tmp_path / "whatshot.duckdb"
    writer = SchedulerDuckDBWriter(database)
    now = datetime.now(UTC)
    writer.persist_capture(_newsflash_batch("first", now - timedelta(minutes=1)))
    writer.persist_capture(_newsflash_batch("second", now))

    reader = HistoryReader(database)
    page = reader.search_history(
        "新进展",
        site="flash",
        since=now - timedelta(hours=1),
        until=now + timedelta(minutes=1),
    )
    assert len(page["items"]) == 2
    assert reader.get_storage_stats()["newsflashItems"] == 1
    reader.close()
    writer.close()


def test_newsflash_capture_preserves_content_observed_at_that_time(
    tmp_path: Path,
) -> None:
    database = tmp_path / "whatshot.duckdb"
    writer = SchedulerDuckDBWriter(database)
    now = datetime.now(UTC)
    first = _newsflash_batch("old", now - timedelta(minutes=1))
    second = _newsflash_batch("new", now)
    first_item = first.fetch_result.data.data[0]
    second_item = second.fetch_result.data.data[0]
    first_item.title = "旧标题"
    first_item.content = "旧正文"
    second_item.title = "新标题"
    second_item.content = "新正文"

    writer.persist_capture(first)
    writer.persist_capture(second)

    reader = HistoryReader(database)
    old_capture = reader.get_capture(first.capture_id)
    new_capture = reader.get_capture(second.capture_id)
    assert old_capture["items"][0]["title"] == "旧标题"
    assert old_capture["items"][0]["content"] == "旧正文"
    assert new_capture["items"][0]["title"] == "新标题"
    assert new_capture["items"][0]["content"] == "新正文"
    reader.close()
    writer.close()


def test_cursor_pagination_keeps_duplicate_item_ids(tmp_path: Path) -> None:
    database = tmp_path / "whatshot.duckdb"
    writer = SchedulerDuckDBWriter(database)
    now = datetime.now(UTC)
    batch = _hotlist_batch("duplicate-items", now)
    batch.fetch_result.data.data[0].id = "same"
    batch.fetch_result.data.data[1].id = "same"
    writer.persist_capture(batch)

    reader = HistoryReader(database)
    query = {
        "since": now - timedelta(seconds=1),
        "until": now + timedelta(seconds=1),
        "limit": 1,
    }
    first = reader.query_history(**query)
    second = reader.query_history(**query, cursor=first["nextCursor"])

    assert [item["title"] for item in first["items"]] == ["人工智能"]
    assert [item["title"] for item in second["items"]] == ["第二条"]
    reader.close()
    writer.close()


def test_cursor_snapshot_excludes_concurrent_appends_without_gaps(
    tmp_path: Path,
) -> None:
    database = tmp_path / "whatshot.duckdb"
    writer = SchedulerDuckDBWriter(database)
    observed_at = datetime.now(UTC) - timedelta(minutes=1)
    for key in ("first", "second", "third"):
        writer.persist_capture(_hotlist_batch(key, observed_at))

    reader = HistoryReader(database, cursor_secret=b"snapshot-test-secret-value")
    page = reader.query_history(
        since=observed_at - timedelta(seconds=1),
        until=observed_at + timedelta(minutes=2),
        limit=2,
    )
    snapshot_as_of = page["asOf"]
    initial_ids = [item["evidenceId"] for item in page["items"]]

    writer.persist_capture(
        _hotlist_batch("concurrent", observed_at + timedelta(seconds=1))
    )
    while page["nextCursor"] is not None:
        page = reader.query_history(
            since=observed_at - timedelta(seconds=1),
            until=observed_at + timedelta(minutes=2),
            limit=2,
            cursor=page["nextCursor"],
        )
        assert page["asOf"] == snapshot_as_of
        initial_ids.extend(item["evidenceId"] for item in page["items"])

    assert initial_ids == [f"duckdb:{index:020d}" for index in range(1, 7)]
    assert len(initial_ids) == len(set(initial_ids))
    fresh = reader.query_history(
        since=observed_at - timedelta(seconds=1),
        until=observed_at + timedelta(minutes=2),
    )
    assert len(fresh["items"]) == 8
    reader.close()
    writer.close()


def test_snapshot_lifecycle_and_coverage_exclude_future_observations(
    tmp_path: Path,
) -> None:
    database = tmp_path / "whatshot.duckdb"
    writer = SchedulerDuckDBWriter(database)
    now = datetime.now(UTC)
    past = now - timedelta(minutes=1)
    future = now + timedelta(days=1)
    writer.persist_capture(_hotlist_batch("past", past))
    # This row is already below the ingest watermark when the query begins, so
    # watermark-only snapshots would incorrectly include it in lifecycle and
    # coverage even though it is later than the page's asOf.
    writer.persist_capture(_hotlist_batch("future-clock-skew", future))

    reader = HistoryReader(database)
    page = reader.query_history(
        site="demo",
        board_key="hot",
        since=past - timedelta(minutes=1),
        until=now,
    )
    assert len(page["items"]) == 2
    assert {item["observedAt"] for item in page["items"]} == {past}
    assert {item["lastSeenAt"] for item in page["items"]} == {past}
    assert page["coverage"]["latestAvailableAt"] == past

    coverage = reader.get_data_coverage(site="demo", board_key="hot")
    assert coverage["latestAvailableAt"] == past
    reader.close()
    writer.close()


def test_cursor_is_bound_to_filters_and_normalized_keyword(tmp_path: Path) -> None:
    database = tmp_path / "whatshot.duckdb"
    writer = SchedulerDuckDBWriter(database)
    observed_at = datetime.now(UTC) - timedelta(minutes=1)
    batch = _hotlist_batch("filters", observed_at)
    batch.fetch_result.data.data[0].title = "ＡＩ  NEWS"
    batch.fetch_result.data.data[1].title = "AI second"
    writer.persist_capture(batch)
    reader = HistoryReader(database, cursor_secret=b"filters-test-secret-value!!")
    page = reader.search_history("ＡＩ", limit=1)

    equivalent = reader.search_history(
        "ai",
        limit=1,
        cursor=page["nextCursor"],
    )
    assert [item["title"] for item in equivalent["items"]] == ["AI second"]
    with pytest.raises(HistoryCursorError):
        reader.search_history(
            "ai",
            site="another-site",
            limit=1,
            cursor=page["nextCursor"],
        )
    with pytest.raises(HistoryCursorError):
        reader.query_history(limit=1, cursor=page["nextCursor"])
    reader.close()
    writer.close()


def test_cursor_expiry_has_distinct_domain_error(tmp_path: Path) -> None:
    database = tmp_path / "whatshot.duckdb"
    writer = SchedulerDuckDBWriter(database)
    writer.persist_capture(_hotlist_batch("expiry", datetime.now(UTC)))
    reader = HistoryReader(
        database,
        cursor_secret=b"expiry-test-secret-value!!!!",
        cursor_ttl=timedelta(0),
    )
    page = reader.query_history(limit=1)

    with pytest.raises(HistoryCursorExpiredError):
        reader.query_history(limit=1, cursor=page["nextCursor"])
    reader.close()
    writer.close()


def test_malformed_cursor_has_stable_domain_error(tmp_path: Path) -> None:
    database = tmp_path / "whatshot.duckdb"
    writer = SchedulerDuckDBWriter(database)
    reader = HistoryReader(database)

    with pytest.raises(HistoryCursorError) as exc_info:
        reader.query_history(cursor="W10")

    assert exc_info.value.code == "INVALID_HISTORY_CURSOR"
    reader.close()
    writer.close()


def test_search_treats_sql_wildcards_as_literals(tmp_path: Path) -> None:
    database = tmp_path / "whatshot.duckdb"
    writer = SchedulerDuckDBWriter(database)
    now = datetime.now(UTC)
    writer.persist_capture(_hotlist_batch("literal-search", now))
    reader = HistoryReader(database)
    window = {
        "since": now - timedelta(seconds=1),
        "until": now + timedelta(seconds=1),
    }

    assert reader.search_history("%", **window)["items"] == []
    assert reader.search_history("_", **window)["items"] == []
    assert reader.search_history("\\", **window)["items"] == []
    reader.close()
    writer.close()


def test_gold_observations_and_retention(tmp_path: Path) -> None:
    database = tmp_path / "whatshot.duckdb"
    writer = SchedulerDuckDBWriter(database)
    now = datetime.now(UTC)
    writer.persist_capture(_gold_batch("old-gold", now - timedelta(days=200)))
    writer.persist_capture(_gold_batch("current-gold", now))

    reader = HistoryReader(database)
    page = reader.query_history(
        site="gold",
        kind="gold",
        since=now - timedelta(days=201),
        until=now + timedelta(minutes=1),
    )
    assert len(page["items"]) == 2
    assert page["items"][0]["title"] == "足金"
    reader.close()

    writer.apply_retention(180)
    reader = HistoryReader(database)
    assert reader.get_storage_stats()["captures"] == 1
    assert reader.get_storage_stats()["goldRows"] == 1
    reader.close()
    writer.close()


def test_history_package_does_not_export_writer() -> None:
    from whats_hot_api import history

    assert not hasattr(history, "SchedulerDuckDBWriter")

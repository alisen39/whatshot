from __future__ import annotations

from datetime import UTC
from unittest.mock import AsyncMock

import orjson
from click.testing import CliRunner

from whats_hot_api.cli.main import cli
from whats_hot_api.daemon.client import DaemonClientError
from whats_hot_api.fetch import (
    FetchRequest,
    FetchResult,
    FetchTypeNotFoundError,
)
from whats_hot_api.models import ListItem, RouterData


def _fetch_result(request: FetchRequest) -> FetchResult:
    from datetime import datetime

    return FetchResult(
        request=request,
        observed_at=datetime.now(UTC),
        data=RouterData(
            name=request.site,
            title="Demo",
            type="热榜",
            total=1,
            fromCache=False,
            updateTime="2026-07-31T00:00:00+00:00",
            data=[
                ListItem(
                    id="1",
                    title="测试标题",
                    hot=123,
                    url="https://example.com/1",
                )
            ],
        ),
    )


def test_cli_lists_sources_as_json() -> None:
    result = CliRunner().invoke(cli, ["list", "-f", "json"])

    assert result.exit_code == 0
    payload = orjson.loads(result.stdout)
    assert any(row["name"] == "weibo" for row in payload)
    assert all("defaultType" in row for row in payload)


def test_cli_dynamic_source_fetches_without_persistence(monkeypatch) -> None:
    async def fetch(request: FetchRequest) -> FetchResult:
        return _fetch_result(request)

    monkeypatch.setattr("whats_hot_api.cli.main.fetch_service.fetch", fetch)
    result = CliRunner().invoke(
        cli,
        ["weibo", "hot", "--limit", "1", "-f", "json"],
    )

    assert result.exit_code == 0
    payload = orjson.loads(result.stdout)
    assert payload == [
        {
            "rank": 1,
            "id": "1",
            "title": "测试标题",
            "url": "https://example.com/1",
            "hot": 123,
            "site": "weibo",
            "boardKey": "hot",
        }
    ]


def test_cli_source_uses_default_hot_type(monkeypatch) -> None:
    fetch = AsyncMock()
    fetch.side_effect = lambda request: _fetch_result(request)
    monkeypatch.setattr("whats_hot_api.cli.main.fetch_service.fetch", fetch)

    result = CliRunner().invoke(cli, ["weibo", "-f", "json"])

    assert result.exit_code == 0
    assert fetch.await_args.args[0].path_type == "hot"


def test_cli_fetch_reaches_source_that_conflicts_with_static_command(
    monkeypatch,
) -> None:
    fetch = AsyncMock()
    fetch.side_effect = lambda request: _fetch_result(request)
    monkeypatch.setattr("whats_hot_api.cli.main.fetch_service.fetch", fetch)

    result = CliRunner().invoke(
        cli,
        ["fetch", "history", "hot", "-f", "json"],
    )

    assert result.exit_code == 0
    assert fetch.await_args.args[0].site == "history"


def test_cli_emits_structured_error_to_stderr(monkeypatch) -> None:
    async def fetch(request: FetchRequest) -> FetchResult:
        raise FetchTypeNotFoundError(
            "Unknown type.",
            details={"validTypes": ["hot"]},
        )

    monkeypatch.setattr("whats_hot_api.cli.main.fetch_service.fetch", fetch)
    result = CliRunner().invoke(
        cli,
        ["--error-format", "json", "weibo", "missing", "-f", "json"],
    )

    assert result.exit_code == 66
    assert result.stdout == ""
    payload = orjson.loads(result.stderr)
    assert payload["error"]["code"] == "UNKNOWN_TYPE"


def test_cli_rejects_invalid_param_syntax() -> None:
    result = CliRunner().invoke(
        cli,
        ["weibo", "--param", "missing-equals"],
    )

    assert result.exit_code == 2
    assert "Expected KEY=VALUE" in result.stderr


def test_cli_config_validate_does_not_create_database(tmp_path) -> None:
    config_path = tmp_path / "whatshot.toml"
    database = tmp_path / "whatshot.duckdb"
    config_path.write_text(
        f"""
[storage]
path = "{database}"

[scheduler]
enabled = true

[[scheduler.jobs]]
id = "weibo-hot"
site = "weibo"
type = "hot"
interval = "10m"
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["config", "validate", "--config", str(config_path), "-f", "json"],
    )

    assert result.exit_code == 0
    payload = orjson.loads(result.stdout)
    assert payload["storageEnabled"] is True
    assert payload["jobCount"] == 1
    assert database.exists() is False


def test_cli_config_validate_accepts_disabled_storage_without_files(tmp_path) -> None:
    config_path = tmp_path / "whatshot.toml"
    database = tmp_path / "data" / "whatshot.duckdb"
    config_path.write_text(
        f"""
[storage]
enabled = false
path = "{database}"

[scheduler]
enabled = true
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["config", "validate", "--config", str(config_path), "-f", "json"],
    )

    assert result.exit_code == 0
    payload = orjson.loads(result.stdout)
    assert payload["storageEnabled"] is False
    assert payload["jobCount"] == 0
    assert database.parent.exists() is False


def test_cli_history_queries_daemon(monkeypatch) -> None:
    class FakeClient:
        def get(self, path, *, params=None):
            assert path == "/internal/v1/history"
            assert params["site"] == "weibo"
            return {
                "items": [{"title": "历史结果", "site": "weibo"}],
                "nextCursor": None,
                "truncated": False,
            }

    monkeypatch.setattr(
        "whats_hot_api.cli.main._daemon_client",
        lambda config: FakeClient(),
    )
    result = CliRunner().invoke(
        cli,
        ["history", "query", "--site", "weibo", "-f", "json"],
    )

    assert result.exit_code == 0
    assert orjson.loads(result.stdout)[0]["title"] == "历史结果"


def test_cli_daemon_error_uses_service_unavailable_exit(monkeypatch) -> None:
    class FakeClient:
        def get(self, path, *, params=None):
            raise DaemonClientError("not running")

    monkeypatch.setattr(
        "whats_hot_api.cli.main._daemon_client",
        lambda config: FakeClient(),
    )
    result = CliRunner().invoke(
        cli,
        ["history", "stats", "-f", "json"],
    )

    assert result.exit_code == 69
    assert "DAEMON_UNAVAILABLE" in result.stderr


def test_cli_disabled_history_uses_config_exit_code(monkeypatch) -> None:
    class FakeClient:
        def get(self, path, *, params=None):
            raise DaemonClientError(
                "History storage is disabled.",
                code="HISTORY_DISABLED",
            )

    monkeypatch.setattr(
        "whats_hot_api.cli.main._daemon_client",
        lambda config: FakeClient(),
    )
    result = CliRunner().invoke(
        cli,
        ["history", "query", "-f", "json"],
    )

    assert result.exit_code == 78
    assert "HISTORY_DISABLED" in result.stderr


def test_cli_scheduler_trigger_polls_accepted_operation(monkeypatch) -> None:
    class FakeClient:
        polls = 0

        def post(self, path, *, json=None):
            assert path.endswith("/demo-hot/trigger")
            return {
                "operationId": "operation-one",
                "jobId": "demo-hot",
                "status": "accepted",
            }

        def get(self, path, *, params=None):
            assert path == "/internal/v1/scheduler/runs/operation-one"
            self.polls += 1
            return {
                "operationId": "operation-one",
                "jobId": "demo-hot",
                "status": "success" if self.polls > 1 else "running",
                "captureId": "capture-one",
            }

    client = FakeClient()
    monkeypatch.setattr(
        "whats_hot_api.cli.main._daemon_client",
        lambda config: client,
    )
    monkeypatch.setattr("whats_hot_api.cli.main.time.sleep", lambda _: None)

    result = CliRunner().invoke(
        cli,
        ["scheduler", "trigger", "demo-hot", "-f", "json"],
    )

    assert result.exit_code == 0
    assert orjson.loads(result.stdout)["captureId"] == "capture-one"
    assert client.polls == 2


def test_cli_scheduler_trigger_timeout_is_not_daemon_unavailable(
    monkeypatch,
) -> None:
    class FakeClient:
        def post(self, path, *, json=None):
            return {
                "operationId": "slow-operation",
                "jobId": "demo-hot",
                "status": "accepted",
            }

    monkeypatch.setattr(
        "whats_hot_api.cli.main._daemon_client",
        lambda config: FakeClient(),
    )
    monotonic = iter([0.0, 2.0])
    monkeypatch.setattr(
        "whats_hot_api.cli.main.time.monotonic",
        lambda: next(monotonic),
    )

    result = CliRunner().invoke(
        cli,
        [
            "scheduler",
            "trigger",
            "demo-hot",
            "--wait-timeout",
            "1",
        ],
    )

    assert result.exit_code == 75
    assert "SCHEDULER_RUN_TIMEOUT" in result.stderr
    assert "DAEMON_UNAVAILABLE" not in result.stderr


def test_cli_scheduler_trigger_no_wait_returns_operation(monkeypatch) -> None:
    class FakeClient:
        def post(self, path, *, json=None):
            return {
                "operationId": "background-operation",
                "jobId": "demo-hot",
                "status": "accepted",
            }

        def get(self, path, *, params=None):
            raise AssertionError("no-wait must not poll")

    monkeypatch.setattr(
        "whats_hot_api.cli.main._daemon_client",
        lambda config: FakeClient(),
    )

    result = CliRunner().invoke(
        cli,
        [
            "scheduler",
            "trigger",
            "demo-hot",
            "--no-wait",
            "-f",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert orjson.loads(result.stdout)["operationId"] == "background-operation"


def test_cli_invalid_config_uses_config_exit_code(tmp_path) -> None:
    config_path = tmp_path / "invalid.toml"
    config_path.write_text(
        """
[scheduler]
[[scheduler.jobs]]
id = "bad"
site = "missing"
type = "hot"
interval = "10m"
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["config", "validate", "--config", str(config_path)],
    )

    assert result.exit_code == 78
    assert "unknown site" in result.stderr

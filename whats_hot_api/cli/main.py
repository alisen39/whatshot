"""OpenCLI-style command-line entry point."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import click
import orjson
import yaml

from whats_hot_api._version import get_version
from whats_hot_api.cli.output import (
    OUTPUT_FORMATS,
    OutputFormat,
    normalize_rows,
    render,
)
from whats_hot_api.daemon.client import DaemonClient, DaemonClientError
from whats_hot_api.daemon.main import run_daemon
from whats_hot_api.fetch import (
    CachePolicy,
    FetchError,
    FetchRequest,
    SourceDescriptor,
    canonical_board_key,
)
from whats_hot_api.registry import (
    discover_and_register_routes,
    fetch_service,
)
from whats_hot_api.scheduler.config import (
    AppConfig,
    SchedulerConfigError,
    load_config,
)


class ConfigClickError(click.ClickException):
    exit_code = 78


def _ensure_discovered() -> None:
    discover_and_register_routes()


def _default_output_format() -> OutputFormat:
    return "table" if click.get_text_stream("stdout").isatty() else "yaml"


def _parse_params(values: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        key, separator, item = value.partition("=")
        if not separator or not key.strip():
            raise click.BadParameter(
                f"Expected KEY=VALUE, got {value!r}.",
                param_hint="--param",
            )
        result[key.strip()] = item
    return result


def _emit_error(ctx: click.Context, error: FetchError) -> None:
    payload = {"error": error.as_dict()}
    error_format = (ctx.find_root().obj or {}).get("error_format", "text")
    if error_format == "json":
        text = orjson.dumps(
            payload,
            option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE,
        ).decode()
    elif error_format == "yaml":
        text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    else:
        text = f"ERROR [{error.code}]: {error.message}\n"
    click.echo(text, err=True, nl=False)


def _exit_code(error: FetchError) -> int:
    if error.code in {"UNKNOWN_SOURCE", "UNKNOWN_TYPE"}:
        return 66
    if error.retryable:
        return 75
    return 1


def _load_cli_config(path: str | None) -> AppConfig:
    _ensure_discovered()
    try:
        return load_config(
            Path(path) if path else None,
            fetch_service=fetch_service,
        )
    except SchedulerConfigError as exc:
        raise ConfigClickError(str(exc)) from exc


def _daemon_client(config: AppConfig) -> DaemonClient:
    host = (
        "127.0.0.1" if config.daemon.bind in {"0.0.0.0", "::"} else config.daemon.bind
    )
    return DaemonClient(f"http://{host}:{config.daemon.port}")


def _emit_daemon_error(ctx: click.Context, error: DaemonClientError) -> None:
    payload = {
        "error": {
            "code": error.code,
            "message": str(error),
            "retryable": error.code in {"DAEMON_UNAVAILABLE", "SCHEDULER_RUN_TIMEOUT"},
            "details": {},
        }
    }
    error_format = (ctx.find_root().obj or {}).get("error_format", "text")
    if error_format == "json":
        text = orjson.dumps(
            payload,
            option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE,
        ).decode()
    elif error_format == "yaml":
        text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    else:
        text = f"ERROR [{error.code}]: {error}\n"
    click.echo(text, err=True, nl=False)


def _call_daemon(
    ctx: click.Context,
    callback,
) -> Any:
    try:
        return callback()
    except DaemonClientError as error:
        _emit_daemon_error(ctx, error)
        exit_code = (
            69
            if error.code == "DAEMON_UNAVAILABLE"
            else 66
            if error.code in {"JOB_NOT_FOUND", "UNKNOWN_SOURCE"}
            else 75
            if error.code == "SCHEDULER_RUN_TIMEOUT"
            else 78
            if error.code in {"HISTORY_DISABLED", "STORAGE_DISABLED"}
            else 1
        )
        raise click.exceptions.Exit(exit_code) from error


def _wait_for_scheduler_run(
    client: DaemonClient,
    operation: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    operation_id = operation["operationId"]
    deadline = time.monotonic() + timeout
    current = operation
    while current.get("status") in {"accepted", "running"}:
        if time.monotonic() >= deadline:
            raise DaemonClientError(
                (
                    f"Scheduler run '{operation_id}' is still running after "
                    f"{timeout:g} seconds."
                ),
                code="SCHEDULER_RUN_TIMEOUT",
            )
        time.sleep(0.25)
        current = client.get(f"/internal/v1/scheduler/runs/{operation_id}")
    if current.get("status") == "failed":
        raise DaemonClientError(
            str(current.get("errorMessage") or "Scheduler run failed."),
            code=str(current.get("errorCode") or "SCHEDULER_RUN_FAILED"),
        )
    return current


def _source_command(site: str) -> click.Command:
    descriptor = fetch_service.describe_source(site)

    @click.command(
        name=site,
        help=descriptor.description or descriptor.title,
        context_settings={"help_option_names": ["-h", "--help"]},
    )
    @click.argument(
        "path_type",
        required=False,
        default=descriptor.default_type,
    )
    @click.option(
        "--param",
        "params",
        multiple=True,
        metavar="KEY=VALUE",
        help="Additional route parameter; repeatable.",
    )
    @click.option("--limit", type=click.IntRange(1, 200))
    @click.option(
        "--cache",
        "cache_policy",
        type=click.Choice([policy.value for policy in CachePolicy]),
        default=CachePolicy.PREFER.value,
        show_default=True,
    )
    @click.option(
        "--format",
        "output_format",
        "-f",
        type=click.Choice(OUTPUT_FORMATS),
        default=None,
    )
    @click.option(
        "--envelope",
        is_flag=True,
        help="Include route response metadata instead of only rows.",
    )
    @click.pass_context
    def command(
        ctx: click.Context,
        path_type: str,
        params: tuple[str, ...],
        limit: int | None,
        cache_policy: str,
        output_format: OutputFormat | None,
        envelope: bool,
    ) -> None:
        """Fetch one source board without persisting it."""
        _fetch_and_render(
            ctx,
            descriptor=descriptor,
            path_type=path_type,
            params=params,
            limit=limit,
            cache_policy=cache_policy,
            output_format=output_format,
            envelope=envelope,
        )

    command.help = (
        f"{command.help}\n\n"
        f"Available types: {', '.join(descriptor.types)}. "
        f"Default: {descriptor.default_type}."
    )
    return command


def _fetch_and_render(
    ctx: click.Context,
    *,
    descriptor: SourceDescriptor,
    path_type: str,
    params: tuple[str, ...],
    limit: int | None,
    cache_policy: str,
    output_format: OutputFormat | None,
    envelope: bool,
) -> None:
    parsed_params = _parse_params(params)
    try:
        result = asyncio.run(
            fetch_service.fetch(
                FetchRequest(
                    site=descriptor.name,
                    path_type=path_type,
                    params=parsed_params,
                    limit=limit,
                    cache_policy=CachePolicy(cache_policy),
                )
            )
        )
    except FetchError as error:
        _emit_error(ctx, error)
        raise click.exceptions.Exit(_exit_code(error)) from error

    data = result.data
    if envelope:
        value: Any = {
            "code": 200,
            **data.model_dump(exclude={"params"}, exclude_none=True),
        }
    else:
        board_key = canonical_board_key(
            path_type=path_type,
            params=parsed_params,
            declared_dimensions=(descriptor.params or {}).keys(),
        )
        value = normalize_rows(
            data.data,
            site=descriptor.name,
            board_key=board_key,
        )
    click.echo(
        render(value, output_format or _default_output_format()),
        nl=False,
    )


class SourceGroup(click.Group):
    """Resolve registered sources as dynamic top-level commands."""

    def list_commands(self, ctx: click.Context) -> list[str]:
        _ensure_discovered()
        commands = set(super().list_commands(ctx))
        commands.update(source.name for source in fetch_service.list_sources())
        return sorted(commands)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        static = super().get_command(ctx, cmd_name)
        if static is not None:
            return static
        _ensure_discovered()
        try:
            fetch_service.describe_source(cmd_name)
        except FetchError:
            return None
        return _source_command(cmd_name)


@click.group(
    cls=SourceGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--error-format",
    type=click.Choice(["text", "json", "yaml"]),
    default="text",
    show_default=True,
)
@click.pass_context
def cli(ctx: click.Context, error_format: str) -> None:
    """Fetch and query WhatsHot sources."""
    ctx.ensure_object(dict)
    ctx.obj["error_format"] = error_format


@cli.command("list")
@click.option(
    "--format",
    "output_format",
    "-f",
    type=click.Choice(OUTPUT_FORMATS),
    default=None,
)
def list_sources(output_format: OutputFormat | None) -> None:
    """List discoverable sources without calling upstreams."""
    _ensure_discovered()
    rows = [source.as_dict() for source in fetch_service.list_sources()]
    click.echo(render(rows, output_format or _default_output_format()), nl=False)


@cli.command("fetch")
@click.argument("site")
@click.argument("path_type", required=False)
@click.option(
    "--param",
    "params",
    multiple=True,
    metavar="KEY=VALUE",
    help="Additional route parameter; repeatable.",
)
@click.option("--limit", type=click.IntRange(1, 200))
@click.option(
    "--cache",
    "cache_policy",
    type=click.Choice([policy.value for policy in CachePolicy]),
    default=CachePolicy.PREFER.value,
    show_default=True,
)
@click.option(
    "--format",
    "output_format",
    "-f",
    type=click.Choice(OUTPUT_FORMATS),
    default=None,
)
@click.option(
    "--envelope",
    is_flag=True,
    help="Include route response metadata instead of only rows.",
)
@click.pass_context
def fetch_source(
    ctx: click.Context,
    site: str,
    path_type: str | None,
    params: tuple[str, ...],
    limit: int | None,
    cache_policy: str,
    output_format: OutputFormat | None,
    envelope: bool,
) -> None:
    """Fetch a source explicitly, including names reserved by CLI commands."""
    _ensure_discovered()
    try:
        descriptor = fetch_service.describe_source(site)
    except FetchError as error:
        _emit_error(ctx, error)
        raise click.exceptions.Exit(_exit_code(error)) from error
    _fetch_and_render(
        ctx,
        descriptor=descriptor,
        path_type=path_type or descriptor.default_type,
        params=params,
        limit=limit,
        cache_policy=cache_policy,
        output_format=output_format,
        envelope=envelope,
    )


@cli.command("describe")
@click.argument("site")
@click.option(
    "--format",
    "output_format",
    "-f",
    type=click.Choice(OUTPUT_FORMATS),
    default=None,
)
@click.pass_context
def describe_source(
    ctx: click.Context,
    site: str,
    output_format: OutputFormat | None,
) -> None:
    """Describe one source and its route parameters."""
    _ensure_discovered()
    try:
        value = fetch_service.describe_source(site).as_dict()
    except FetchError as error:
        _emit_error(ctx, error)
        raise click.exceptions.Exit(_exit_code(error)) from error
    click.echo(render(value, output_format or _default_output_format()), nl=False)


@cli.command("version")
def show_version() -> None:
    """Print the installed WhatsHot version."""
    click.echo(get_version())


@cli.group("config")
def config_group() -> None:
    """Validate daemon and Scheduler configuration."""


@config_group.command("validate")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
)
@click.option(
    "--format",
    "output_format",
    "-f",
    type=click.Choice(OUTPUT_FORMATS),
    default=None,
)
def validate_config(
    config_path: Path | None,
    output_format: OutputFormat | None,
) -> None:
    """Validate TOML without starting the daemon or writing DuckDB."""
    config = _load_cli_config(str(config_path) if config_path else None)
    value = {
        "valid": True,
        "storageEnabled": config.storage.enabled,
        "databasePath": str(config.storage.path),
        "daemon": {
            "bind": config.daemon.bind,
            "port": config.daemon.port,
        },
        "schedulerEnabled": config.scheduler.enabled,
        "jobCount": len(config.jobs),
        "jobs": [
            {
                "id": job.id,
                "site": job.site,
                "boardKey": job.board_key,
                "intervalSeconds": job.interval_seconds,
                "enabled": job.enabled,
            }
            for job in config.jobs
        ],
    }
    click.echo(render(value, output_format or _default_output_format()), nl=False)


@cli.command("daemon")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
)
def daemon_command(config_path: Path | None) -> None:
    """Run Scheduler, DuckDB history, Backend API, and Control API."""
    try:
        run_daemon(config_path)
    except SchedulerConfigError as exc:
        raise ConfigClickError(str(exc)) from exc

def _history_output(
    value: dict[str, Any],
    *,
    output_format: OutputFormat | None,
    envelope: bool,
) -> None:
    rendered_value = value if envelope else value.get("items", value)
    click.echo(
        render(rendered_value, output_format or _default_output_format()),
        nl=False,
    )


@cli.group("history")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
)
@click.pass_context
def history_group(ctx: click.Context, config_path: Path | None) -> None:
    """Query persisted history through the running daemon."""
    ctx.ensure_object(dict)
    ctx.obj["daemon_config"] = _load_cli_config(
        str(config_path) if config_path else None
    )


@history_group.command("query")
@click.option("--site")
@click.option("--board")
@click.option("--kind", type=click.Choice(["hotlist", "newsflash", "gold"]))
@click.option("--since")
@click.option("--until")
@click.option("--limit", type=click.IntRange(1, 200), default=50)
@click.option("--cursor")
@click.option(
    "--format",
    "output_format",
    "-f",
    type=click.Choice(OUTPUT_FORMATS),
    default=None,
)
@click.option("--envelope", is_flag=True)
@click.pass_context
def history_query(
    ctx: click.Context,
    site: str | None,
    board: str | None,
    kind: str | None,
    since: str | None,
    until: str | None,
    limit: int,
    cursor: str | None,
    output_format: OutputFormat | None,
    envelope: bool,
) -> None:
    """Query historical items."""
    client = _daemon_client(ctx.obj["daemon_config"])
    value = _call_daemon(
        ctx,
        lambda: client.get(
            "/internal/v1/history",
            params={
                "site": site,
                "board": board,
                "kind": kind,
                "since": since,
                "until": until,
                "limit": limit,
                "cursor": cursor,
            },
        ),
    )
    _history_output(value, output_format=output_format, envelope=envelope)


@history_group.command("search")
@click.argument("keyword")
@click.option("--site")
@click.option("--board")
@click.option("--since")
@click.option("--until")
@click.option("--limit", type=click.IntRange(1, 200), default=50)
@click.option("--cursor")
@click.option(
    "--format",
    "output_format",
    "-f",
    type=click.Choice(OUTPUT_FORMATS),
    default=None,
)
@click.option("--envelope", is_flag=True)
@click.pass_context
def history_search(
    ctx: click.Context,
    keyword: str,
    site: str | None,
    board: str | None,
    since: str | None,
    until: str | None,
    limit: int,
    cursor: str | None,
    output_format: OutputFormat | None,
    envelope: bool,
) -> None:
    """Search titles, descriptions, and newsflash content."""
    client = _daemon_client(ctx.obj["daemon_config"])
    value = _call_daemon(
        ctx,
        lambda: client.get(
            "/internal/v1/history/search",
            params={
                "keyword": keyword,
                "site": site,
                "board": board,
                "since": since,
                "until": until,
                "limit": limit,
                "cursor": cursor,
            },
        ),
    )
    _history_output(value, output_format=output_format, envelope=envelope)


@history_group.command("trend")
@click.option("--site", required=True)
@click.option("--board", required=True)
@click.option("--item-id", required=True)
@click.option("--bucket", type=click.Choice(["10m", "1h", "6h", "1d"]), default="1h")
@click.option("--since")
@click.option("--until")
@click.option(
    "--format",
    "output_format",
    "-f",
    type=click.Choice(OUTPUT_FORMATS),
    default=None,
)
@click.pass_context
def history_trend(
    ctx: click.Context,
    site: str,
    board: str,
    item_id: str,
    bucket: str,
    since: str | None,
    until: str | None,
    output_format: OutputFormat | None,
) -> None:
    """Query rank and hot-value trend series."""
    client = _daemon_client(ctx.obj["daemon_config"])
    value = _call_daemon(
        ctx,
        lambda: client.get(
            "/internal/v1/history/trends",
            params={
                "site": site,
                "board": board,
                "item_id": item_id,
                "bucket": bucket,
                "since": since,
                "until": until,
            },
        ),
    )
    click.echo(
        render(value.get("series", []), output_format or _default_output_format()),
        nl=False,
    )


@history_group.command("stats")
@click.option(
    "--format",
    "output_format",
    "-f",
    type=click.Choice(OUTPUT_FORMATS),
    default=None,
)
@click.pass_context
def history_stats(
    ctx: click.Context,
    output_format: OutputFormat | None,
) -> None:
    """Show DuckDB history statistics."""
    client = _daemon_client(ctx.obj["daemon_config"])
    value = _call_daemon(
        ctx,
        lambda: client.get("/internal/v1/storage/stats"),
    )
    click.echo(render(value, output_format or _default_output_format()), nl=False)


@history_group.command("capture")
@click.argument("capture_id")
@click.option(
    "--format",
    "output_format",
    "-f",
    type=click.Choice(OUTPUT_FORMATS),
    default=None,
)
@click.pass_context
def history_capture(
    ctx: click.Context,
    capture_id: str,
    output_format: OutputFormat | None,
) -> None:
    """Return one capture and all of its items."""
    client = _daemon_client(ctx.obj["daemon_config"])
    value = _call_daemon(
        ctx,
        lambda: client.get(f"/internal/v1/history/captures/{capture_id}"),
    )
    click.echo(render(value, output_format or _default_output_format()), nl=False)


@cli.group("scheduler")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
)
@click.pass_context
def scheduler_group(ctx: click.Context, config_path: Path | None) -> None:
    """Inspect or trigger the Scheduler through the daemon."""
    ctx.ensure_object(dict)
    ctx.obj["daemon_config"] = _load_cli_config(
        str(config_path) if config_path else None
    )


@scheduler_group.command("status")
@click.option(
    "--format",
    "output_format",
    "-f",
    type=click.Choice(OUTPUT_FORMATS),
    default=None,
)
@click.pass_context
def scheduler_status(
    ctx: click.Context,
    output_format: OutputFormat | None,
) -> None:
    """Show Scheduler runtime status."""
    client = _daemon_client(ctx.obj["daemon_config"])
    value = _call_daemon(
        ctx,
        lambda: client.get("/internal/v1/scheduler/status"),
    )
    click.echo(render(value, output_format or _default_output_format()), nl=False)


@scheduler_group.command("jobs")
@click.option(
    "--format",
    "output_format",
    "-f",
    type=click.Choice(OUTPUT_FORMATS),
    default=None,
)
@click.pass_context
def scheduler_jobs(
    ctx: click.Context,
    output_format: OutputFormat | None,
) -> None:
    """List configured Scheduler jobs."""
    client = _daemon_client(ctx.obj["daemon_config"])
    value = _call_daemon(
        ctx,
        lambda: client.get("/internal/v1/scheduler/jobs"),
    )
    click.echo(
        render(value["jobs"], output_format or _default_output_format()),
        nl=False,
    )


@scheduler_group.command("trigger")
@click.argument("job_id")
@click.option(
    "--wait/--no-wait",
    default=True,
    show_default=True,
    help="Wait for the accepted Scheduler run to finish.",
)
@click.option(
    "--wait-timeout",
    type=click.FloatRange(min=1, max=3600),
    default=180.0,
    show_default=True,
)
@click.option(
    "--format",
    "output_format",
    "-f",
    type=click.Choice(OUTPUT_FORMATS),
    default=None,
)
@click.pass_context
def scheduler_trigger(
    ctx: click.Context,
    job_id: str,
    wait: bool,
    wait_timeout: float,
    output_format: OutputFormat | None,
) -> None:
    """Ask Scheduler to run one configured job immediately."""
    client = _daemon_client(ctx.obj["daemon_config"])
    value = _call_daemon(
        ctx,
        lambda: client.post(f"/internal/v1/scheduler/jobs/{job_id}/trigger"),
    )
    if wait:
        value = _call_daemon(
            ctx,
            lambda: _wait_for_scheduler_run(
                client,
                value,
                timeout=wait_timeout,
            ),
        )
    click.echo(render(value, output_format or _default_output_format()), nl=False)


def main() -> None:
    cli(prog_name="whatshot")


if __name__ == "__main__":
    main()

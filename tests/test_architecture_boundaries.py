from __future__ import annotations

import ast
from pathlib import Path

import whats_hot_api

PACKAGE_ROOT = Path(whats_hot_api.__file__).parent


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_only_writer_actor_imports_scheduler_storage() -> None:
    offenders = []
    target = "whats_hot_api.scheduler.storage"
    for path in PACKAGE_ROOT.rglob("*.py"):
        if target in _imports(path):
            relative = path.relative_to(PACKAGE_ROOT).as_posix()
            if relative != "scheduler/writer_actor.py":
                offenders.append(relative)

    assert offenders == []


def test_duckdb_is_not_imported_by_public_adapters() -> None:
    forbidden_roots = {
        "app.py",
        "registry.py",
        "fetch",
        "cli",
        "mcp",
    }
    offenders = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        relative = path.relative_to(PACKAGE_ROOT)
        if relative.parts[0] not in forbidden_roots:
            continue
        if "duckdb" in _imports(path):
            offenders.append(relative.as_posix())

    assert offenders == []


def test_core_fastapi_app_does_not_start_scheduler_or_history() -> None:
    imports = _imports(PACKAGE_ROOT / "app.py")

    assert not any(module.startswith("whats_hot_api.scheduler") for module in imports)
    assert not any(module.startswith("whats_hot_api.history") for module in imports)
    assert not any(module.startswith("whats_hot_api.mcp") for module in imports)


def test_stdio_proxy_does_not_open_history_database() -> None:
    imports = _imports(PACKAGE_ROOT / "mcp" / "stdio_proxy.py")

    assert "whats_hot_api.history" not in imports
    assert "whats_hot_api.scheduler.storage" not in imports


def test_history_public_api_is_read_only() -> None:
    from whats_hot_api import history

    assert history.__all__ == ["HistoryReader"]
    assert not hasattr(history, "SchedulerDuckDBWriter")

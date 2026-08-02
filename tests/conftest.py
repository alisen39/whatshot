from __future__ import annotations

import pytest

_INTEGRATION_MODULES = {
    "test_create_app.py",
    "test_route_metadata.py",
}

_E2E_MODULES = {"test_all_routes.py"}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="run live upstream end-to-end route smoke tests",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    skip_e2e = pytest.mark.skip(reason="requires --run-e2e and live upstream access")
    for item in items:
        if item.path.name in _E2E_MODULES:
            marker = pytest.mark.e2e
            if not config.getoption("--run-e2e"):
                item.add_marker(skip_e2e)
        elif item.path.name in _INTEGRATION_MODULES:
            marker = pytest.mark.integration
        else:
            marker = pytest.mark.unit
        item.add_marker(marker)

"""Single source for the installed WhatsHot package version."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version

_SOURCE_TREE_VERSION = "0.1.0"


def get_version() -> str:
    try:
        return distribution_version("whats-hot-api")
    except PackageNotFoundError:
        return _SOURCE_TREE_VERSION

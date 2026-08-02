"""Read-only historical query API.

Write access intentionally lives under :mod:`whats_hot_api.scheduler.storage`.
"""

from whats_hot_api.history.query import HistoryReader

__all__ = ["HistoryReader"]

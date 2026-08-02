"""Data transfer models between Scheduler and the history store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from whats_hot_api.fetch import FetchResult

TriggerKind = Literal["interval", "manual"]


@dataclass(frozen=True, slots=True)
class RunStart:
    run_id: str
    run_key: str
    job_id: str
    trigger_kind: TriggerKind
    scheduled_for: datetime
    started_at: datetime
    attempt: int = 1


@dataclass(frozen=True, slots=True)
class CaptureBatch:
    capture_id: str
    run: RunStart
    board_key: str
    fetch_result: FetchResult

"""Cross-process owner lock for the single WhatsHot daemon."""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO


class DaemonAlreadyRunningError(RuntimeError):
    pass


class OwnerLock:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._file: IO[str] | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open("a+", encoding="utf-8")
        try:
            self._lock(file)
        except OSError as exc:
            file.seek(0)
            owner = file.read().strip() or "unknown"
            file.close()
            raise DaemonAlreadyRunningError(
                f"Another WhatsHot daemon owns {self.path} (pid={owner})."
            ) from exc
        file.seek(0)
        file.truncate()
        file.write(str(os.getpid()))
        file.flush()
        self._file = file

    def release(self) -> None:
        if self._file is None:
            return
        self._unlock(self._file)
        self._file.close()
        self._file = None

    @staticmethod
    def _lock(file: IO[str]) -> None:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(file: IO[str]) -> None:
        if os.name == "nt":
            import msvcrt

            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(file.fileno(), fcntl.LOCK_UN)

"""Single-run lock for the daily application loop.

Two concurrent rounds against the same workspace would share the browser, the
candidate queue and the CV cache.  The lock is a non-blocking ``flock`` on
``data/run.lock``: the file can stay on disk after a run (the kernel releases
the lock when the process exits), and a second process gets ``RunLocked``
instead of starting a parallel round.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Callable, Literal

LOCK_FILENAME = "run.lock"


class RunLocked(RuntimeError):
    """Another round already holds the workspace lock."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunLock:
    """Context manager that admits one run per workspace."""

    def __init__(
        self,
        path: Path,
        *,
        assert_writable: Callable[[Path], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self._assert_writable = assert_writable
        self._clock = clock or _utcnow
        self._handle: IO[str] | None = None

    def __enter__(self) -> "RunLock":
        if self._assert_writable is not None:
            self._assert_writable(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            if exc.errno in {errno.EAGAIN, errno.EACCES}:
                raise RunLocked(
                    f"another run holds {self.path} (pid in the file: {_holder(self.path)})"
                ) from exc
            raise
        self._handle = handle
        payload = {
            "pid": os.getpid(),
            "started_at": self._clock().isoformat(),
        }
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(payload) + "\n")
        handle.flush()
        return self

    def __exit__(self, exc_type, exc, traceback) -> Literal[False]:
        handle = self._handle
        if handle is None:
            return False
        self._handle = None
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
        return False


def _holder(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    if isinstance(payload, dict) and payload.get("pid") is not None:
        return str(payload["pid"])
    return "unknown"

"""Persistent state for one daily run.

The queue is the source of truth for individual jobs; this file adds the
run-level counters needed to resume an interrupted round without restarting the
count or reapplying jobs LinkedIn already confirmed.  It lives in
``data/runs/<run_id>.json`` inside the writable workspace.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from career_ops.paths import WorkspacePaths

RUNS_DIRNAME = "runs"
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_run_id(run_id: str) -> None:
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(f"invalid run id {run_id!r}")


@dataclass
class RunState:
    """Counters and per-job outcomes for a daily run."""

    run_id: str
    target: int
    path: Path
    started_at: str
    updated_at: str
    status: str = "running"
    stop_reason: str | None = None
    attempts: int = 0
    verified: int = 0
    jobs: dict[str, dict[str, object]] = field(default_factory=dict)
    _clock: Callable[[], datetime] = field(default=utcnow, repr=False)
    _assert_writable: Callable[[Path], None] | None = field(default=None, repr=False)

    @classmethod
    def load_or_create(
        cls,
        paths: WorkspacePaths,
        *,
        run_id: str,
        target: int,
        clock: Callable[[], datetime] | None = None,
        assert_writable: Callable[[Path], None] | None = None,
    ) -> "RunState":
        validate_run_id(run_id)
        clock = clock or utcnow
        path = Path(paths.data) / RUNS_DIRNAME / f"{run_id}.json"
        now = clock().isoformat()
        if not path.is_file():
            return cls(
                run_id=run_id,
                target=target,
                path=path,
                started_at=now,
                updated_at=now,
                _clock=clock,
                _assert_writable=assert_writable or paths.assert_writable,
            )

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read run state {path}: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError(f"run state {path} must contain a JSON object")
        stored_run_id = str(payload.get("run_id") or run_id)
        if stored_run_id != run_id:
            raise ValueError(
                f"run state {path} belongs to run {stored_run_id!r}, not {run_id!r}"
            )
        jobs = payload.get("jobs")
        return cls(
            run_id=run_id,
            target=target,
            path=path,
            started_at=str(payload.get("started_at") or now),
            updated_at=str(payload.get("updated_at") or now),
            status=str(payload.get("status") or "running"),
            stop_reason=_optional_str(payload.get("stop_reason")),
            attempts=_as_int(payload.get("attempts")),
            verified=_as_int(payload.get("verified")),
            jobs={
                str(job_id): dict(info)
                for job_id, info in (jobs.items() if isinstance(jobs, Mapping) else [])
                if isinstance(info, Mapping)
            },
            _clock=clock,
            _assert_writable=assert_writable or paths.assert_writable,
        )

    def start(self) -> None:
        self.status = "running"
        self.stop_reason = None
        self.updated_at = self._clock().isoformat()

    def record_job(
        self,
        job_id: str,
        *,
        state: str,
        reason: str | None,
        attempts: int,
        verified: bool,
        waiting: bool,
        cv: str | None = None,
        session_dir: str | None = None,
    ) -> None:
        self.jobs[job_id] = {
            "state": state,
            "reason": reason,
            "attempts": attempts,
            "verified": verified,
            "waiting": waiting,
            "cv": cv,
            "session_dir": session_dir,
            "finished_at": self._clock().isoformat(),
        }
        self.updated_at = self._clock().isoformat()

    def finish(self, *, status: str, stop_reason: str) -> None:
        self.status = status
        self.stop_reason = stop_reason
        self.updated_at = self._clock().isoformat()

    def waiting_count(self) -> int:
        return sum(1 for info in self.jobs.values() if bool(info.get("waiting")))

    def verified_jobs(self) -> set[str]:
        return {
            job_id
            for job_id, info in self.jobs.items()
            if bool(info.get("verified"))
        }

    def snapshot(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "target": self.target,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "attempts": self.attempts,
            "verified": self.verified,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "jobs": {job_id: dict(info) for job_id, info in self.jobs.items()},
        }

    def save(self) -> None:
        if self._assert_writable is not None:
            self._assert_writable(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.snapshot(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _as_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0

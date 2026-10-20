"""Observable sessions for a single application run.

Every application writes to ``output/sessions/<run_id>/``: ``session.json``
holds the run metadata, ``events.jsonl`` is an append-only structured log and
``screenshots/`` holds the visual evidence.  The recorder is intentionally
small; the application adapter (#04) calls it at every transition and the
report/retention slices (#08) read the same files.

Event schema (one JSON object per line)::

    {
      "ts": "2026-10-19T12:00:00.320000+00:00",
      "run_id": "2026-10-19-morning",
      "job_id": "4411222",
      "stage": "form_page",
      "page": 1,
      "status": "ok",
      "duration_ms": 320,
      "artifact": "screenshots/form-page-1.png",
      "detail": null
    }

Screenshots are named after their stage (``open.png``, ``form-page-1.png``,
``review.png``, ``submit.png``, ``error.png``); a repeated successful capture
of the same stage gets ``-2``, ``-3``, ... so names stay stable when captures
are reordered.  A failed application still closes its session with
``status: failed`` and an ``error`` event (plus a grim fallback screenshot when
the CDP renderer stopped answering).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Mapping

from career_ops.capture import Screenshotter, capture_with_fallback, grim_screenshotter
from career_ops.paths import WorkspacePaths

SESSION_DIRNAME = "sessions"
_EVENT_KEYS = (
    "ts",
    "run_id",
    "job_id",
    "stage",
    "page",
    "status",
    "duration_ms",
    "artifact",
    "detail",
)
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _slug(stage: str) -> str:
    return stage.replace("_", "-").replace(" ", "-")


class SessionRecorder:
    """Writes metadata, events and screenshots for one application run."""

    def __init__(
        self,
        root: Path,
        *,
        run_id: str,
        job: Mapping[str, object] | None,
        clock: Callable[[], datetime],
        screenshotter: Screenshotter | None,
        fallback: Screenshotter | None,
        created_at: datetime,
    ) -> None:
        self.root = root
        self.run_id = run_id
        self.job = dict(job) if job is not None else None
        self._clock = clock
        self._screenshotter = screenshotter
        self._fallback = fallback
        self._created_at = created_at
        self._closed = False

    @classmethod
    def create(
        cls,
        paths: WorkspacePaths,
        *,
        run_id: str | None = None,
        job: Mapping[str, object] | str | None = None,
        clock: Callable[[], datetime] | None = None,
        screenshotter: Screenshotter | None = None,
        fallback: Screenshotter | None = None,
        subdir: str | None = None,
    ) -> "SessionRecorder":
        """Create a fresh session directory under the workspace's output.

        When a screenshotter is supplied, the system-level ``grim`` capture is
        wired as the automatic timeout fallback unless an explicit fallback is
        given.  ``subdir`` keeps one application attempt per job below a daily
        run directory while ``run_id`` stays the same for every attempt.
        """
        clock = clock or _utcnow
        created_at = clock()
        run_id = run_id or created_at.strftime("%Y%m%dT%H%M%SZ")
        if not _RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError(f"invalid run id {run_id!r}")

        sessions_root = paths.output / SESSION_DIRNAME
        root = sessions_root / run_id
        if subdir is not None:
            if not _RUN_ID_PATTERN.fullmatch(subdir):
                raise ValueError(f"invalid session subdirectory {subdir!r}")
            root = root / subdir
        if root.exists():
            suffix = 2
            while Path(f"{root}-{suffix}").exists():
                suffix += 1
            root = Path(f"{root}-{suffix}")
            if subdir is None:
                run_id = root.name

        paths.assert_writable(root)
        (root / "screenshots").mkdir(parents=True)
        (root / "events.jsonl").touch()

        if isinstance(job, str):
            job = {"id": job}
        if screenshotter is not None and fallback is None:
            fallback = grim_screenshotter()
        recorder = cls(
            root,
            run_id=run_id,
            job=job,
            clock=clock,
            screenshotter=screenshotter,
            fallback=fallback,
            created_at=created_at,
        )
        recorder._write_metadata(status="running", finished_at=None)
        return recorder

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def screenshots_dir(self) -> Path:
        return self.root / "screenshots"

    def record(
        self,
        stage: str,
        status: str,
        *,
        job_id: str | None = None,
        page: int | None = None,
        duration_ms: int = 0,
        artifact: str | None = None,
        detail: Mapping[str, object] | None = None,
    ) -> dict:
        """Append one structured event and return it."""
        event = {
            "ts": _iso(self._clock()),
            "run_id": self.run_id,
            "job_id": job_id if job_id is not None else self._job_id(),
            "stage": stage,
            "page": page,
            "status": status,
            "duration_ms": int(duration_ms),
            "artifact": artifact,
            "detail": dict(detail) if detail is not None else None,
        }
        assert list(event) == list(_EVENT_KEYS)
        self._append(event)
        return event

    def capture(
        self,
        stage: str,
        *,
        job_id: str | None = None,
        page: int | None = None,
        status: str = "ok",
        detail: Mapping[str, object] | None = None,
    ) -> dict:
        """Capture a screenshot for ``stage`` and log it with its duration.

        A CDP timeout automatically triggers the configured grim fallback.  A
        failed capture is recorded in the session but never hides the original
        application outcome.
        """
        if self._screenshotter is None:
            raise RuntimeError("this session has no screenshotter configured")

        job_id = job_id if job_id is not None else self._job_id()
        name = _slug(stage)
        if page is not None:
            name = f"{name}-{page}"
        path = self._available_path(name)

        started = self._clock()
        result = capture_with_fallback(self._screenshotter, path, self._fallback)
        duration_ms = int((self._clock() - started).total_seconds() * 1000)

        event_detail = dict(detail) if detail is not None else None
        if result.status == "ok":
            event_status = status
        elif result.source == "fallback":
            # The grim capture worked; the stage still has usable evidence.
            event_status = status
            event_detail = {
                **(event_detail or {}),
                "capture_error": result.error,
                "capture_source": "fallback",
            }
        elif result.status == "timeout":
            event_status = "timeout"
            event_detail = {**(event_detail or {}), "capture_error": result.error}
        else:
            event_status = "failed"
            event_detail = {**(event_detail or {}), "capture_error": result.error}

        artifact = None
        if path.is_file():
            artifact = path.relative_to(self.root).as_posix()
        return self.record(
            stage,
            event_status,
            job_id=job_id,
            page=page,
            duration_ms=duration_ms,
            artifact=artifact,
            detail=event_detail,
        )

    def fail(
        self,
        error: object,
        *,
        job_id: str | None = None,
        page: int | None = None,
        detail: Mapping[str, object] | None = None,
    ) -> dict:
        """Record an application failure, with an error screenshot when possible.

        Returned failures (wrong CV, closed job) call this directly; exceptions
        reaching ``__exit__`` use it too.  Failure recording never raises.
        """
        merged = {**(detail or {}), "error": str(error)}
        if self._screenshotter is not None:
            try:
                return self.capture(
                    "error",
                    job_id=job_id,
                    page=page,
                    status="failed",
                    detail=merged,
                )
            except Exception as exc:  # noqa: BLE001 - never mask the application error
                merged = {**merged, "recorder_error": str(exc)}
        return self.record("error", "failed", job_id=job_id, page=page, detail=merged)

    def close(self, status: str = "completed") -> None:
        """Persist the final session status (idempotent)."""
        if self._closed:
            return
        self._closed = True
        self._write_metadata(status=status, finished_at=self._clock())

    def __enter__(self) -> "SessionRecorder":
        return self

    def __exit__(self, exc_type, exc, traceback) -> Literal[False]:
        if exc is not None:
            self.fail(f"{type(exc).__name__}: {exc}")
            self.close("failed")
        else:
            self.close("completed")
        return False

    def _available_path(self, name: str) -> Path:
        """Stable stage name; only a repeated successful capture gets a suffix."""
        path = self.screenshots_dir / f"{name}.png"
        suffix = 2
        while path.exists():
            path = self.screenshots_dir / f"{name}-{suffix}.png"
            suffix += 1
        return path

    def _job_id(self) -> str | None:
        if not self.job:
            return None
        job_id = self.job.get("id")
        return None if job_id is None else str(job_id)

    def _append(self, event: Mapping[str, object]) -> None:
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _write_metadata(self, *, status: str, finished_at: datetime | None) -> None:
        metadata = {
            "run_id": self.run_id,
            "status": status,
            "created_at": _iso(self._created_at),
            "finished_at": _iso(finished_at) if finished_at is not None else None,
            "job": self.job,
        }
        metadata_path = self.root / "session.json"
        temporary = metadata_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(metadata_path)

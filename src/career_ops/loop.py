"""Sequential daily loop: apply until the verified target is reached.

The loop owns orchestration only.  Browser work is injected as an ``apply``
callable, CV resolution as another callable, and discovery as a
``CandidateSource``.  That keeps the policy deterministic and testable with the
fake adapter while the CLI wires the real workspace.

Stopping rules:

* exactly ``target`` verified applications — the loop checks the counter before
  it opens the next job, so a 21st attempt never starts;
* the optional time budget, checked before every attempt;
* LinkedIn's daily limit, reported by the adapter as ``LinkedInDailyLimit``;
* an exhausted candidate source (no job left to evaluate).

Retries keep the queue as the source of truth.  A transient failure goes back to
``eligible`` only while the job has used fewer than ``max_attempts_per_job``
attempts in this run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from career_ops.cv_cache import CvDecision
from career_ops.cv_tailoring import CvGenerationError
from career_ops.queue import (
    Candidate,
    EnqueueResult,
    JobQueue,
    QueueProcessor,
    Selection,
    load_candidates,
    record_application_outcome,
)
from career_ops.run_state import RunState


class CandidateSource(Protocol):
    """A discovery seam: return the candidates found right now."""

    def discover(self) -> Sequence[Candidate]:
        """Return candidates; the queue deduplicates them."""


class FileCandidateSource:
    """Read a candidate file every time discovery is requested."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def discover(self) -> Sequence[Candidate]:
        return load_candidates(self.path)


@dataclass(frozen=True)
class LoopConfig:
    target: int
    max_seconds: float | None = None
    max_attempts_per_job: int = 2
    low_watermark: int = 5

    def __post_init__(self) -> None:
        if self.target < 1:
            raise ValueError("target must be at least 1")
        if self.max_seconds is not None and self.max_seconds < 0:
            raise ValueError("max_seconds must be zero or greater")
        if self.max_attempts_per_job < 1:
            raise ValueError("max_attempts_per_job must be at least 1")
        if self.low_watermark < 0:
            raise ValueError("low_watermark must be zero or greater")


@dataclass(frozen=True)
class JobOutcome:
    """Observable result of one application attempt inside the loop."""

    job_id: str
    state: str
    reason: str | None
    attempts: int
    verified: bool
    submitted: bool
    waiting: bool
    cv: str | None
    session_dir: str | None
    duration_ms: int
    payload: Mapping[str, object] = field(repr=False, compare=False)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.job_id,
            "state": self.state,
            "reason": self.reason,
            "attempts": self.attempts,
            "verified": self.verified,
            "submitted": self.submitted,
            "waiting": self.waiting,
            "cv": self.cv,
            "session_dir": self.session_dir,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class LoopOutcome:
    """Final result of a daily loop."""

    run_id: str
    target: int
    stop_reason: str
    verified: int
    submitted: int
    waiting: int
    attempts: int
    applications: tuple[JobOutcome, ...]
    ingested: tuple[EnqueueResult, ...]
    state_path: Path
    last_payload: Mapping[str, object] | None = None
    last_selection: Selection | None = None

    @property
    def status(self) -> str:
        return "verified" if self.stop_reason == "target_reached" else "failed"

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "target": self.target,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "verified": self.verified,
            "submitted": self.submitted,
            "waiting": self.waiting,
            "attempts": self.attempts,
            "state_path": str(self.state_path),
            "applications": [application.as_dict() for application in self.applications],
        }


class DailyLoop:
    """Apply job by job until one of the stopping rules fires."""

    def __init__(
        self,
        *,
        queue: JobQueue,
        processor: QueueProcessor,
        source: CandidateSource,
        config: LoopConfig,
        state: RunState,
        apply: Callable[[Selection, Path], Mapping[str, object]],
        resolve_cv: Callable[[Selection], tuple[Path, CvDecision | None]],
        requeue_reason: str | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.queue = queue
        self.processor = processor
        self.source = source
        self.config = config
        self.state = state
        self.apply = apply
        self.resolve_cv = resolve_cv
        self.requeue_reason = requeue_reason
        self._monotonic = monotonic or time.monotonic
        self._source_exhausted = False
        self._discovery_backlog = 0
        self._ingested: list[EnqueueResult] = []
        self._applications: list[JobOutcome] = []
        self._last_payload: Mapping[str, object] | None = None
        self._last_selection: Selection | None = None

    @property
    def run_id(self) -> str:
        return self.state.run_id

    def run(self) -> LoopOutcome:
        started = self._monotonic()
        self.state.start()
        self._reconcile()
        self._abandon_stale_applying()

        stop_reason = "queue_exhausted"
        while self.state.verified < self.config.target:
            if self._budget_exhausted(started):
                stop_reason = "time_budget_exhausted"
                break

            self._maybe_discover(force=False)
            selection = self.processor.next_eligible()
            if selection is None:
                selection = self._recover_selection()
            if selection is None:
                stop_reason = "queue_exhausted"
                break

            job_id = selection.job_id
            record = self.queue.get(job_id)
            if record.attempts >= self.config.max_attempts_per_job:
                self._complete(
                    job_id,
                    state="failed",
                    reason="attempts_exhausted",
                    attempts=record.attempts,
                )
                continue

            cv, cv_decision = self._resolve_cv_or_record(selection)
            if cv is None:
                continue

            self.queue.begin(job_id)
            self.state.attempts += 1
            self.state.save()
            job_started = self._monotonic()
            payload = dict(self.apply(selection, cv))
            duration_ms = int((self._monotonic() - job_started) * 1000)
            self._last_payload = payload
            self._last_selection = selection
            outcome, stop = self._record_attempt(
                selection,
                payload,
                cv=cv,
                duration_ms=duration_ms,
                cv_decision=cv_decision,
            )
            self._applications.append(outcome)
            if stop is not None:
                stop_reason = stop
                break

        if self.state.verified >= self.config.target:
            stop_reason = "target_reached"
        self.state.finish(status="verified" if stop_reason == "target_reached" else "failed",
                          stop_reason=stop_reason)
        self.state.save()
        return LoopOutcome(
            run_id=self.run_id,
            target=self.config.target,
            stop_reason=stop_reason,
            verified=self.state.verified,
            submitted=self.state.clicked_count(),
            waiting=self.state.waiting_count(),
            attempts=self.state.attempts,
            applications=tuple(self._applications),
            ingested=tuple(self._ingested),
            state_path=self.state.path,
            last_payload=self._last_payload,
            last_selection=self._last_selection,
        )

    def _reconcile(self) -> None:
        """Count verified jobs from the queue even if the state file lagged."""
        already = len(self.queue.verified_for_run(self.run_id))
        if already > self.state.verified:
            self.state.verified = already

    def _abandon_stale_applying(self) -> None:
        """A previous process may have died after ``begin``.

        Retrying automatically is unsafe because the submit click may already
        have happened.  The attempt is recorded as interrupted and stays out of
        the verified count.
        """
        for job_id, record in list(self.queue.records.items()):
            if record.state != "applying":
                continue
            self.queue.complete(
                job_id,
                "failed",
                "run_interrupted",
                {
                    "message": "the previous run stopped while this attempt was in progress",
                    "attempts": record.attempts,
                },
            )
            self.state.record_job(
                job_id,
                state="failed",
                reason="run_interrupted",
                attempts=record.attempts,
                verified=False,
                waiting=False,
            )

    def _maybe_discover(self, *, force: bool) -> bool:
        """Call the source when the backlog is low, or when ``force`` empties it.

        A discovery that adds nothing is remembered, but the flag is cleared
        once the backlog has shrunk: a source that is slow to reveal candidates
        still gets another look after the loop made progress.
        """
        backlog = self.queue.backlog()
        if self._source_exhausted:
            if backlog >= self._discovery_backlog:
                return False
            self._source_exhausted = False
        if backlog > self.config.low_watermark:
            return False
        if force and backlog > 0:
            return False
        self._discover()
        return True

    def _recover_selection(self) -> Selection | None:
        if not self._maybe_discover(force=True):
            return None
        return self.processor.next_eligible()

    def _discover(self) -> None:
        results = self.queue.ingest(
            self.source.discover(), requeue_reason=self.requeue_reason
        )
        self._ingested.extend(results)
        self._discovery_backlog = self.queue.backlog()
        if not any(result.status in {"enqueued", "requeued"} for result in results):
            self._source_exhausted = True

    def _budget_exhausted(self, started: float) -> bool:
        budget = self.config.max_seconds
        if budget is None or budget == 0:
            return False
        return self._monotonic() - started >= budget

    def _resolve_cv_or_record(
        self, selection: Selection
    ) -> tuple[Path | None, CvDecision | None]:
        started = self._monotonic()
        try:
            return self.resolve_cv(selection)
        except CvGenerationError as exc:
            duration_ms = int((self._monotonic() - started) * 1000)
            self.queue.complete(
                selection.job_id,
                "failed",
                exc.reason,
                {
                    "message": str(exc),
                    "stage": "cv",
                    "retryable": exc.retryable,
                },
            )
            self._complete(
                selection.job_id,
                state="failed",
                reason=exc.reason,
                attempts=self.queue.get(selection.job_id).attempts,
                message=str(exc),
                duration_ms=duration_ms,
            )
            self._last_selection = selection
            self._last_payload = self._synthetic_failure(selection, exc.reason, str(exc))
            self._applications.append(
                JobOutcome(
                    job_id=selection.job_id,
                    state="failed",
                    reason=exc.reason,
                    attempts=self.queue.get(selection.job_id).attempts,
                    verified=False,
                    submitted=False,
                    waiting=False,
                    cv=None,
                    session_dir=None,
                    duration_ms=duration_ms,
                    payload=self._last_payload,
                )
            )
            return None, None

    def _record_attempt(
        self,
        selection: Selection,
        payload: Mapping[str, object],
        *,
        cv: Path,
        duration_ms: int,
        cv_decision: CvDecision | None,
    ) -> tuple[JobOutcome, str | None]:
        job_id = selection.job_id
        record = record_application_outcome(self.queue, job_id, payload)
        state = record.state
        reason = record.reason
        verified = payload.get("status") == "verified"
        waiting = reason == "waiting_input"
        clicked = bool(_result(payload).get("clicked"))
        session_dir = (
            str(record.detail["session_dir"])
            if isinstance(record.detail.get("session_dir"), str)
            else None
        )
        attempts = record.attempts
        stop: str | None = None

        if verified:
            if job_id not in self.state.verified_jobs():
                self.state.verified += 1
            if self.state.verified >= self.config.target:
                stop = "target_reached"
        elif reason == "daily_limit":
            stop = "daily_limit_reached"
        elif reason != "waiting_input" and _retryable(payload):
            if attempts < self.config.max_attempts_per_job:
                retried = self.queue.retry(job_id, reason)
                state = retried.state
                reason = retried.reason
            else:
                state = "failed"

        self._complete(
            job_id,
            state=state,
            reason=reason,
            attempts=attempts,
            verified=verified,
            submitted=clicked,
            waiting=waiting,
            cv=str(cv),
            session_dir=session_dir,
            cv_decision=cv_decision,
            duration_ms=duration_ms,
        )
        return (
            JobOutcome(
                job_id=job_id,
                state=state,
                reason=reason,
                attempts=attempts,
                verified=verified,
                submitted=clicked,
                waiting=waiting,
                cv=str(cv),
                session_dir=session_dir,
                duration_ms=duration_ms,
                payload=payload,
            ),
            stop,
        )

    def _complete(
        self,
        job_id: str,
        *,
        state: str,
        reason: str | None,
        attempts: int,
        verified: bool = False,
        submitted: bool = False,
        waiting: bool = False,
        cv: str | None = None,
        session_dir: str | None = None,
        cv_decision: CvDecision | None = None,
        message: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        self.state.record_job(
            job_id,
            state=state,
            reason=reason,
            attempts=attempts,
            verified=verified,
            submitted=submitted,
            waiting=waiting,
            cv=cv,
            session_dir=session_dir,
            duration_ms=duration_ms,
        )
        if cv_decision is not None:
            self.state.jobs[job_id]["cv_cache"] = cv_decision.as_dict()
        if message is not None:
            self.state.jobs[job_id]["message"] = message
        self.state.save()

    def _synthetic_failure(
        self, selection: Selection, reason: str, message: str
    ) -> dict[str, object]:
        return {
            "status": "failed",
            "run_id": self.run_id,
            "job": selection.as_job(),
            "result": {
                "submitted": False,
                "verified": False,
                "clicked": False,
                "reason": reason,
                "attempts": 0,
                "retryable": False,
            },
            "failure": {"reason": reason, "message": message, "retryable": False},
            "artifacts": {
                "session_dir": None,
                "session_json": None,
                "events": None,
                "screenshots": [],
            },
            "cv": None,
        }


def _retryable(payload: Mapping[str, object]) -> bool:
    failure = payload.get("failure")
    if isinstance(failure, Mapping):
        return bool(failure.get("retryable"))
    return False


def _result(payload: Mapping[str, object]) -> Mapping[str, object]:
    result = payload.get("result")
    return result if isinstance(result, Mapping) else {}

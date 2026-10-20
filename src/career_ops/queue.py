"""Persistent candidate queue, quick filters and deterministic eligibility flow.

The queue is the shortlist state between discovery and application.  It stores
one record per LinkedIn job id, keeps terminal decisions from coming back, and
only fetches a JD for candidates that pass the title and location filters.  The
first eligible job is returned to the caller (the application flow); later
candidates stay untouched in ``new`` so a daily run can continue from there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

from career_ops.eligibility import EligibilityRules, evaluate_eligibility
from career_ops.job_description import JobDescriptionError, JobDescriptionFetcher
from career_ops.job_filters import filter_location, filter_title
from career_ops.job_profile import build_job_profile
from career_ops.paths import WorkspacePaths

QUEUE_FILENAME = "queue.json"
JD_DIRNAME = "jds"
QUEUE_VERSION = 1

# Terminal for the queue: these ids do not return without an explicit reason.
_BLOCKING_STATES = frozenset(
    {
        "title_rejected",
        "ineligible",
        "failed",
        "applying",
        "waiting_input",
        "submitted",
        "verified",
    }
)

# States that can still be retried safely without an explicit requeue.
_RESUMABLE_STATES = frozenset({"new", "jd_fetched"})

# Reasons that mean the job itself cannot be applied to (not a transient error).
BLOCKER_REASONS = frozenset({"already_applied", "job_closed", "no_easy_apply"})

_EVENT_BY_STATE = {
    "title_rejected": "rejected",
    "ineligible": "rejected",
    "jd_fetched": "jd_fetched",
    "eligible": "eligible",
    "failed": "failed",
    "applying": "attempt_started",
    "waiting_input": "waiting_input",
    "submitted": "submitted",
    "verified": "verified",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


@dataclass(frozen=True)
class Candidate:
    """One row received from discovery (pool TSV, enriched TSV or JSON)."""

    id: str
    title: str = ""
    company: str = ""
    location: str = ""
    workplace: str = ""
    is_remote: bool = False
    url: str = ""
    keyword: str = ""
    applied: bool = False
    closed: bool = False
    discarded: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "Candidate":
        if not isinstance(payload, Mapping):
            raise ValueError("each candidate must be a JSON object")
        raw_id = payload.get("id", payload.get("job_id"))
        job_id = str(raw_id).strip() if raw_id is not None else ""
        if not job_id:
            raise ValueError("candidate is missing a non-empty id")
        return cls(
            id=job_id,
            title=str(payload.get("title") or "").strip(),
            company=str(payload.get("company") or "").strip(),
            location=str(
                payload.get("location", payload.get("loc")) or ""
            ).strip(),
            workplace=str(
                payload.get("workplace", payload.get("workplace_type")) or ""
            ).strip(),
            is_remote=_as_bool(payload.get("is_remote")),
            url=str(payload.get("url") or "").strip(),
            keyword=str(payload.get("keyword") or "").strip(),
            applied=_as_bool(payload.get("applied", payload.get("already_applied"))),
            closed=_as_bool(payload.get("closed")),
            discarded=_as_bool(payload.get("discarded")),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "workplace": self.workplace,
            "is_remote": self.is_remote,
            "url": self.url,
            "keyword": self.keyword,
            "applied": self.applied,
            "closed": self.closed,
            "discarded": self.discarded,
        }


@dataclass
class StoredJob:
    candidate: Candidate
    state: str = "new"
    reason: str | None = None
    detail: dict[str, object] = field(default_factory=dict)
    jd_path: str | None = None
    profile: dict[str, object] | None = None
    decision: dict[str, object] | None = None
    attempts: int = 0
    enqueued_at: str = ""
    updated_at: str = ""

    @property
    def id(self) -> str:
        return self.candidate.id

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "candidate": self.candidate.as_dict(),
            "state": self.state,
            "reason": self.reason,
            "detail": dict(self.detail),
            "jd_path": self.jd_path,
            "profile": dict(self.profile) if self.profile is not None else None,
            "decision": dict(self.decision) if self.decision is not None else None,
            "attempts": self.attempts,
            "enqueued_at": self.enqueued_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "StoredJob":
        candidate_payload = payload.get("candidate")
        source = candidate_payload if isinstance(candidate_payload, Mapping) else payload
        candidate = Candidate.from_mapping(source)
        profile = payload.get("profile")
        decision = payload.get("decision")
        detail = payload.get("detail")
        attempts = payload.get("attempts")
        return cls(
            candidate=candidate,
            state=str(payload.get("state") or "new"),
            reason=_optional_str(payload.get("reason")),
            detail=dict(detail) if isinstance(detail, Mapping) else {},
            jd_path=_optional_str(payload.get("jd_path")),
            profile=dict(profile) if isinstance(profile, Mapping) else None,
            decision=dict(decision) if isinstance(decision, Mapping) else None,
            attempts=(
                attempts
                if isinstance(attempts, int) and not isinstance(attempts, bool)
                else 0
            ),
            enqueued_at=str(payload.get("enqueued_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
        )


@dataclass(frozen=True)
class EnqueueResult:
    job_id: str
    status: str
    reason: str | None
    state: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.job_id,
            "status": self.status,
            "reason": self.reason,
            "state": self.state,
        }


@dataclass(frozen=True)
class Selection:
    job_id: str
    candidate: Candidate
    jd_path: Path | None
    profile: Mapping[str, object] | None
    decision: Mapping[str, object] | None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.job_id,
            "candidate": self.candidate.as_dict(),
            "jd_path": str(self.jd_path) if self.jd_path is not None else None,
            "profile": dict(self.profile) if self.profile is not None else None,
            "decision": dict(self.decision) if self.decision is not None else None,
        }

    def as_job(self) -> dict[str, object]:
        """Flatten the selection into the job payload used by sessions/JSON."""
        job = self.candidate.as_dict()
        job["profile"] = dict(self.profile) if self.profile is not None else None
        job["decision"] = dict(self.decision) if self.decision is not None else None
        if self.jd_path is not None:
            job["jd_path"] = str(self.jd_path)
        return job


class JobQueue:
    """One JSON file under ``data/`` with a record per candidate id."""

    def __init__(
        self,
        path: Path,
        *,
        jds_dir: Path,
        clock: Callable[[], datetime] | None = None,
        assert_writable: Callable[[Path], None] | None = None,
    ) -> None:
        self.path = Path(path)
        self.jds_dir = Path(jds_dir)
        self.records: dict[str, StoredJob] = {}
        self.history: list[dict[str, object]] = []
        self._clock = clock or _utcnow
        self._assert_writable = assert_writable

    @classmethod
    def load(
        cls,
        paths: WorkspacePaths,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> "JobQueue":
        queue = cls(
            paths.data / QUEUE_FILENAME,
            jds_dir=paths.data / JD_DIRNAME,
            clock=clock,
            assert_writable=paths.assert_writable,
        )
        if not queue.path.is_file():
            return queue
        try:
            payload = json.loads(queue.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read queue {queue.path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"queue {queue.path} must contain a JSON object")
        records = payload.get("records")
        if not isinstance(records, list):
            raise ValueError(f"queue {queue.path} has no records list")
        for item in records:
            if not isinstance(item, Mapping):
                raise ValueError(f"queue {queue.path} has an invalid record")
            record = StoredJob.from_dict(item)
            queue.records[record.id] = record
        history = payload.get("history")
        if isinstance(history, list):
            queue.history = [
                dict(entry) for entry in history if isinstance(entry, Mapping)
            ]
        return queue

    def ingest(
        self,
        candidates: Iterable[Candidate],
        *,
        requeue_reason: str | None = None,
    ) -> list[EnqueueResult]:
        """Add candidates, keeping dedupe and terminal states explicit."""
        now = _iso(self._clock())
        results: list[EnqueueResult] = []
        for candidate in candidates:
            existing = self.records.get(candidate.id)
            if existing is not None:
                if requeue_reason:
                    previous = existing.state
                    existing.state = "new"
                    existing.reason = requeue_reason
                    existing.detail = {
                        "requeued_from": previous,
                        "reason": requeue_reason,
                    }
                    existing.attempts = 0
                    existing.updated_at = now
                    self._history(
                        existing.id,
                        "requeued",
                        state="new",
                        reason=requeue_reason,
                        detail={"from": previous},
                    )
                    results.append(
                        EnqueueResult(candidate.id, "requeued", requeue_reason, "new")
                    )
                    continue
                refused_state, refused_reason = _initial_state(candidate)
                if refused_state != "new" and existing.state not in _BLOCKING_STATES:
                    previous = existing.state
                    existing.state = refused_state
                    existing.reason = refused_reason
                    existing.detail = {}
                    existing.updated_at = now
                    self._history(
                        existing.id,
                        "rejected",
                        state=refused_state,
                        reason=refused_reason,
                        detail={"from": previous},
                    )
                    results.append(
                        EnqueueResult(
                            candidate.id,
                            "skipped",
                            refused_reason,
                            refused_state,
                        )
                    )
                    continue
                if existing.state in _BLOCKING_STATES:
                    reason = f"blocked:{existing.state}"
                    self._history(existing.id, "skipped", state=existing.state, reason=reason)
                    results.append(
                        EnqueueResult(candidate.id, "skipped", reason, existing.state)
                    )
                    continue
                self._history(existing.id, "skipped", state=existing.state, reason="duplicate")
                results.append(
                    EnqueueResult(candidate.id, "skipped", "duplicate", existing.state)
                )
                continue

            initial_state, initial_reason = _initial_state(candidate)
            record = StoredJob(
                candidate=candidate,
                state=initial_state,
                reason=initial_reason,
                enqueued_at=now,
                updated_at=now,
            )
            self.records[candidate.id] = record
            self._history(candidate.id, "enqueued", state=initial_state, reason=initial_reason)
            status = "enqueued" if initial_state == "new" else "skipped"
            results.append(EnqueueResult(candidate.id, status, initial_reason, initial_state))
        self.save()
        return results

    def pending(self) -> list[StoredJob]:
        return [
            record
            for record in self.records.values()
            if record.state in _RESUMABLE_STATES
        ]

    def backlog(self) -> int:
        """Records that still need work: ``new``, ``jd_fetched`` or ``eligible``."""
        return sum(
            1
            for record in self.records.values()
            if record.state in _RESUMABLE_STATES or record.state == "eligible"
        )

    def verified_for_run(self, run_id: str) -> list[str]:
        """Ids this run already confirmed, used to resume without double counting."""
        return [
            job_id
            for job_id, record in self.records.items()
            if record.state == "verified" and record.detail.get("run_id") == run_id
        ]

    def first_eligible(self) -> StoredJob | None:
        return next(
            (record for record in self.records.values() if record.state == "eligible"),
            None,
        )

    def get(self, job_id: str) -> StoredJob:
        return self.records[job_id]

    def mark(
        self,
        job_id: str,
        state: str,
        reason: str | None = None,
        detail: Mapping[str, object] | None = None,
        *,
        jd_path: Path | None = None,
        profile: Mapping[str, object] | None = None,
        decision: Mapping[str, object] | None = None,
    ) -> StoredJob:
        record = self.get(job_id)
        previous = record.state
        record.state = state
        record.reason = reason
        record.detail = dict(detail) if detail is not None else {}
        record.updated_at = _iso(self._clock())
        if jd_path is not None:
            record.jd_path = str(jd_path)
        if profile is not None:
            record.profile = dict(profile)
        if decision is not None:
            record.decision = dict(decision)
        self._history(
            job_id,
            _EVENT_BY_STATE.get(state, "state_changed"),
            state=state,
            reason=reason,
            detail={"from": previous, **record.detail},
        )
        self.save()
        return record

    def begin(self, job_id: str) -> StoredJob:
        record = self.get(job_id)
        if record.state != "eligible":
            raise ValueError(f"job {job_id} is not eligible for an attempt")
        record.attempts += 1
        return self.mark(
            job_id,
            "applying",
            None,
            {"attempt": record.attempts},
        )

    def complete(
        self,
        job_id: str,
        state: str,
        reason: str | None,
        detail: Mapping[str, object] | None = None,
    ) -> StoredJob:
        """Record the outcome of an application attempt."""
        return self.mark(job_id, state, reason, detail)

    def retry(self, job_id: str, reason: str | None) -> StoredJob:
        """Put a job that failed transiently back in the eligible slot.

        Attempts are kept: the daily loop uses them to enforce its per-job
        retry limit, so a retry can never restart the count.
        """
        record = self.get(job_id)
        return self.mark(
            job_id,
            "eligible",
            f"retry_scheduled:{reason}" if reason else "retry_scheduled",
            {"previous_reason": reason, "attempts": record.attempts},
        )

    def store_jd(self, job_id: str, text: str) -> Path:
        path = self.jds_dir / f"{job_id}.txt"
        self._writable(path)
        self.jds_dir.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".txt.tmp")
        temporary.write_text(
            text if text.endswith("\n") else text + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return path

    def snapshot(self) -> dict[str, object]:
        return {
            "version": QUEUE_VERSION,
            "updated_at": _iso(self._clock()),
            "records": [record.as_dict() for record in self.records.values()],
            "history": list(self.history),
        }

    def save(self) -> None:
        self._writable(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.snapshot(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def _writable(self, path: Path) -> None:
        if self._assert_writable is not None:
            self._assert_writable(path)

    def _history(
        self,
        job_id: str,
        action: str,
        *,
        state: str,
        reason: str | None,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self.history.append(
            {
                "ts": _iso(self._clock()),
                "id": job_id,
                "action": action,
                "state": state,
                "reason": reason,
                "detail": dict(detail) if detail is not None else {},
            }
        )


class QueueProcessor:
    """Run quick filters, fetch lazily and return the first eligible job."""

    def __init__(
        self,
        queue: JobQueue,
        fetcher: JobDescriptionFetcher,
        *,
        rules: EligibilityRules | None = None,
    ) -> None:
        self.queue = queue
        self.fetcher = fetcher
        self.rules = rules or EligibilityRules()

    def next_eligible(self) -> Selection | None:
        existing = self.queue.first_eligible()
        if existing is not None:
            return _selection(existing)

        for record in self.queue.pending():
            selection = self._process(record)
            if selection is not None:
                return selection
        return None

    def _process(self, record: StoredJob) -> Selection | None:
        candidate = record.candidate

        title = filter_title(candidate.title)
        if not title.accepted:
            self.queue.mark(
                record.id,
                "title_rejected",
                title.reason,
                {**title.detail, "filter": "title"},
            )
            return None

        location = filter_location(
            candidate.location,
            workplace=candidate.workplace,
            is_remote=candidate.is_remote,
        )
        if not location.accepted:
            # Location is a cheap pre-JD reject. The explicit lifecycle has no
            # location state, so record it as ineligible with the filter detail.
            self.queue.mark(
                record.id,
                "ineligible",
                location.reason,
                {**location.detail, "filter": "location"},
            )
            return None

        try:
            jd = self.fetcher.fetch(candidate.id)
        except JobDescriptionError as exc:
            self.queue.mark(
                record.id,
                "failed",
                exc.reason,
                {"message": str(exc), "retryable": True, "stage": "jd"},
            )
            return None

        jd_path = self.queue.store_jd(candidate.id, jd.text)
        self.queue.mark(
            record.id,
            "jd_fetched",
            None,
            {"jd_path": str(jd_path), "url": jd.url},
            jd_path=jd_path,
        )

        profile = build_job_profile(
            jd.text,
            title=candidate.title or jd.title,
        )
        decision = evaluate_eligibility(profile, self.rules)
        self.queue.mark(
            record.id,
            "eligible" if decision.eligible else "ineligible",
            decision.reason,
            decision.as_dict(),
            profile=profile.as_dict(),
            decision=decision.as_dict(),
        )
        if decision.eligible:
            return _selection(self.queue.get(record.id))
        return None


def load_candidates(path: Path) -> list[Candidate]:
    """Read a JSON array, a ``{"candidates": [...]}`` object or a TSV."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_json_candidates(path)
    if suffix in {".tsv", ".txt"}:
        return _load_tsv_candidates(path)
    raise ValueError(f"unsupported candidate file {path}: use .json or .tsv")


def _load_json_candidates(path: Path) -> list[Candidate]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read candidates from {path}: {exc}") from exc
    if isinstance(payload, dict):
        payload = payload.get("candidates", payload.get("jobs"))
        if not isinstance(payload, list):
            raise ValueError(f"{path} must contain a candidates list")
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a candidates list")
    candidates: list[Candidate] = []
    for index, item in enumerate(payload, start=1):
        try:
            candidates.append(Candidate.from_mapping(item))
        except ValueError as exc:
            raise ValueError(f"{path}: candidate {index}: {exc}") from exc
    return candidates


def _load_tsv_candidates(path: Path) -> list[Candidate]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise ValueError(f"could not read candidates from {path}: {exc}") from exc
    rows = [line for line in lines if line.strip()]
    if not rows:
        return []
    header = [column.strip().lower() for column in rows[0].split("\t")]
    if "id" not in header:
        raise ValueError(f"{path}: TSV header must contain an id column")
    if len(set(header)) != len(header):
        raise ValueError(f"{path}: TSV header has duplicate columns")

    candidates: list[Candidate] = []
    for line_number, line in enumerate(rows[1:], start=2):
        cells = line.split("\t")
        if len(cells) < len(header):
            cells.extend([""] * (len(header) - len(cells)))
        row = dict(zip(header, cells))
        try:
            candidates.append(Candidate.from_mapping(row))
        except ValueError as exc:
            raise ValueError(f"{path}: row {line_number}: {exc}") from exc
    return candidates


def _initial_state(candidate: Candidate) -> tuple[str, str | None]:
    if candidate.applied:
        return "ineligible", "already_applied"
    if candidate.closed:
        return "ineligible", "job_closed"
    if candidate.discarded:
        return "ineligible", "discarded"
    return "new", None


def _selection(record: StoredJob) -> Selection:
    return Selection(
        job_id=record.id,
        candidate=record.candidate,
        jd_path=Path(record.jd_path) if record.jd_path else None,
        profile=record.profile,
        decision=record.decision,
    )


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "sim"}
    return bool(value)


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def record_application_outcome(
    queue: JobQueue,
    job_id: str,
    payload: Mapping[str, object],
) -> StoredJob:
    """Map a ``career-ops-run`` job payload onto the queue state machine."""
    failure = payload.get("failure")
    reason = failure.get("reason") if isinstance(failure, Mapping) else None
    if not isinstance(reason, str):
        result = payload.get("result")
        reason = str(result.get("reason")) if isinstance(result, Mapping) else "unknown"

    if payload.get("status") == "verified":
        state = "verified"
    elif reason == "waiting_input":
        state = "waiting_input"
    elif reason in BLOCKER_REASONS:
        state = "ineligible"
    else:
        state = "failed"

    detail: dict[str, object] = {"run_id": payload.get("run_id"), "reason": reason}
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, Mapping) and artifacts.get("session_dir") is not None:
        detail["session_dir"] = artifacts["session_dir"]
    cv = payload.get("cv")
    if isinstance(cv, str) and cv:
        detail["cv"] = cv
    cv_cache = payload.get("cv_cache")
    if isinstance(cv_cache, Mapping):
        detail["cv_cache"] = dict(cv_cache)
    return queue.complete(job_id, state, reason, detail)

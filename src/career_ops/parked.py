"""Parked application forms that need a human answer.

A form that stops on an unknown question is left open in its browser tab because
reopening it loses the work already filled in.  The workspace keeps a single
``data/parked-form.json`` record with the job, the CDP target holding the tab,
the pending questions and the token that authorises a resume.  At most one form
is parked at a time; a second one is reported as a failure instead of replacing
the first.

`career-ops-reply` reads this record, validates the answers, appends them to the
workspace answers file and resumes the form through the same target.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from career_ops.adapter import PendingQuestion
from career_ops.paths import WorkspacePaths

PARKED_FILENAME = "parked-form.json"
PARKED_VERSION = 1
ANSWERS_FILENAME = "answers-hermes.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ParkedFormError(ValueError):
    """Base for parked-form persistence problems."""


class ParkedFormLimit(ParkedFormError):
    """Another job already owns the single parked tab."""

    def __init__(self, job_id: str) -> None:
        super().__init__(
            f"job {job_id} already has the parked form; close or answer it first"
        )
        self.job_id = job_id


@dataclass(frozen=True)
class ParkedForm:
    """The single form waiting for an answer."""

    token: str
    run_id: str
    job: Mapping[str, object]
    target: str | None
    cv: str | None
    questions: tuple[PendingQuestion, ...]
    session_dir: str | None
    target_goal: int
    parked_at: str

    @property
    def job_id(self) -> str:
        return str(self.job.get("id") or "")

    def as_dict(self) -> dict[str, object]:
        return {
            "version": PARKED_VERSION,
            "token": self.token,
            "run_id": self.run_id,
            "job": dict(self.job),
            "target": self.target,
            "cv": self.cv,
            "questions": [question.as_dict() for question in self.questions],
            "session_dir": self.session_dir,
            "target_goal": self.target_goal,
            "parked_at": self.parked_at,
            "answers_file": ANSWERS_FILENAME,
            "resume_hint": (
                "career-ops-reply --run-id {run_id} --job {job_id} "
                "--token {token} --answer '<question>=<answer>'"
            ).format(run_id=self.run_id, job_id=self.job_id, token=self.token),
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "ParkedForm":
        raw_job = payload.get("job")
        job = dict(raw_job) if isinstance(raw_job, Mapping) else {}
        if not str(job.get("id") or "").strip():
            raise ValueError("parked form has no job id")
        raw_questions = payload.get("questions")
        if not isinstance(raw_questions, list):
            raise ValueError("parked form has no questions list")
        questions = tuple(
            PendingQuestion.from_mapping(question)
            for question in raw_questions
            if isinstance(question, Mapping)
        )
        token = str(payload.get("token") or "").strip()
        if not token:
            raise ValueError("parked form has no resume token")
        return cls(
            token=token,
            run_id=str(payload.get("run_id") or ""),
            job=job,
            target=_optional_str(payload.get("target")),
            cv=_optional_str(payload.get("cv")),
            questions=questions,
            session_dir=_optional_str(payload.get("session_dir")),
            target_goal=_as_int(payload.get("target_goal")) or 1,
            parked_at=str(payload.get("parked_at") or ""),
        )


@dataclass
class ParkedFormStore:
    """Read, write and clear the single parked form under ``data/``."""

    paths: WorkspacePaths
    clock: Callable[[], datetime] = field(default=_utcnow, repr=False)

    @property
    def path(self) -> Path:
        return self.paths.data / PARKED_FILENAME

    @property
    def answers_path(self) -> Path:
        return self.paths.config / ANSWERS_FILENAME

    def load(self) -> ParkedForm | None:
        if not self.path.is_file():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read parked form {self.path}: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError(f"parked form {self.path} must contain a JSON object")
        return ParkedForm.from_mapping(payload)

    def park(
        self,
        *,
        run_id: str,
        job: Mapping[str, object],
        questions: Sequence[PendingQuestion],
        target: str | None,
        cv: str | Path | None,
        session_dir: str | None,
        target_goal: int,
    ) -> ParkedForm:
        job_id = str(job.get("id") or "").strip()
        if not job_id:
            raise ValueError("cannot park a form without a job id")
        current = self.load()
        if current is not None and current.job_id != job_id:
            raise ParkedFormLimit(current.job_id)
        token = current.token if current is not None else secrets.token_hex(8)
        parked = ParkedForm(
            token=token,
            run_id=run_id,
            job=dict(job),
            target=target,
            cv=str(cv) if cv is not None else None,
            questions=tuple(questions),
            session_dir=session_dir,
            target_goal=max(1, int(target_goal)),
            parked_at=self.clock().isoformat(),
        )
        self._write(parked)
        return parked

    def clear(self) -> None:
        if not self.path.is_file():
            return
        self._assert_writable(self.path)
        self.path.unlink()

    def _write(self, parked: ParkedForm) -> None:
        self._assert_writable(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(parked.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def _assert_writable(self, path: Path) -> None:
        self.paths.assert_writable(path)


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _as_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0

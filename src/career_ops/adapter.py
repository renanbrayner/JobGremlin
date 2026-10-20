"""Narrow contract between the one-job runner and a browser implementation.

The runner owns orchestration and observation; the adapter owns every external
side effect: opening the LinkedIn job, filling the Easy Apply form, selecting
the expected CV, clicking submit, verifying the result and taking screenshots.

Two implementations exist:

* ``career_ops.real_adapter.RealApplicationAdapter`` wraps the copied
  ``jobinfo``/``easyapply``/``cdp`` scripts without changing them;
* ``career_ops.fake_adapter.FakeApplicationAdapter`` lets the CLI acceptance
  tests exercise success, failure, a wrong CV and a renderer timeout without a
  browser.

The adapter bound to one job is also a ``SubmissionAdapter`` so the existing
``SubmissionGuard`` (#03) can enforce the CV check and the post-click rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from career_ops.submission import SubmissionAdapter


class AdapterError(RuntimeError):
    """A browser operation could not be completed."""

    reason = "adapter_error"


class AdapterUnavailable(AdapterError):
    """The adapter or one of the scripts it wraps is not usable."""

    reason = "adapter_unavailable"


class ApplicationFailed(AdapterError):
    """The application flow stopped before a verified submission."""

    reason = "application_failed"


class ParkedFormLost(AdapterError):
    """The tab holding a parked form no longer exists.

    The application may not have been submitted; the job must be reported as a
    recoverable failure so a later round can decide what to do, never as sent.
    """

    reason = "parked_form_lost"


@dataclass(frozen=True)
class PendingQuestion:
    """One unanswered form field, with the options needed to answer it."""

    text: str
    kind: str = "text"
    options: tuple[str, ...] = ()

    def as_text(self) -> str:
        """Legacy one-line form printed by ``easyapply`` and shown to humans."""
        if self.kind == "radio" and self.options:
            return f"? [radio: {' | '.join(self.options)}]  {self.text}"
        if self.kind == "check":
            return f"? [check] {self.text}"
        if self.kind == "select" and self.options:
            return f"SELECT: {self.text} [opcoes: {' | '.join(self.options)}]"
        return f"? {self.text}"

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "kind": self.kind,
            "options": list(self.options),
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "PendingQuestion":
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("pending question is missing a non-empty text")
        raw_options = payload.get("options")
        options = (
            tuple(str(option) for option in raw_options if str(option).strip())
            if isinstance(raw_options, (list, tuple))
            else ()
        )
        return cls(
            text=text,
            kind=str(payload.get("kind") or "text"),
            options=options,
        )


class WaitingForInput(AdapterError):
    """A required form question has no answer, so the form was left open."""

    reason = "waiting_input"

    def __init__(
        self,
        questions: Sequence[str | PendingQuestion] = (),
        *,
        target: str | None = None,
    ) -> None:
        self.pending = tuple(
            question
            if isinstance(question, PendingQuestion)
            else PendingQuestion(text=str(question))
            for question in questions
        )
        self.questions = tuple(question.as_text() for question in self.pending)
        self.target = target
        detail = f" ({len(self.questions)} pending question(s))" if self.questions else ""
        super().__init__(f"application is waiting for an answer{detail}")


class LinkedInDailyLimit(AdapterError):
    """LinkedIn reported that the account reached its daily application limit."""

    reason = "daily_limit"

    def __init__(self, message: str = "LinkedIn reported its daily application limit") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class JobInfo:
    """What opening a job page tells the runner before any form is touched."""

    id: str
    title: str = ""
    company: str = ""
    url: str = ""
    applied: bool = False
    easy_apply: bool = True
    closed: bool = False

    @property
    def blocker(self) -> str | None:
        """Return the reason this job must not be attempted, if any."""
        if self.applied:
            return "already_applied"
        if self.closed:
            return "job_closed"
        if not self.easy_apply:
            return "no_easy_apply"
        return None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "url": self.url,
            "applied": self.applied,
            "easy_apply": self.easy_apply,
            "closed": self.closed,
        }


class ApplicationAdapter(SubmissionAdapter, Protocol):
    """Every external effect one application attempt needs."""

    def open(self) -> JobInfo:
        """Open the job page and report its state before the form is filled."""

    def capture(self, path: Path) -> None:
        """Write a screenshot to ``path`` for the session recorder."""

    def recover(self) -> None:
        """Make the browser usable again after a renderer timeout."""

    def discard_waiting_form(self) -> None:
        """Close the tab of a form that could not be parked (best effort)."""

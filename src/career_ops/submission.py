"""Guard the final submission with a CV check and a renderer deadline.

The 19/10 reference round read 12 JDs, found 4 eligible jobs and submitted
none: the renderer froze during the CV upload and the whole batch was lost.
This module turns that failure mode into an explicit, retryable result:

* the adapter first attaches the tailored PDF under the renderer deadline;
* only the *selected* CV is read back and compared with the expected PDF
  before the submit button is clicked; a mismatch is a fatal failure and can
  never be counted as submitted;
* the failure is recorded through ``SessionRecorder`` (whose CDP timeout falls
  back to ``grim``) and the browser can be recovered before a second attempt;
* a timeout during or after the submit click is never retried automatically,
  because the click may already have gone through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Protocol, Sequence

from career_ops.cv_attachment import CvAttachmentCheck, WrongCvAttached, verify_cv_attachment
from career_ops.renderer import RendererError, RendererTimeout, RendererWatchdog
from career_ops.session import SessionRecorder

DEFAULT_SUBMISSION_ATTEMPTS = 2
Status = Literal["submitted", "failed"]


class SubmissionAdapter(Protocol):
    """The narrow browser surface the guard needs from the application adapter."""

    def attach(self, expected_cv: Path) -> None:
        """Make ``expected_cv`` the selected CV, uploading or selecting it.

        Must be idempotent: a retry calls this again after recovery.  The
        adapter should leave the form in a safe state even when the upload is
        not possible (never select a different PDF).
        """

    def selected_cvs(self) -> Sequence[str]:
        """Return only the currently selected CV name(s), not the library."""

    def submit(self) -> None:
        """Click the final submit button."""

    def verify(self) -> bool:
        """Return True only when LinkedIn confirms the application was sent."""


@dataclass(frozen=True)
class SubmissionResult:
    """Outcome of one guarded submission.

    ``submitted`` is the single source of truth: it is True only after the
    adapter attached the expected CV, the click happened and LinkedIn
    confirmed it.  ``clicked`` records the weaker fact that the submit button
    was pressed, which the daily funnel reports separately from ``verified``.
    """

    submitted: bool
    attempts: int
    reason: str
    retryable: bool = False
    expected_cv: str | None = None
    selected_cvs: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = field(default_factory=tuple)
    clicked: bool = False

    @property
    def status(self) -> Status:
        return "submitted" if self.submitted else "failed"

    @property
    def verified(self) -> bool:
        return self.submitted

    @property
    def ok(self) -> bool:
        return self.submitted


class SubmissionGuard:
    """Apply the CV check, submit and verify, recovering from renderer freezes."""

    def __init__(
        self,
        session: SessionRecorder,
        watchdog: RendererWatchdog,
        *,
        max_attempts: int = DEFAULT_SUBMISSION_ATTEMPTS,
        recover: Callable[[], object] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.session = session
        self.watchdog = watchdog
        self.max_attempts = max_attempts
        self.recover = recover

    def submit(
        self,
        *,
        job_id: str,
        expected_cv: str | Path,
        adapter: SubmissionAdapter,
    ) -> SubmissionResult:
        artifacts: list[str] = []
        selected_cvs: tuple[str, ...] = ()
        attempts = 0

        for attempt in range(1, self.max_attempts + 1):
            attempts = attempt
            submit_started = False
            try:
                expected_path = Path(expected_cv)
                self.watchdog.run(
                    lambda: adapter.attach(expected_path),
                    label="upload CV",
                )
                selected_cvs = tuple(
                    self.watchdog.run(
                        adapter.selected_cvs,
                        label="read selected CV",
                    )
                )
                check = verify_cv_attachment(expected_cv, selected_cvs)

                if not check.ok:
                    artifacts.extend(
                        _capture(
                            self.session,
                            "review",
                            job_id=job_id,
                            status="failed",
                            detail=check.detail(),
                        )
                    )
                    failure = self.session.fail(
                        WrongCvAttached(check),
                        job_id=job_id,
                        detail=check.detail(),
                    )
                    artifacts.extend(_artifact(failure))
                    return _result(
                        submitted=False,
                        attempts=attempts,
                        reason="missing_cv" if check.reason == "missing" else "wrong_cv",
                        retryable=False,
                        check=check,
                        artifacts=artifacts,
                    )

                artifacts.extend(
                    _capture(
                        self.session,
                        "cv_selection",
                        job_id=job_id,
                        detail=check.detail(),
                    )
                )
                artifacts.extend(_capture(self.session, "review", job_id=job_id))

                # From here on a timeout is ambiguous: the click may have
                # reached LinkedIn.  Record the uncertainty and never click
                # "Submit" a second time in this call.
                submit_started = True
                self.watchdog.run(adapter.submit, label="submit application")
                artifacts.extend(_capture(self.session, "submit", job_id=job_id))

                verified = bool(
                    self.watchdog.run(adapter.verify, label="verify submission")
                )
                if verified:
                    return _result(
                        submitted=True,
                        attempts=attempts,
                        reason="verified",
                        check=check,
                        artifacts=artifacts,
                        clicked=True,
                    )

                failure = self.session.fail(
                    "LinkedIn did not confirm the application",
                    job_id=job_id,
                    detail={"reason": "not_confirmed", "attempt": attempt},
                )
                artifacts.extend(_artifact(failure))
                return _result(
                    submitted=False,
                    attempts=attempts,
                    reason="not_confirmed",
                    # The click already happened; a loop retry could apply twice.
                    retryable=False,
                    check=check,
                    artifacts=artifacts,
                    clicked=True,
                )

            except TimeoutError as exc:
                # RendererTimeout is raised by our watchdog; a raw TimeoutError
                # can still come from the CDP socket's own deadline.
                label = exc.label if isinstance(exc, RendererTimeout) else "renderer"
                timeout = (
                    exc.timeout if isinstance(exc, RendererTimeout) else self.watchdog.timeout
                )
                failure = self.session.fail(
                    exc,
                    job_id=job_id,
                    detail={
                        "reason": "renderer_timeout",
                        "operation": label,
                        "timeout_seconds": timeout,
                        "attempt": attempt,
                        "submit_started": submit_started,
                    },
                )
                artifacts.extend(_artifact(failure))

                if submit_started:
                    # The application may already be registered; never resubmit.
                    return _result(
                        submitted=False,
                        attempts=attempt,
                        reason="renderer_timeout_after_submit",
                        retryable=False,
                        selected_cvs=selected_cvs,
                        artifacts=artifacts,
                        clicked=True,
                    )

                if attempt >= self.max_attempts or self.recover is None:
                    return _result(
                        submitted=False,
                        attempts=attempt,
                        reason="renderer_timeout",
                        retryable=True,
                        selected_cvs=selected_cvs,
                        artifacts=artifacts,
                    )

                try:
                    self.recover()
                except (RendererError, OSError) as recovery_exc:
                    recovery_failure = self.session.fail(
                        recovery_exc,
                        job_id=job_id,
                        detail={
                            "reason": "renderer_recovery_failed",
                            "operation": label,
                            "attempt": attempt,
                        },
                    )
                    artifacts.extend(_artifact(recovery_failure))
                    return _result(
                        submitted=False,
                        attempts=attempt,
                        reason="renderer_recovery_failed",
                        retryable=True,
                        selected_cvs=selected_cvs,
                        artifacts=artifacts,
                    )
                # Recover succeeded: loop re-attaches, re-checks the selected
                # CV and only then touches the submit button again.

        # The loop always returns; this is only for the type checker.
        return _result(
            submitted=False,
            attempts=attempts,
            reason="exhausted",
            retryable=True,
            selected_cvs=selected_cvs,
            artifacts=artifacts,
        )


def _result(
    *,
    submitted: bool,
    attempts: int,
    reason: str,
    retryable: bool = False,
    check: CvAttachmentCheck | None = None,
    selected_cvs: tuple[str, ...] = (),
    artifacts: list[str],
    clicked: bool = False,
) -> SubmissionResult:
    return SubmissionResult(
        submitted=submitted,
        attempts=attempts,
        reason=reason,
        retryable=retryable,
        expected_cv=check.expected if check is not None else None,
        selected_cvs=check.selected if check is not None else selected_cvs,
        artifacts=tuple(dict.fromkeys(artifacts)),
        clicked=clicked,
    )


def _artifact(event: dict) -> list[str]:
    artifact = event.get("artifact")
    return [str(artifact)] if artifact else []


def _capture(
    session: SessionRecorder,
    stage: str,
    **kwargs: object,
) -> list[str]:
    """Capture evidence without letting a screenshot problem change the outcome."""
    try:
        event = session.capture(stage, **kwargs)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - evidence must never mask the application result
        return []
    return _artifact(event)

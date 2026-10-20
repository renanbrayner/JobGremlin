from __future__ import annotations

from pathlib import Path

import pytest

from career_ops.capture import CaptureTimeout
from career_ops.renderer import RendererRecoveryFailed, RendererTimeout, RendererWatchdog
from career_ops.session import SessionRecorder
from career_ops.submission import SubmissionGuard
from conftest import FakeScreenshotter, read_events


class FrozenCdp:
    def __call__(self, path: Path) -> None:
        raise CaptureTimeout("Runtime.evaluate did not answer")


class FakeAdapter:
    def __init__(
        self,
        selected: list[str] | None = None,
        *,
        verified: bool = True,
        freeze_attach_calls: int = 0,
        freeze_selected_calls: int = 0,
        freeze_submit: bool = False,
    ) -> None:
        self.selected = list(selected or [])
        self.verified = verified
        self.freeze_attach_calls = freeze_attach_calls
        self.freeze_selected_calls = freeze_selected_calls
        self.freeze_submit = freeze_submit
        self.attach_calls = 0
        self.selected_calls = 0
        self.submit_calls = 0
        self.verify_calls = 0
        self.attached_paths: list[Path] = []

    def attach(self, expected_cv: Path) -> None:
        self.attach_calls += 1
        self.attached_paths.append(expected_cv)
        if self.attach_calls <= self.freeze_attach_calls:
            raise RendererTimeout("upload CV", 30)

    def selected_cvs(self):
        self.selected_calls += 1
        if self.selected_calls <= self.freeze_selected_calls:
            raise RendererTimeout("read selected CV", 30)
        return self.selected

    def submit(self):
        self.submit_calls += 1
        if self.freeze_submit:
            raise RendererTimeout("submit application", 30)

    def verify(self):
        self.verify_calls += 1
        return self.verified


def _session(paths, *, screenshotter=None, fallback=None) -> SessionRecorder:
    return SessionRecorder.create(
        paths,
        run_id="2026-10-19-morning",
        job={"id": "4411222"},
        screenshotter=screenshotter,
        fallback=fallback,
    )


def test_a_verified_submission_is_the_only_success(paths):
    session = _session(paths, screenshotter=FakeScreenshotter())
    adapter = FakeAdapter(["cv-renan-react-2026-10-19.pdf"])
    guard = SubmissionGuard(session, RendererWatchdog(1.0))

    result = guard.submit(
        job_id="4411222",
        expected_cv="/tmp/cv-renan-react-2026-10-19.pdf",
        adapter=adapter,
    )

    assert result.status == "submitted"
    assert result.submitted is True
    assert result.verified is True
    assert result.attempts == 1
    assert result.reason == "verified"
    assert result.retryable is False
    assert result.expected_cv == "cv-renan-react-2026-10-19.pdf"
    assert result.selected_cvs == ("cv-renan-react-2026-10-19.pdf",)
    assert adapter.attach_calls == 1
    assert adapter.attached_paths == [Path("/tmp/cv-renan-react-2026-10-19.pdf")]
    assert [event["stage"] for event in read_events(session)] == [
        "cv_selection",
        "review",
        "submit",
    ]
    assert adapter.submit_calls == 1
    assert adapter.verify_calls == 1
    for artifact in result.artifacts:
        assert session.root.joinpath(artifact).is_file()


@pytest.mark.parametrize(
    ("selected", "reason", "detail_reason"),
    [
        (["cv-renan-crossing-en-2026-10-06.pdf"], "wrong_cv", "wrong_cv"),
        ([], "missing_cv", "missing"),
    ],
)
def test_the_wrong_or_missing_selected_cv_aborts_before_the_submit_click(
    paths, selected, reason, detail_reason
):
    session = _session(paths, screenshotter=FakeScreenshotter())
    adapter = FakeAdapter(selected)
    guard = SubmissionGuard(session, RendererWatchdog(1.0))

    result = guard.submit(
        job_id="4411222",
        expected_cv="cv-renan-react-2026-10-19.pdf",
        adapter=adapter,
    )

    assert result.status == "failed"
    assert result.submitted is False
    assert result.verified is False
    assert result.reason == reason
    assert result.retryable is False
    assert adapter.attach_calls == 1
    assert adapter.submit_calls == 0
    assert adapter.verify_calls == 0

    events = read_events(session)
    assert [event["stage"] for event in events] == ["review", "error"]
    assert events[0]["status"] == "failed"
    assert events[1]["status"] == "failed"
    assert events[1]["detail"]["reason"] == detail_reason
    assert events[1]["detail"]["expected_cv"] == "cv-renan-react-2026-10-19.pdf"
    assert result.artifacts
    assert all(session.root.joinpath(artifact).is_file() for artifact in result.artifacts)


def test_a_submission_that_linkedin_does_not_confirm_is_not_counted(paths):
    session = _session(paths, screenshotter=FakeScreenshotter())
    adapter = FakeAdapter(["cv-renan-react-2026-10-19.pdf"], verified=False)
    guard = SubmissionGuard(session, RendererWatchdog(1.0))

    result = guard.submit(
        job_id="4411222",
        expected_cv="cv-renan-react-2026-10-19.pdf",
        adapter=adapter,
    )

    assert result.status == "failed"
    assert result.submitted is False
    assert result.verified is False
    assert result.reason == "not_confirmed"
    # The click already happened; retrying could double-apply.
    assert result.retryable is False
    assert adapter.submit_calls == 1
    assert read_events(session)[-1]["stage"] == "error"


def test_the_19_10_freeze_is_retried_without_losing_the_evidence(paths):
    """Regression: the CV upload froze the renderer and the round submitted 0."""
    session = _session(paths, screenshotter=FrozenCdp(), fallback=FakeScreenshotter(b"grim"))
    adapter = FakeAdapter(
        ["cv-renan-react-2026-10-19.pdf"],
        freeze_attach_calls=1,
    )
    recoveries: list[str] = []
    guard = SubmissionGuard(
        session,
        RendererWatchdog(1.0),
        recover=lambda: recoveries.append("reconnected"),
    )

    result = guard.submit(
        job_id="4411222",
        expected_cv="cv-renan-react-2026-10-19.pdf",
        adapter=adapter,
    )

    assert result.status == "submitted"
    assert result.submitted is True
    assert result.attempts == 2
    assert result.reason == "verified"
    assert recoveries == ["reconnected"]
    # The retry re-attaches, re-checks only the selected CV, and submits once.
    assert adapter.attach_calls == 2
    assert adapter.selected_calls == 1
    assert adapter.submit_calls == 1
    assert adapter.verify_calls == 1

    events = read_events(session)
    assert [event["stage"] for event in events] == [
        "error",
        "cv_selection",
        "review",
        "submit",
    ]
    frozen = events[0]
    assert frozen["status"] == "failed"
    assert frozen["detail"]["reason"] == "renderer_timeout"
    assert frozen["detail"]["operation"] == "upload CV"
    assert frozen["detail"]["submit_started"] is False
    assert frozen["detail"]["capture_source"] == "fallback"
    assert frozen["artifact"] == "screenshots/error.png"
    assert session.root.joinpath(frozen["artifact"]).read_bytes() == b"grim"


def test_a_raw_socket_timeout_is_treated_like_a_renderer_timeout(paths):
    session = _session(paths, screenshotter=FakeScreenshotter())

    class SocketTimeoutAdapter(FakeAdapter):
        def attach(self, expected_cv: Path) -> None:
            self.attach_calls += 1
            raise TimeoutError("DOM.setFileInputFiles timed out")

    adapter = SocketTimeoutAdapter()
    guard = SubmissionGuard(session, RendererWatchdog(1.0))

    result = guard.submit(
        job_id="4411222",
        expected_cv="cv-renan-react-2026-10-19.pdf",
        adapter=adapter,
    )

    assert result.status == "failed"
    assert result.submitted is False
    assert result.reason == "renderer_timeout"
    assert adapter.submit_calls == 0
    assert read_events(session)[-1]["detail"]["operation"] == "renderer"


def test_a_timeout_after_the_submit_click_is_never_retried(paths):
    session = _session(paths, screenshotter=FakeScreenshotter())
    adapter = FakeAdapter(["cv-renan-react-2026-10-19.pdf"], freeze_submit=True)
    recoveries: list[str] = []
    guard = SubmissionGuard(
        session,
        RendererWatchdog(1.0),
        recover=lambda: recoveries.append("would reconnect"),
    )

    result = guard.submit(
        job_id="4411222",
        expected_cv="cv-renan-react-2026-10-19.pdf",
        adapter=adapter,
    )

    assert result.status == "failed"
    assert result.submitted is False
    assert result.reason == "renderer_timeout_after_submit"
    # The click may already have registered; do not feed this to a retry loop.
    assert result.retryable is False
    assert result.attempts == 1
    assert adapter.submit_calls == 1
    assert recoveries == []
    assert read_events(session)[-1]["detail"]["submit_started"] is True


def test_a_failed_recovery_stops_before_a_second_submit(paths):
    session = _session(paths, screenshotter=FakeScreenshotter())
    adapter = FakeAdapter(freeze_attach_calls=2)

    def fail_recovery():
        raise RendererRecoveryFailed("renderer still unresponsive")

    guard = SubmissionGuard(session, RendererWatchdog(1.0), recover=fail_recovery)

    result = guard.submit(
        job_id="4411222",
        expected_cv="cv-renan-react-2026-10-19.pdf",
        adapter=adapter,
    )

    assert result.status == "failed"
    assert result.submitted is False
    assert result.reason == "renderer_recovery_failed"
    assert result.retryable is True
    assert result.attempts == 1
    assert adapter.submit_calls == 0


def test_two_freezes_exhaust_the_attempts_without_submitting(paths):
    session = _session(paths, screenshotter=FakeScreenshotter())
    adapter = FakeAdapter(freeze_attach_calls=2)
    recoveries: list[str] = []
    guard = SubmissionGuard(
        session,
        RendererWatchdog(1.0),
        recover=lambda: recoveries.append("ok"),
    )

    result = guard.submit(
        job_id="4411222",
        expected_cv="cv-renan-react-2026-10-19.pdf",
        adapter=adapter,
    )

    assert result.status == "failed"
    assert result.submitted is False
    assert result.reason == "renderer_timeout"
    assert result.attempts == 2
    assert recoveries == ["ok"]
    assert adapter.attach_calls == 2
    assert adapter.submit_calls == 0
    error_artifacts = [
        event["artifact"] for event in read_events(session) if event["stage"] == "error"
    ]
    assert error_artifacts == ["screenshots/error.png", "screenshots/error-2.png"]

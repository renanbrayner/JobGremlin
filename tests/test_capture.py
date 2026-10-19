from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from career_ops.capture import (
    CaptureError,
    CaptureTimeout,
    capture_with_fallback,
    cdp_screenshotter,
    grim_screenshotter,
)


class RecordingShot:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[Path] = []

    def __call__(self, path: Path) -> None:
        self.calls.append(path)
        if self.error is not None:
            raise self.error
        path.write_bytes(b"fake-png")


class FakeRunner:
    def __init__(
        self,
        *,
        returncode: int = 0,
        error: Exception | None = None,
        stderr: str = "boom",
    ) -> None:
        self.returncode = returncode
        self.error = error
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if self.error is not None:
            raise self.error
        if self.returncode == 0:
            Path(argv[-1]).write_bytes(b"command-png")
        return subprocess.CompletedProcess(argv, self.returncode, "", self.stderr)


def test_a_working_primary_capture_does_not_run_the_fallback(tmp_path):
    primary = RecordingShot()
    fallback = RecordingShot()
    path = tmp_path / "shot.png"

    result = capture_with_fallback(primary, path, fallback)

    assert result.status == "ok"
    assert result.source == "primary"
    assert result.error is None
    assert path.read_bytes() == b"fake-png"
    assert fallback.calls == []


def test_a_cdp_timeout_falls_back_to_the_system_capture(tmp_path):
    primary = RecordingShot(CaptureTimeout("CDP did not answer"))
    fallback = RecordingShot()
    path = tmp_path / "shot.png"

    result = capture_with_fallback(primary, path, fallback)

    assert result.status == "timeout"
    assert result.source == "fallback"
    assert "CDP did not answer" in result.error
    assert path.read_bytes() == b"fake-png"
    assert primary.calls == [path]
    assert fallback.calls == [path]


def test_a_timeout_without_a_fallback_is_marked_as_timeout(tmp_path):
    primary = RecordingShot(CaptureTimeout("renderer frozen"))

    result = capture_with_fallback(primary, tmp_path / "shot.png")

    assert result.status == "timeout"
    assert result.source is None
    assert result.error == "renderer frozen"


def test_a_failed_fallback_keeps_both_errors_and_no_artifact(tmp_path):
    primary = RecordingShot(CaptureTimeout("CDP did not answer"))
    fallback = RecordingShot(CaptureError("grim is not installed"))
    path = tmp_path / "shot.png"

    result = capture_with_fallback(primary, path, fallback)

    assert result.status == "failed"
    assert result.source is None
    assert "CDP did not answer" in result.error
    assert "grim is not installed" in result.error
    assert not path.exists()


def test_a_non_timeout_capture_error_does_not_run_the_fallback(tmp_path):
    primary = RecordingShot(CaptureError("page is closed"))
    fallback = RecordingShot()

    result = capture_with_fallback(primary, tmp_path / "shot.png", fallback)

    assert result.status == "failed"
    assert result.error == "page is closed"
    assert fallback.calls == []


def test_command_screenshotter_maps_a_timeout_to_capture_timeout(tmp_path):
    runner = FakeRunner(error=subprocess.TimeoutExpired(["cdp"], 10))
    shot = cdp_screenshotter(tmp_path / "scripts", timeout=10, runner=runner)

    with pytest.raises(CaptureTimeout, match="timed out"):
        shot(tmp_path / "shot.png")

    assert runner.calls == [[str(tmp_path / "scripts" / "cdp"), "shot", str(tmp_path / "shot.png")]]


def test_command_screenshotter_maps_a_bad_exit_to_capture_error(tmp_path):
    runner = FakeRunner(returncode=1)
    shot = grim_screenshotter(runner=runner)

    with pytest.raises(CaptureError, match="grim exited 1: boom"):
        shot(tmp_path / "shot.png")

    assert runner.calls == [["grim", "-t", "png", str(tmp_path / "shot.png")]]


def test_command_screenshotter_maps_a_timeout_message_to_capture_timeout(tmp_path):
    runner = FakeRunner(
        returncode=1,
        stderr="Traceback ... TimeoutError: Page.captureScreenshot",
    )
    shot = cdp_screenshotter(tmp_path / "scripts", runner=runner)

    with pytest.raises(CaptureTimeout, match="TimeoutError"):
        shot(tmp_path / "shot.png")


def test_an_unexpected_capture_exception_becomes_a_failed_result(tmp_path):
    class Exploding:
        def __call__(self, path: Path) -> None:
            raise ValueError("bad adapter")

    result = capture_with_fallback(Exploding(), tmp_path / "shot.png")

    assert result.status == "failed"
    assert result.error == "unexpected capture error: bad adapter"


def test_command_screenshotter_rejects_a_zero_exit_without_a_file(tmp_path):
    class SilentRunner:
        def __call__(self, argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, "", "")

    shot = grim_screenshotter(runner=SilentRunner())

    with pytest.raises(CaptureError, match="wrote no screenshot"):
        shot(tmp_path / "shot.png")

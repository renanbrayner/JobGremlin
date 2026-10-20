from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from career_ops.capture import CaptureTimeout
from career_ops.session import SessionRecorder
from conftest import FakeClock, FakeScreenshotter, read_events

UTC = timezone.utc


def test_an_application_run_creates_a_session_directory_with_metadata(paths, workspace):
    clock = FakeClock(datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC))

    recorder = SessionRecorder.create(
        paths,
        run_id="2026-10-19-morning",
        job={"id": "4411222", "title": "Staff Engineer", "company": "Acme"},
        clock=clock,
    )

    assert recorder.root == workspace / "output" / "sessions" / "2026-10-19-morning"
    assert recorder.events_path == recorder.root / "events.jsonl"
    assert recorder.screenshots_dir == recorder.root / "screenshots"
    assert recorder.events_path.is_file()
    assert recorder.events_path.read_text(encoding="utf-8") == ""
    assert recorder.screenshots_dir.is_dir()

    metadata = json.loads((recorder.root / "session.json").read_text(encoding="utf-8"))
    assert metadata == {
        "run_id": "2026-10-19-morning",
        "status": "running",
        "created_at": "2026-10-19T12:00:00+00:00",
        "finished_at": None,
        "job": {"id": "4411222", "title": "Staff Engineer", "company": "Acme"},
    }


def test_closing_a_session_records_its_final_status(paths):
    clock = FakeClock(datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC))
    recorder = SessionRecorder.create(paths, run_id="run-1", clock=clock)

    clock.advance(1500)
    recorder.close("completed")

    metadata = json.loads((recorder.root / "session.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "completed"
    assert metadata["finished_at"] == "2026-10-19T12:00:01.500000+00:00"


def test_a_recorded_event_has_the_observability_schema(paths):
    clock = FakeClock(datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC))
    recorder = SessionRecorder.create(
        paths,
        run_id="run-1",
        job={"id": "4411222"},
        clock=clock,
    )

    clock.advance(320)
    event = recorder.record("open", "ok", duration_ms=320)

    assert list(event) == [
        "ts",
        "run_id",
        "job_id",
        "stage",
        "page",
        "status",
        "duration_ms",
        "artifact",
        "detail",
    ]
    assert event["ts"] == "2026-10-19T12:00:00.320000+00:00"
    assert event["run_id"] == "run-1"
    assert event["job_id"] == "4411222"
    assert event["stage"] == "open"
    assert event["page"] is None
    assert event["status"] == "ok"
    assert event["duration_ms"] == 320
    assert event["artifact"] is None
    assert event["detail"] is None

    assert read_events(recorder) == [event]


def test_screenshots_get_stable_names_and_are_referenced_by_their_events(paths):
    clock = FakeClock(datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC))
    shot = FakeScreenshotter()
    recorder = SessionRecorder.create(
        paths,
        run_id="run-1",
        job={"id": "4411222"},
        clock=clock,
        screenshotter=shot,
    )

    opened = recorder.capture("open")
    page_one = recorder.capture("form_page", page=1)
    page_two = recorder.capture("form_page", page=2)
    cv_selection = recorder.capture("cv_selection")
    recorder.capture("review")
    recorder.capture("submit")
    waiting = recorder.capture("waiting")
    error = recorder.capture("error", status="failed", detail={"reason": "renderer frozen"})

    assert recorder.root.joinpath(opened["artifact"]).read_bytes() == b"png-bytes"
    assert [event["artifact"] for event in read_events(recorder)] == [
        "screenshots/open.png",
        "screenshots/form-page-1.png",
        "screenshots/form-page-2.png",
        "screenshots/cv-selection.png",
        "screenshots/review.png",
        "screenshots/submit.png",
        "screenshots/waiting.png",
        "screenshots/error.png",
    ]
    assert page_one["page"] == 1
    assert page_two["page"] == 2
    assert cv_selection["stage"] == "cv_selection"
    assert waiting["stage"] == "waiting"
    assert error["status"] == "failed"
    assert error["detail"] == {"reason": "renderer frozen"}
    assert len(shot.calls) == 8


def test_the_same_stage_reuses_the_same_name_across_sessions(paths):
    clock = FakeClock(datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC))

    first = SessionRecorder.create(
        paths, run_id="run-1", clock=clock, screenshotter=FakeScreenshotter()
    )
    first.capture("open")
    second = SessionRecorder.create(
        paths, run_id="run-2", clock=clock, screenshotter=FakeScreenshotter()
    )
    second.capture("open")

    assert first.root.joinpath("screenshots/open.png").is_file()
    assert second.root.joinpath("screenshots/open.png").is_file()


def test_a_repeated_stage_gets_a_suffix_without_renaming_earlier_shots(paths):
    clock = FakeClock(datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC))
    recorder = SessionRecorder.create(
        paths, run_id="run-1", clock=clock, screenshotter=FakeScreenshotter()
    )

    first = recorder.capture("error")
    second = recorder.capture("error")

    assert first["artifact"] == "screenshots/error.png"
    assert second["artifact"] == "screenshots/error-2.png"
    assert recorder.root.joinpath(first["artifact"]).is_file()
    assert recorder.root.joinpath(second["artifact"]).is_file()


def test_a_session_records_the_grim_fallback_when_cdp_times_out(paths):
    clock = FakeClock(datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC))
    fallback = FakeScreenshotter(b"grim-png")

    def frozen_cdp(path: Path) -> None:
        raise CaptureTimeout("CDP did not answer")

    recorder = SessionRecorder.create(
        paths,
        run_id="run-1",
        job={"id": "4411222"},
        clock=clock,
        screenshotter=frozen_cdp,
        fallback=fallback,
    )

    event = recorder.capture("open")

    assert event["status"] == "ok"
    assert event["artifact"] == "screenshots/open.png"
    assert recorder.root.joinpath(event["artifact"]).read_bytes() == b"grim-png"
    assert event["detail"] == {"capture_error": "CDP did not answer", "capture_source": "fallback"}


def test_fail_keeps_the_application_error_when_grim_fallback_is_used(paths):
    clock = FakeClock(datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC))
    fallback = FakeScreenshotter(b"grim-png")

    def frozen_cdp(path: Path) -> None:
        raise CaptureTimeout("CDP did not answer")

    recorder = SessionRecorder.create(
        paths,
        run_id="run-1",
        clock=clock,
        screenshotter=frozen_cdp,
        fallback=fallback,
    )

    event = recorder.fail("vaga fechada")

    assert event["status"] == "failed"
    assert event["detail"] == {
        "error": "vaga fechada",
        "capture_error": "CDP did not answer",
        "capture_source": "fallback",
    }
    assert recorder.root.joinpath(event["artifact"]).read_bytes() == b"grim-png"


def test_a_returned_failure_records_an_error_screenshot(paths):
    clock = FakeClock(datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC))
    recorder = SessionRecorder.create(
        paths,
        run_id="run-1",
        job={"id": "4411222"},
        clock=clock,
        screenshotter=FakeScreenshotter(),
    )

    event = recorder.fail("vaga fechada")
    recorder.close("failed")

    assert event["stage"] == "error"
    assert event["status"] == "failed"
    assert event["detail"] == {"error": "vaga fechada"}
    assert recorder.root.joinpath(event["artifact"]).is_file()
    metadata = json.loads((recorder.root / "session.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"


def test_a_failed_application_still_leaves_an_inspectable_session(paths):
    clock = FakeClock(datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC))
    shopper = FakeScreenshotter()
    recorder = SessionRecorder.create(
        paths,
        run_id="run-1",
        job={"id": "4411222"},
        clock=clock,
        screenshotter=shopper,
    )

    with pytest.raises(RuntimeError, match="apply exploded"):
        with recorder:
            recorder.capture("open")
            raise RuntimeError("apply exploded")

    metadata = json.loads((recorder.root / "session.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["finished_at"] is not None

    events = read_events(recorder)
    assert [event["stage"] for event in events] == ["open", "error"]
    assert events[-1]["status"] == "failed"
    assert events[-1]["detail"] == {"error": "RuntimeError: apply exploded"}
    assert recorder.root.joinpath(events[-1]["artifact"]).is_file()

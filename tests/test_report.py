from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from career_ops.queue import Candidate, JobQueue
from career_ops.report import build_run_report, latest_run_id, prune_runs
from career_ops.run_state import RunState
from career_ops.session import SessionRecorder
from conftest import FakeClock, FakeScreenshotter

UTC = timezone.utc


def _session(paths, clock, run_id: str, job_id: str) -> SessionRecorder:
    recorder = SessionRecorder.create(
        paths,
        run_id=run_id,
        job={"id": job_id},
        clock=clock,
        screenshotter=FakeScreenshotter(),
        subdir=job_id,
    )
    recorder.capture("open")
    recorder.capture("review")
    recorder.close("completed")
    return recorder


def _verified_report_fixture(paths, workspace: Path) -> tuple[str, FakeClock]:
    run_id = "daily-report"
    clock = FakeClock(datetime(2026, 10, 20, 9, 0, 0, tzinfo=UTC))
    state = RunState.load_or_create(paths, run_id=run_id, target=1, clock=clock)
    state.start()

    queue = JobQueue.load(paths, clock=clock)
    queue.ingest([Candidate(id="1", title="Desenvolvedor React")])
    queue.mark("1", "eligible", "eligible", {"run_id": run_id})
    queue.complete("1", "verified", "verified", {"run_id": run_id, "cv": "output/cv.pdf"})

    session = _session(paths, clock, run_id, "1")
    clock.advance(12_000)
    state.attempts = 1
    state.verified = 1
    state.record_job(
        "1",
        state="verified",
        reason="verified",
        attempts=1,
        verified=True,
        submitted=True,
        waiting=False,
        cv="/workspace/output/cv.pdf",
        session_dir=str(session.root),
        duration_ms=12_000,
    )
    state.jobs["1"]["cv_cache"] = {
        "hit": True,
        "reason": "cache_hit",
        "cv_id": "cv-frontend-react-pt-senior-abc",
        "score": 0.97,
    }
    state.finish(status="verified", stop_reason="target_reached")
    state.save()
    return run_id, clock


def test_a_run_report_writes_markdown_html_and_summary_artifacts(paths, workspace):
    run_id, _ = _verified_report_fixture(paths, workspace)

    report = build_run_report(paths, run_id)

    run_dir = workspace / "output" / "sessions" / run_id
    assert report.artifacts.markdown == run_dir / "report.md"
    assert report.artifacts.html == run_dir / "report.html"
    assert report.artifacts.summary_text == run_dir / "summary.txt"
    assert report.artifacts.summary_json == run_dir / "summary.json"
    assert report.artifacts.markdown.is_file()
    assert report.artifacts.html.is_file()
    assert report.artifacts.summary_text.is_file()
    assert report.artifacts.summary_json.is_file()

    markdown = report.artifacts.markdown.read_text(encoding="utf-8")
    assert "# Relatório diário — daily-report" in markdown
    assert "Candidatos" in markdown
    assert "Verificadas" in markdown
    assert "screenshots/open.png" in markdown

    html = report.artifacts.html.read_text(encoding="utf-8")
    assert "<img" in html
    assert "1/screenshots/open.png" in html

    summary = json.loads(report.artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["run_id"] == run_id
    assert summary["status"] == "verified"
    assert summary["stop_reason"] == "target_reached"
    assert summary["target"] == 1
    assert summary["verified"] == 1
    assert summary["submitted"] == 1
    assert summary["funnel"]["candidates"] == 1
    assert summary["funnel"]["verified"] == 1
    assert summary["funnel"]["cvs_reused"] == 1
    assert summary["funnel"]["cvs_generated"] == 0
    assert summary["session_path"] == str(run_dir)
    assert summary["report"]["markdown"] == str(run_dir / "report.md")
    assert summary["jobs"][0]["id"] == "1"
    assert summary["jobs"][0]["duration_ms"] == 12_000
    assert summary["jobs"][0]["cv"] == "/workspace/output/cv.pdf"


def _mixed_funnel_fixture(paths, workspace: Path) -> str:
    run_id = "daily-funnel"
    clock = FakeClock(datetime(2026, 10, 20, 10, 0, 0, tzinfo=UTC))
    state = RunState.load_or_create(paths, run_id=run_id, target=2, clock=clock)
    state.start()

    queue = JobQueue.load(paths, clock=clock)
    queue.ingest(
        [
            Candidate(id="1", title="QA Automation Engineer"),
            Candidate(id="2", title="Desenvolvedor React", location="São Paulo, SP"),
            Candidate(id="3", title="Desenvolvedor React"),
            Candidate(id="4", title="Desenvolvedor React"),
            Candidate(id="5", title="Desenvolvedor React"),
            Candidate(id="6", title="Desenvolvedor React"),
            Candidate(id="7", title="Desenvolvedor React"),
        ]
    )
    queue.mark("1", "title_rejected", "title_qa", {"filter": "title"})
    queue.mark(
        "2", "ineligible", "location_outside_region", {"filter": "location"}
    )
    queue.mark("3", "ineligible", "family_not_targeted", {"decision": "family"})
    for job_id in ("4", "5", "6"):
        queue.mark(job_id, "eligible", "eligible", {"run_id": run_id})
    queue.begin("4")
    queue.complete(
        "4", "failed", "renderer_timeout", {"run_id": run_id, "message": "frozen"}
    )
    for job_id, hit in (("5", True), ("6", False)):
        queue.complete(job_id, "verified", "verified", {"run_id": run_id})

    state.attempts = 3
    state.verified = 2
    state.record_job(
        "4",
        state="failed",
        reason="renderer_timeout",
        attempts=1,
        verified=False,
        submitted=False,
        waiting=False,
        session_dir=None,
        duration_ms=30_000,
    )
    state.record_job(
        "5",
        state="verified",
        reason="verified",
        attempts=1,
        verified=True,
        submitted=True,
        waiting=False,
        cv="/workspace/output/cv-cache/reused.pdf",
        duration_ms=10_000,
    )
    state.jobs["5"]["cv_cache"] = {"hit": True, "cv_id": "cv-reused"}
    state.record_job(
        "6",
        state="verified",
        reason="verified",
        attempts=1,
        verified=True,
        submitted=True,
        waiting=False,
        cv="/workspace/output/cv-cache/generated.pdf",
        duration_ms=11_000,
    )
    state.jobs["6"]["cv_cache"] = {"hit": False, "cv_id": "cv-generated"}
    clock.advance(60_000)
    state.finish(status="verified", stop_reason="target_reached")
    state.save()
    return run_id


def test_the_funnel_counts_discards_cv_decisions_and_failures(paths, workspace):
    run_id = _mixed_funnel_fixture(paths, workspace)

    report = build_run_report(paths, run_id)
    summary = report.summary

    assert summary["funnel"]["candidates"] == 7
    assert summary["funnel"]["discarded"] == 3
    assert summary["funnel"]["discards_by_reason"] == {
        "family_not_targeted": 1,
        "location_outside_region": 1,
        "title_qa": 1,
    }
    assert summary["funnel"]["eligible"] == 3
    assert summary["funnel"]["cvs_reused"] == 1
    assert summary["funnel"]["cvs_generated"] == 1
    assert summary["funnel"]["applied"] == 2
    assert summary["funnel"]["verified"] == 2
    assert summary["funnel"]["failures"] == 1
    assert summary["funnel"]["waiting"] == 0
    assert summary["blockers"] == {
        "family_not_targeted": 1,
        "location_outside_region": 1,
        "title_qa": 1,
    }
    assert summary["failures"] == [{"id": "4", "reason": "renderer_timeout"}]
    assert "Falhas: 4=renderer_timeout" in report.text


def test_regenerating_an_old_report_ignores_later_queue_changes(paths):
    run_id = "daily-historical"
    clock = FakeClock(datetime(2026, 10, 20, 11, 0, 0, tzinfo=UTC))
    state = RunState.load_or_create(paths, run_id=run_id, target=1, clock=clock)
    state.start()

    queue = JobQueue.load(paths, clock=clock)
    queue.ingest(
        [
            Candidate(id="1", title="Desenvolvedor React"),
            Candidate(id="2", title="QA Automation Engineer"),
        ]
    )
    queue.mark("1", "eligible", "eligible", {"run_id": run_id})
    queue.complete("1", "verified", "verified", {"run_id": run_id})
    queue.mark("2", "title_rejected", "title_qa", {"filter": "title"})

    state.verified = 1
    state.record_job(
        "1",
        state="verified",
        reason="verified",
        attempts=1,
        verified=True,
        submitted=False,
        waiting=False,
    )
    state.finish(status="verified", stop_reason="target_reached")
    state.save()

    # A later run may move the discarded job back to the queue.  The historical
    # report must keep what happened during this run.
    clock.advance(60_000)
    queue.mark("2", "eligible", "requeued", {"run_id": run_id})

    report = build_run_report(paths, run_id)
    jobs = {job.job_id: job for job in report.jobs}

    assert jobs["2"].state == "title_rejected"
    assert jobs["2"].reason == "title_qa"
    assert report.summary["funnel"]["discards_by_reason"] == {"title_qa": 1}
    assert report.summary["funnel"]["applied"] == 1
    assert report.summary["funnel"]["verified"] == 1


def _run_state(
    paths,
    run_id: str,
    moment: datetime,
    *,
    status: str = "verified",
    stop_reason: str | None = "target_reached",
):
    clock = FakeClock(moment)
    state = RunState.load_or_create(paths, run_id=run_id, target=1, clock=clock)
    if status != "running":
        state.finish(status=status, stop_reason=stop_reason or "queue_exhausted")
    state.save()
    run_dir = paths.output / "sessions" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "session.json").write_text('{"status": "completed"}\n', encoding="utf-8")
    return state


def test_retention_keeps_the_three_latest_complete_runs(paths):
    start = datetime(2026, 10, 1, 8, 0, 0, tzinfo=UTC)
    for index in range(5):
        _run_state(paths, f"run-{index}", start + timedelta(hours=index))
    _run_state(
        paths,
        "run-incomplete",
        start + timedelta(hours=2, minutes=30),
        status="running",
    )

    removed = prune_runs(paths, keep=3)

    assert removed == ("run-1", "run-0")
    remaining = {path.stem for path in (paths.data / "runs").glob("*.json")}
    assert remaining == {"run-2", "run-3", "run-4", "run-incomplete"}
    for run_id in ("run-0", "run-1"):
        assert not (paths.output / "sessions" / run_id).exists()
    for run_id in ("run-2", "run-3", "run-4", "run-incomplete"):
        assert (paths.output / "sessions" / run_id).is_dir()
    assert latest_run_id(paths) == "run-4"


def test_retention_ignores_a_corrupt_run_id(paths):
    start = datetime(2026, 10, 1, 8, 0, 0, tzinfo=UTC)
    _run_state(paths, "safe", start)
    corrupt = paths.data / "runs" / "corrupt.json"
    corrupt.write_text(
        json.dumps(
            {
                "run_id": "../../config",
                "status": "verified",
                "stop_reason": "target_reached",
                "started_at": start.isoformat(),
                "updated_at": start.isoformat(),
            }
        ),
        encoding="utf-8",
    )

    removed = prune_runs(paths, keep=1)

    assert removed == ()
    assert (paths.data / "runs" / "corrupt.json").is_file()
    assert (paths.output / "sessions" / "safe").is_dir()


def test_retention_never_removes_a_protected_or_unfinished_run(paths):
    start = datetime(2026, 10, 1, 8, 0, 0, tzinfo=UTC)
    for index in range(4):
        _run_state(paths, f"run-{index}", start + timedelta(hours=index))
    _run_state(paths, "run-running", start, status="running")

    removed = prune_runs(paths, keep=1, protected={"run-0"})

    assert removed == ("run-2", "run-1")
    remaining = {path.stem for path in (paths.data / "runs").glob("*.json")}
    assert remaining == {"run-0", "run-3", "run-running"}

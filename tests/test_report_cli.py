from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from career_ops.run_state import RunState
from conftest import FRONTEND_JD, invoke, write_cv, write_jd_fixtures


def _daily(run, workspace: Path, *, run_id: str, video: bool = False):
    candidates = workspace / "data" / "candidates.json"
    candidates.write_text(
        json.dumps(
            [
                {
                    "id": "101",
                    "title": "Desenvolvedor React",
                    "location": "Recife, PE",
                    "workplace": "Remote",
                }
            ]
        ),
        encoding="utf-8",
    )
    jds = write_jd_fixtures(workspace, {"101": FRONTEND_JD})
    args = [
        "--candidates",
        str(candidates),
        "--jd-dir",
        str(jds),
        "--cv",
        str(write_cv(workspace)),
        "--adapter",
        "fake",
        "--target",
        "1",
        "--run-id",
        run_id,
    ]
    if video:
        args.append("--video")
    return invoke(run, *args)


def test_a_daily_run_generates_its_report_and_summary(run, workspace):
    result, payload = _daily(run, workspace, run_id="daily-report-e2e")

    assert result.returncode == 0
    assert payload["status"] == "verified"
    run_dir = workspace / "output" / "sessions" / "daily-report-e2e"
    assert Path(payload["report"]["markdown"]) == run_dir / "report.md"
    assert Path(payload["report"]["html"]) == run_dir / "report.html"
    assert Path(payload["report"]["summary_text"]) == run_dir / "summary.txt"
    assert Path(payload["report"]["summary_json"]) == run_dir / "summary.json"
    assert payload["report"]["video"] is None
    assert payload["summary"]["funnel"] == {
        "candidates": 1,
        "discarded": 0,
        "discards_by_reason": {},
        "eligible": 1,
        "cvs_generated": 0,
        "cvs_reused": 0,
        "applied": 1,
        "verified": 1,
        "failures": 0,
        "failure_reasons": [],
        "waiting": 0,
    }
    assert (run_dir / "report.md").is_file()
    assert (run_dir / "report.html").is_file()
    assert (run_dir / "summary.txt").is_file()
    assert (run_dir / "summary.json").is_file()
    assert not (run_dir / "video.mp4").exists()


def test_the_report_command_rebuilds_a_run_and_returns_json(run, workspace):
    _daily(run, workspace, run_id="daily-report-cli")

    result = run("career-ops-report", "--run-id", "daily-report-cli", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["command"] == "career-ops-report"
    assert payload["run_id"] == "daily-report-cli"
    assert payload["status"] == "verified"
    assert payload["summary"]["funnel"]["verified"] == 1
    assert payload["jobs"][0]["id"] == "101"
    assert payload["artifacts"]["markdown"].endswith("report.md")
    assert payload["retention"]["removed"] == []


def test_the_report_command_defaults_to_the_latest_run(run, workspace):
    _daily(run, workspace, run_id="daily-report-older")
    _daily(run, workspace, run_id="daily-report-newer")

    result = run("career-ops-report", "--no-prune")
    payload = json.loads(result.stdout) if result.stdout.startswith("{") else None

    assert result.returncode == 0
    # Human mode prints the short text summary.
    assert payload is None
    assert "Sessão daily-report-newer" in result.stdout


def test_the_report_command_reports_a_missing_run(run):
    result = run("career-ops-report", "--run-id", "does-not-exist", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["status"] == "failed"
    assert payload["failure"]["reason"] == "run_not_found"


def test_the_report_help_is_human_readable(run):
    result = run("career-ops-report", "--help")

    assert result.returncode == 0
    assert "Generate the Markdown/HTML report" in result.stdout
    assert "--run-id" in result.stdout
    assert "Exit codes:" in result.stdout
    assert "career-ops-report --run-id daily-2026-10-20 --json" in result.stdout


def test_a_daily_run_applies_the_retention_window(run, workspace, env, paths):
    moment = datetime(2000, 1, 1, tzinfo=timezone.utc)
    for run_id in ("very-old", "also-old"):
        state = RunState.load_or_create(
            paths, run_id=run_id, target=1, clock=lambda: moment
        )
        state.finish(status="verified", stop_reason="target_reached")
        state.save()
        (paths.output / "sessions" / run_id).mkdir(parents=True)
    env["CAREER_OPS_RETENTION_RUNS"] = "1"

    result, payload = _daily(run, workspace, run_id="daily-retention")

    assert result.returncode == 0
    assert payload["retention"]["keep"] == 1
    assert set(payload["retention"]["removed"]) == {"very-old", "also-old"}
    assert (workspace / "output" / "sessions" / "daily-retention").is_dir()
    assert not (workspace / "output" / "sessions" / "very-old").exists()
    assert not (workspace / "data" / "runs" / "also-old.json").exists()


def test_no_prune_ignores_an_invalid_retention_setting(run, workspace, env):
    _daily(run, workspace, run_id="daily-no-prune")
    env["CAREER_OPS_RETENTION_RUNS"] = "not-a-number"

    result = run(
        "career-ops-report",
        "--run-id",
        "daily-no-prune",
        "--no-prune",
        "--json",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["status"] == "verified"
    assert payload["retention"]["removed"] == []


def test_the_report_command_retains_exactly_the_requested_window(run, paths):
    start = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
    for index in range(4):
        moment = start + timedelta(hours=index)
        state = RunState.load_or_create(
            paths, run_id=f"run-{index}", target=1, clock=lambda moment=moment: moment
        )
        state.finish(status="verified", stop_reason="target_reached")
        state.save()
        (paths.output / "sessions" / f"run-{index}").mkdir(parents=True)

    result = run("career-ops-report", "--run-id", "run-0", "--keep", "3", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["retention"]["removed"] == ["run-0"]
    remaining = {path.stem for path in (paths.data / "runs").glob("*.json")}
    assert remaining == {"run-1", "run-2", "run-3"}


def test_a_daily_run_can_record_an_optional_video(run, workspace):
    result, payload = _daily(run, workspace, run_id="daily-report-video", video=True)

    assert result.returncode == 0
    video = workspace / "output" / "sessions" / "daily-report-video" / "video.mp4"
    assert video.is_file()
    assert payload["report"]["video"] == str(video)
    assert payload["summary"]["video"] == str(video)

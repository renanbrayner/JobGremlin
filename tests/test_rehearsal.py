from __future__ import annotations

import json

from career_ops.rehearsal import (
    BASELINE_2026_10_19,
    RehearsalStep,
    render_rehearsal_report,
)


def _job(
    job_id: str,
    state: str,
    *,
    reason: str | None = None,
    screenshots: int = 4,
) -> dict:
    return {
        "id": job_id,
        "state": state,
        "reason": reason,
        "screenshots": [
            {"stage": "open", "path": f"{job_id}/screenshots/open.png"}
        ]
        * screenshots,
    }


def _summary(
    *,
    candidates: int,
    discarded: int,
    eligible: int,
    generated: int,
    reused: int,
    applied: int,
    verified: int,
    jobs: list[dict],
) -> dict:
    return {
        "funnel": {
            "candidates": candidates,
            "discarded": discarded,
            "eligible": eligible,
            "cvs_generated": generated,
            "cvs_reused": reused,
            "applied": applied,
            "verified": verified,
            "failures": 0,
            "waiting": 0,
        },
        "report": {
            "markdown": "/repo/output/sessions/step/report.md",
            "html": "/repo/output/sessions/step/report.html",
            "summary_text": "/repo/output/sessions/step/summary.txt",
            "summary_json": "/repo/output/sessions/step/summary.json",
        },
        "session_path": "/repo/output/sessions/step",
        "target": 1,
        "status": "verified",
        "stop_reason": "target_reached",
        "jobs": jobs,
    }


def test_the_comparison_uses_the_19_10_baseline_and_the_funnel_decisions():
    step = RehearsalStep(
        label="3 vagas",
        run_id="rehearsal-three",
        summary=_summary(
            candidates=6,
            discarded=3,
            eligible=3,
            generated=1,
            reused=2,
            applied=3,
            verified=3,
            jobs=[
                _job("1", "verified"),
                _job("2", "title_rejected", reason="title_qa"),
                _job("3", "ineligible", reason="location_hybrid"),
                _job("4", "ineligible", reason="family_not_targeted"),
                _job("5", "verified"),
                _job("6", "verified"),
            ],
        ),
    )

    markdown, payload = render_rehearsal_report(
        date="2026-10-20",
        steps=[step],
        isolation=None,
    )

    assert payload["baseline"] == dict(BASELINE_2026_10_19)
    metrics = payload["steps"][0]["metrics"]
    assert metrics == {
        "unique_jobs": 6,
        "shortlist": 4,
        "jds_read": 4,
        "eligible": 3,
        "submitted": 3,
        "verified": 3,
        "failures": 0,
        "waiting": 0,
        "cvs_generated": 1,
        "cvs_reused": 2,
        "screenshots": 24,
    }
    rows = {row["metric"]: row for row in payload["comparison"]["rows"]}
    assert rows["unique_jobs"]["baseline"] == 344
    assert rows["shortlist"]["baseline"] == 129
    assert rows["jds_read"]["baseline"] == 12
    assert rows["eligible"]["baseline"] == 4
    assert rows["verified"]["baseline"] == 0
    assert rows["unique_jobs"]["values"] == [6]
    assert rows["verified"]["values"] == [3]

    assert "# Ensaio paralelo — 2026-10-20" in markdown
    assert "19/10" in markdown
    assert "| Vagas únicas na rodada | 344 | 6 |" in markdown
    assert "| Verificadas | 0 | 3 |" in markdown
    assert "target_reached" in markdown
    assert "CV(s) gerado(s)" in markdown


def test_the_baseline_records_the_renderer_freeze_and_zero_sends():
    assert BASELINE_2026_10_19["cards"] == 1950
    assert BASELINE_2026_10_19["unique_jobs"] == 344
    assert BASELINE_2026_10_19["shortlist"] == 129
    assert BASELINE_2026_10_19["jds_read"] == 12
    assert BASELINE_2026_10_19["eligible"] == 4
    assert BASELINE_2026_10_19["submitted"] == 0
    assert BASELINE_2026_10_19["verified"] == 0
    assert "CV" in BASELINE_2026_10_19["note"]


def test_an_unchanged_isolation_result_is_shown_in_the_report():
    step = RehearsalStep(
        label="1 vaga",
        run_id="rehearsal-one",
        summary=_summary(
            candidates=1,
            discarded=0,
            eligible=1,
            generated=1,
            reused=0,
            applied=1,
            verified=1,
            jobs=[_job("1", "verified")],
        ),
    )
    isolation = {
        "unchanged": True,
        "targets": [
            {
                "name": "hermes",
                "paths": ["~/.hermes"],
                "changed": False,
                "differences": [],
            },
            {
                "name": "local_bin",
                "paths": ["~/.local/bin"],
                "changed": False,
                "differences": [],
            },
        ],
    }

    markdown, payload = render_rehearsal_report(
        date="2026-10-20",
        steps=[step],
        isolation=isolation,
    )

    assert payload["isolation"] == isolation
    assert "~/.hermes" in markdown
    assert "~/.local/bin" in markdown
    assert "inalterado" in markdown.lower()


def test_the_rehearsal_script_runs_one_three_and_twenty_jobs_and_proves_isolation(
    run, env, sensitive_home, tmp_path
):
    env["HOME"] = str(sensitive_home)

    workspace = tmp_path / "rehearsal-workspace"
    docs = workspace / "docs"
    result = run(
        "rehearsal",
        "--date",
        "2026-10-20",
        "--workspace-root",
        str(workspace),
        "--docs-dir",
        str(docs),
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["status"] == "ok"
    assert [step["verified"] for step in payload["steps"]] == [1, 3, 20]
    assert payload["steps"][-1]["stop_reason"] == "target_reached"
    assert payload["isolation"]["unchanged"] is True
    assert {
        target["name"] for target in payload["isolation"]["targets"]
    } >= {"hermes", "allowlist", "local_bin", "career_ops_upstream"}

    report = (docs / "2026-10-20.md").read_text(encoding="utf-8")
    assert "19/10" in report
    assert "| Verificadas | 0 | 1 | 3 | 20 |" in report
    assert "inalterado" in report.lower()
    assert "family_not_targeted" in report
    assert "location_hybrid" in report
    assert "reutilizado" in report

    one = workspace / "output" / "sessions" / "rehearsal-one-2026-10-20"
    assert (one / "report.md").is_file()
    assert (one / "report.html").is_file()
    assert (one / "summary.txt").is_file()
    assert (one / "summary.json").is_file()
    session = one / "101"
    assert (session / "session.json").is_file()
    assert (session / "events.jsonl").is_file()
    assert len(list((session / "screenshots").glob("*.png"))) == 4

    three = json.loads(
        (
            workspace
            / "output"
            / "sessions"
            / "rehearsal-three-2026-10-20"
            / "summary.json"
        ).read_text(encoding="utf-8")
    )
    assert three["funnel"]["candidates"] == 6
    assert three["funnel"]["discarded"] == 3
    assert three["funnel"]["eligible"] == 3
    assert three["funnel"]["cvs_generated"] == 1
    assert three["funnel"]["cvs_reused"] == 2
    assert three["funnel"]["verified"] == 3

    twenty = workspace / "output" / "sessions" / "rehearsal-twenty-2026-10-20"
    sessions = sorted(path.name for path in twenty.iterdir() if path.is_dir())
    assert len(sessions) == 20
    for job_id in sessions:
        assert (twenty / job_id / "session.json").is_file()
        assert (twenty / job_id / "events.jsonl").is_file()
        assert len(list((twenty / job_id / "screenshots").glob("*.png"))) == 4

    summary = json.loads(
        (twenty / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["verified"] == 20
    assert summary["stop_reason"] == "target_reached"
    assert summary["funnel"]["applied"] == 20

from __future__ import annotations

import json
from pathlib import Path

FRONTEND_JD = """\
Desenvolvedor Front-end Sênior

Requisitos:
- React e TypeScript.
"""


def _cv(workspace: Path) -> Path:
    path = workspace / "output" / "cv-renan-react-2026-10-19.pdf"
    path.write_bytes(b"%PDF-fake")
    return path


def _candidates(workspace: Path, items: list[dict]) -> Path:
    path = workspace / "data" / "candidates.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


def _jd_dir(workspace: Path, entries: dict[str, str]) -> Path:
    root = workspace / "data" / "jd-fixtures"
    root.mkdir(parents=True, exist_ok=True)
    for job_id, text in entries.items():
        (root / f"{job_id}.txt").write_text(text, encoding="utf-8")
    return root


def _invoke(run, *args: str) -> tuple:
    result = run("career-ops-run", *args)
    payload = json.loads(result.stdout) if result.stdout.strip() else None
    return result, payload


def _queue(workspace: Path) -> dict:
    return json.loads((workspace / "data" / "queue.json").read_text(encoding="utf-8"))


def _records(workspace: Path) -> dict[str, dict]:
    return {record["id"]: record for record in _queue(workspace)["records"]}


def test_a_candidate_list_shortlists_fetches_lazily_and_applies_the_first_eligible(
    run, workspace
):
    cv = _cv(workspace)
    candidates = _candidates(
        workspace,
        [
            {
                "id": "1",
                "title": "QA Automation Engineer",
                "location": "Recife, PE",
                "workplace": "Remote",
            },
            {
                "id": "2",
                "title": "Desenvolvedor React",
                "location": "São Paulo, SP",
                "workplace": "On-site",
            },
            {
                "id": "3",
                "title": "Desenvolvedor React",
                "location": "Recife, PE",
                "workplace": "Remote",
            },
            {
                "id": "4",
                "title": "Desenvolvedor React",
                "location": "Recife, PE",
                "workplace": "Remote",
            },
        ],
    )
    jds = _jd_dir(workspace, {"3": FRONTEND_JD, "4": FRONTEND_JD})

    result, payload = _invoke(
        run,
        "--candidates",
        str(candidates),
        "--jd-dir",
        str(jds),
        "--cv",
        str(cv),
        "--adapter",
        "fake",
        "--run-id",
        "queue-success",
    )

    assert result.returncode == 0
    assert payload["status"] == "verified"
    assert payload["job"]["id"] == "3"
    assert payload["job"]["profile"]["family"] == "frontend"
    assert payload["queue"]["selection"]["id"] == "3"
    assert payload["queue"]["selection"]["decision"]["reason"] == "eligible"
    assert payload["queue"]["record"]["state"] == "verified"
    assert payload["queue"]["record"]["decision"]["reason"] == "eligible"

    records = _records(workspace)
    assert records["1"]["state"] == "title_rejected"
    assert records["1"]["reason"] == "title_qa"
    assert records["2"]["state"] == "ineligible"
    assert records["2"]["reason"] == "location_outside_region"
    assert records["3"]["state"] == "verified"
    assert records["4"]["state"] == "new"
    assert records["4"]["jd_path"] is None


def test_a_second_run_does_not_reapply_a_verified_job(run, workspace):
    cv = _cv(workspace)
    candidates = _candidates(
        workspace,
        [
            {
                "id": "3",
                "title": "Desenvolvedor React",
                "location": "Recife, PE",
                "workplace": "Remote",
            }
        ],
    )
    jds = _jd_dir(workspace, {"3": FRONTEND_JD})

    first, first_payload = _invoke(
        run,
        "--candidates",
        str(candidates),
        "--jd-dir",
        str(jds),
        "--cv",
        str(cv),
        "--adapter",
        "fake",
        "--run-id",
        "queue-first",
    )
    second, second_payload = _invoke(
        run,
        "--candidates",
        str(candidates),
        "--jd-dir",
        str(jds),
        "--cv",
        str(cv),
        "--adapter",
        "fake",
        "--run-id",
        "queue-second",
    )

    assert first.returncode == 0
    assert first_payload["status"] == "verified"
    assert second.returncode == 1
    assert second_payload["status"] == "failed"
    assert second_payload["failure"]["reason"] == "no_eligible_job"
    assert second_payload["queue"]["ingested"][0]["reason"] == "blocked:verified"
    assert len(list((workspace / "output" / "sessions").iterdir())) == 1


def test_a_missing_jd_is_recorded_and_the_flow_continues(run, workspace):
    cv = _cv(workspace)
    candidates = _candidates(
        workspace,
        [
            {
                "id": "1",
                "title": "Desenvolvedor React",
                "location": "Recife, PE",
                "workplace": "Remote",
            },
            {
                "id": "2",
                "title": "Desenvolvedor React",
                "location": "Recife, PE",
                "workplace": "Remote",
            },
        ],
    )
    jds = _jd_dir(workspace, {"2": FRONTEND_JD})

    result, payload = _invoke(
        run,
        "--candidates",
        str(candidates),
        "--jd-dir",
        str(jds),
        "--cv",
        str(cv),
        "--adapter",
        "fake",
        "--run-id",
        "queue-missing-jd",
    )

    assert result.returncode == 0
    assert payload["job"]["id"] == "2"
    records = _records(workspace)
    assert records["1"]["state"] == "failed"
    assert records["1"]["reason"] == "jd_missing"
    assert records["2"]["state"] == "verified"


def test_a_missing_candidate_file_is_a_precondition_error(run, workspace):
    cv = _cv(workspace)

    result, payload = _invoke(
        run,
        "--candidates",
        str(workspace / "data" / "missing.json"),
        "--cv",
        str(cv),
        "--adapter",
        "fake",
    )

    assert result.returncode == 3
    assert payload["failure"]["reason"] == "candidates_missing"
    assert not (workspace / "output" / "sessions").exists()


def test_an_invalid_candidate_file_is_a_usage_error(run, workspace):
    cv = _cv(workspace)
    path = workspace / "data" / "candidates.json"
    path.write_text('{"not": "a list"}', encoding="utf-8")

    result, payload = _invoke(
        run,
        "--candidates",
        str(path),
        "--cv",
        str(cv),
        "--adapter",
        "fake",
    )

    assert result.returncode == 2
    assert payload["failure"]["reason"] == "invalid_candidates"
    assert not (workspace / "output" / "sessions").exists()


def test_job_and_candidates_are_mutually_exclusive(run):
    result = run("career-ops-run", "--job", "1", "--candidates", "c.json")

    assert result.returncode == 2
    assert "exactly one of --job or --candidates" in result.stderr


def test_jd_dir_requires_candidates(run):
    result = run("career-ops-run", "--job", "1", "--jd-dir", "jds")

    assert result.returncode == 2
    assert "--jd-dir requires --candidates" in result.stderr


def test_help_documents_the_queue_mode(run):
    result = run("career-ops-run", "--help")

    assert result.returncode == 0
    assert "--candidates" in result.stdout
    assert "--jd-dir" in result.stdout
    assert '"queue"' in result.stdout

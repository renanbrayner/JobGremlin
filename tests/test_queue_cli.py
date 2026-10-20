from __future__ import annotations

import json
from pathlib import Path

from conftest import DEVOPS_JD, FRONTEND_JD, invoke, write_cv, write_jd_fixtures


def _candidates(workspace: Path, items: list[dict]) -> Path:
    path = workspace / "data" / "candidates.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


def _queue(workspace: Path) -> dict:
    return json.loads((workspace / "data" / "queue.json").read_text(encoding="utf-8"))


def _records(workspace: Path) -> dict[str, dict]:
    return {record["id"]: record for record in _queue(workspace)["records"]}


def _payload_record(payload: dict, job_id: str) -> dict:
    return next(
        record for record in payload["queue"]["records"] if record["id"] == job_id
    )


def test_a_candidate_list_shortlists_fetches_lazily_and_applies_the_first_eligible(
    run, workspace
):
    cv = write_cv(workspace)
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
    jds = write_jd_fixtures(workspace, {"3": FRONTEND_JD, "4": FRONTEND_JD})

    result, payload = invoke(
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
    cv = write_cv(workspace)
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
    jds = write_jd_fixtures(workspace, {"3": FRONTEND_JD})

    first, first_payload = invoke(
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
    second, second_payload = invoke(
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
    cv = write_cv(workspace)
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
    jds = write_jd_fixtures(workspace, {"2": FRONTEND_JD})

    result, payload = invoke(
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


def test_an_ineligible_job_is_reported_with_its_auditable_reason(run, workspace):
    cv = write_cv(workspace)
    candidates = _candidates(
        workspace,
        [
            {
                "id": "1",
                "title": "Software Engineer",
                "location": "Recife, PE",
                "workplace": "Remote",
            }
        ],
    )
    jds = write_jd_fixtures(workspace, {"1": DEVOPS_JD})

    result, payload = invoke(
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
        "queue-ineligible",
    )

    assert result.returncode == 1
    assert payload["failure"]["reason"] == "no_eligible_job"
    record = _records(workspace)["1"]
    assert record["state"] == "ineligible"
    assert record["reason"] == "family_not_targeted"
    assert record["profile"]["family"] == "devops"
    assert record["decision"]["eligible"] is False
    assert record["decision"]["reason"] == "family_not_targeted"


def test_language_rule_is_auditable_through_the_cli(run, workspace):
    cv = write_cv(workspace)
    (workspace / "config" / "eligibility.json").write_text(
        json.dumps({"languages": ["pt"]}), encoding="utf-8"
    )
    english_jd = """\
Frontend Developer

Requirements:
- React and TypeScript.
"""
    candidates = _candidates(
        workspace,
        [
            {
                "id": "1",
                "title": "React Developer",
                "location": "Recife, PE",
                "workplace": "Remote",
            }
        ],
    )
    jds = write_jd_fixtures(workspace, {"1": english_jd})

    result, payload = invoke(
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
        "queue-language",
    )

    assert result.returncode == 1
    assert payload["failure"]["reason"] == "no_eligible_job"
    record = _records(workspace)["1"]
    assert record["state"] == "ineligible"
    assert record["decision"]["reason"] == "language_unsupported"
    assert record["profile"]["language"] == "en"


def test_seniority_rule_is_auditable_through_the_cli(run, workspace):
    cv = write_cv(workspace)
    junior_jd = """\
Desenvolvedor React

Vaga para desenvolvedor júnior.

Requisitos:
- React.
"""
    candidates = _candidates(
        workspace,
        [
            {
                "id": "1",
                "title": "Desenvolvedor React",
                "location": "Recife, PE",
                "workplace": "Remote",
            }
        ],
    )
    jds = write_jd_fixtures(workspace, {"1": junior_jd})

    result, payload = invoke(
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
        "queue-seniority",
    )

    assert result.returncode == 1
    assert payload["failure"]["reason"] == "no_eligible_job"
    record = _records(workspace)["1"]
    assert record["state"] == "ineligible"
    assert record["decision"]["reason"] == "seniority_not_targeted"
    assert record["profile"]["seniority"] == "junior"


def test_a_blocked_failed_job_returns_only_with_an_explicit_requeue_reason(run, workspace):
    cv = write_cv(workspace)
    candidates = _candidates(
        workspace,
        [
            {
                "id": "1",
                "title": "Desenvolvedor React",
                "location": "Recife, PE",
                "workplace": "Remote",
            }
        ],
    )
    empty_jds = write_jd_fixtures(workspace, {}, "empty-jd-fixtures")
    jds = write_jd_fixtures(workspace, {"1": FRONTEND_JD}, "jd-fixtures")

    first, first_payload = invoke(
        run,
        "--candidates",
        str(candidates),
        "--jd-dir",
        str(empty_jds),
        "--cv",
        str(cv),
        "--adapter",
        "fake",
        "--run-id",
        "queue-no-jd",
    )
    blocked, blocked_payload = invoke(
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
        "queue-blocked",
    )
    requeued, requeued_payload = invoke(
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
        "queue-requeued",
        "--requeue-reason",
        "JD now available",
    )

    assert first.returncode == 1
    assert first_payload["failure"]["reason"] == "no_eligible_job"
    first_record = _payload_record(first_payload, "1")
    assert first_record["state"] == "failed"
    assert first_record["reason"] == "jd_missing"

    assert blocked.returncode == 1
    assert blocked_payload["failure"]["reason"] == "no_eligible_job"
    assert blocked_payload["queue"]["ingested"][0]["reason"] == "blocked:failed"
    assert _payload_record(blocked_payload, "1")["state"] == "failed"

    assert requeued.returncode == 0
    assert requeued_payload["status"] == "verified"
    assert requeued_payload["queue"]["ingested"][0]["status"] == "requeued"

    history = _queue(workspace)["history"]
    requeue_events = [entry for entry in history if entry["action"] == "requeued"]
    assert requeue_events[-1]["reason"] == "JD now available"
    assert _records(workspace)["1"]["state"] == "verified"


def test_a_missing_candidate_file_is_a_precondition_error(run, workspace):
    cv = write_cv(workspace)

    result, payload = invoke(
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
    cv = write_cv(workspace)
    path = workspace / "data" / "candidates.json"
    path.write_text('{"not": "a list"}', encoding="utf-8")

    result, payload = invoke(
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

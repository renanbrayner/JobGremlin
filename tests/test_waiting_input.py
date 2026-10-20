from __future__ import annotations

import json
from pathlib import Path

from career_ops import cli
from career_ops.fake_adapter import FakeApplicationAdapter
from conftest import (
    FRONTEND_JD,
    invoke,
    read_queue,
    read_run_state,
    write_candidates,
    write_cv,
    write_jd_fixtures,
)


def _jds(workspace: Path, count: int = 2, *, start: int = 1) -> Path:
    return write_jd_fixtures(
        workspace,
        {str(index): FRONTEND_JD for index in range(start, start + count)},
    )


def _parked_path(workspace: Path) -> Path:
    return workspace / "data" / "parked-form.json"


def _run_waiting(
    run,
    workspace,
    *,
    run_id: str = "daily-waiting",
    count: int = 2,
    start: int = 1,
):
    return invoke(
        run,
        "--candidates",
        str(write_candidates(workspace, count, start=start)),
        "--jd-dir",
        str(_jds(workspace, count=count, start=start)),
        "--cv",
        str(write_cv(workspace)),
        "--adapter",
        "fake",
        "--fake-scenario",
        "waiting_input",
        "--target",
        str(count),
        "--run-id",
        run_id,
    )


def _reply(run, workspace, parked: dict, *args: str):
    result = run(
        "career-ops-reply",
        "--run-id",
        parked["run_id"],
        "--job",
        parked["job"]["id"],
        "--token",
        parked["token"],
        *args,
    )
    payload = json.loads(result.stdout) if result.stdout.strip() else None
    return result, payload


def test_exit_6_parks_one_form_and_the_loop_moves_to_the_next_job(run, workspace):
    result, payload = _run_waiting(run, workspace)

    assert result.returncode == 6
    assert payload["status"] == "failed"
    assert payload["stop_reason"] == "queue_exhausted"
    assert payload["waiting"] == 1

    parked = payload["waiting_input"]
    assert parked["job"]["id"] == "1"
    assert parked["job"]["company"] == "Fake Company"
    assert parked["token"]
    assert parked["target"] == "fake-target-1"
    assert parked["questions"] == [
        {
            "text": "Are you authorized to work?",
            "kind": "radio",
            "options": ["Yes", "No"],
        }
    ]

    on_disk = json.loads(_parked_path(workspace).read_text(encoding="utf-8"))
    assert on_disk["token"] == parked["token"]
    assert on_disk["questions"][0]["options"] == ["Yes", "No"]

    records = read_queue(workspace)
    assert records["1"]["state"] == "waiting_input"
    assert records["2"]["state"] == "failed"
    assert records["2"]["reason"] == "parked_form_limit"
    assert records["2"]["attempts"] == 1
    assert read_run_state(workspace, "daily-waiting")["jobs"]["1"]["waiting"] is True


def test_the_loop_applies_a_normal_job_while_a_form_is_parked(
    workspace, env, capsys, monkeypatch
):
    def build_adapter(
        adapter_name,
        scenario,
        paths,
        environment,
        *,
        job_id,
        cv,
        answers,
        apply_timeout,
        parked_target=None,
    ):
        outcome = "waiting_input" if job_id == "1" else "success"
        return FakeApplicationAdapter(job_id=job_id, cv=cv, scenario=outcome)

    monkeypatch.setattr(cli, "_build_adapter", build_adapter)

    exit_code = cli.main(
        [
            "--candidates",
            str(write_candidates(workspace, 2)),
            "--jd-dir",
            str(_jds(workspace, 2)),
            "--cv",
            str(write_cv(workspace)),
            "--adapter",
            "fake",
            "--target",
            "2",
            "--run-id",
            "daily-next-job",
        ],
        environ=env,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 6
    assert payload["waiting"] == 1
    assert payload["verified"] == 1
    assert payload["waiting_input"]["job"]["id"] == "1"
    records = read_queue(workspace)
    assert records["1"]["state"] == "waiting_input"
    assert records["2"]["state"] == "verified"
    sessions = workspace / "output" / "sessions" / "daily-next-job"
    assert sorted(path.name for path in sessions.iterdir() if path.is_dir()) == [
        "1",
        "2",
    ]


def test_a_second_waiting_form_does_not_replace_the_parked_one(run, workspace):
    first, first_payload = _run_waiting(run, workspace, run_id="daily-parked-first")
    token = first_payload["waiting_input"]["token"]

    second, second_payload = _run_waiting(
        run, workspace, run_id="daily-parked-second", start=3
    )

    assert first.returncode == 6
    assert second.returncode == 1
    assert second_payload["waiting_input"]["token"] == token
    assert second_payload["waiting_input"]["run_id"] == "daily-parked-first"
    assert second_payload["waiting"] == 0
    records = read_queue(workspace)
    assert records["3"]["reason"] == "parked_form_limit"
    assert records["4"]["reason"] == "parked_form_limit"


def test_reply_writes_the_workspace_answers_file_and_resumes_the_form(run, workspace):
    _, payload = _run_waiting(run, workspace)
    parked = payload["waiting_input"]

    result, reply = _reply(
        run,
        workspace,
        parked,
        "--answer",
        "Are you authorized to work?=Yes",
        "--adapter",
        "fake",
        "--fake-scenario",
        "success",
    )

    assert result.returncode == 0
    assert reply["command"] == "career-ops-reply"
    assert reply["status"] == "verified"
    assert reply["result"]["verified"] is True
    assert reply["job"]["id"] == "1"
    assert reply["waiting_input"] is None
    assert reply["answers"]["written"] == ["Are you authorized to work?"]

    answers = json.loads(
        (workspace / "config" / "answers-hermes.json").read_text(encoding="utf-8")
    )
    assert answers == {"Are you authorized to work?": "Yes"}
    assert not _parked_path(workspace).exists()

    record = read_queue(workspace)["1"]
    assert record["state"] == "verified"
    assert record["reason"] == "verified"
    state = read_run_state(workspace, "daily-waiting")
    assert state["verified"] == 1
    assert state["jobs"]["1"]["verified"] is True


def test_an_invalid_option_is_rejected_before_writing_or_resuming(run, workspace):
    _, payload = _run_waiting(run, workspace)
    parked = payload["waiting_input"]

    result, reply = _reply(
        run,
        workspace,
        parked,
        "--answer",
        "Are you authorized to work?=Maybe",
        "--adapter",
        "fake",
    )

    assert result.returncode == 2
    assert reply["status"] == "failed"
    assert reply["failure"]["reason"] == "invalid_answer"
    assert "Yes" in reply["failure"]["message"]
    assert "No" in reply["failure"]["message"]
    assert not (workspace / "config" / "answers-hermes.json").exists()
    assert _parked_path(workspace).is_file()
    assert read_queue(workspace)["1"]["state"] == "waiting_input"


def test_an_answer_for_another_question_is_rejected(run, workspace):
    _, payload = _run_waiting(run, workspace)
    parked = payload["waiting_input"]

    result, reply = _reply(
        run,
        workspace,
        parked,
        "--answer",
        "What is your salary expectation?=10000",
        "--adapter",
        "fake",
    )

    assert result.returncode == 2
    assert reply["failure"]["reason"] == "invalid_answer"
    assert not (workspace / "config" / "answers-hermes.json").exists()
    assert _parked_path(workspace).is_file()


def test_a_resumed_form_that_finds_another_question_stays_parked(run, workspace):
    _, payload = _run_waiting(run, workspace)
    parked = payload["waiting_input"]

    result, reply = _reply(
        run,
        workspace,
        parked,
        "--answer",
        "Are you authorized to work?=Yes",
        "--adapter",
        "fake",
        "--fake-scenario",
        "waiting_input",
    )

    assert result.returncode == 6
    assert reply["status"] == "failed"
    assert reply["failure"]["reason"] == "waiting_input"
    assert reply["waiting_input"]["token"] == parked["token"]
    assert reply["waiting_input"]["questions"][0]["options"] == ["Yes", "No"]
    assert _parked_path(workspace).is_file()
    assert read_queue(workspace)["1"]["state"] == "waiting_input"


def test_a_lost_tab_is_a_recoverable_failure_and_is_never_counted_as_sent(run, workspace):
    _, payload = _run_waiting(run, workspace)
    parked = payload["waiting_input"]

    result, reply = _reply(
        run,
        workspace,
        parked,
        "--answer",
        "Are you authorized to work?=Yes",
        "--adapter",
        "fake",
        "--fake-scenario",
        "lost_tab",
    )

    assert result.returncode == 1
    assert reply["status"] == "failed"
    assert reply["result"]["submitted"] is False
    assert reply["result"]["verified"] is False
    assert reply["failure"]["reason"] == "parked_form_lost"
    assert reply["failure"]["retryable"] is True
    assert not _parked_path(workspace).exists()

    record = read_queue(workspace)["1"]
    assert record["state"] == "failed"
    assert record["reason"] == "parked_form_lost"
    assert read_run_state(workspace, "daily-waiting")["verified"] == 0


def test_reply_requires_the_parked_form_and_its_token(run, workspace):
    _, payload = _run_waiting(run, workspace)
    parked = payload["waiting_input"]

    wrong_result = run(
        "career-ops-reply",
        "--run-id",
        parked["run_id"],
        "--job",
        parked["job"]["id"],
        "--token",
        "not-the-token",
        "--answer",
        "Are you authorized to work?=Yes",
        "--adapter",
        "fake",
    )
    wrong_token = wrong_result
    wrong_payload = json.loads(wrong_result.stdout)
    assert wrong_token.returncode == 3
    assert wrong_payload["failure"]["reason"] == "parked_form_mismatch"
    assert _parked_path(workspace).is_file()

    _parked_path(workspace).unlink()
    missing, missing_payload = _reply(
        run,
        workspace,
        parked,
        "--answer",
        "Are you authorized to work?=Yes",
        "--adapter",
        "fake",
    )
    assert missing.returncode == 3
    assert missing_payload["failure"]["reason"] == "no_parked_form"


def test_an_explicit_job_never_reopens_its_own_parked_form(run, workspace):
    _, payload = _run_waiting(run, workspace)
    parked = payload["waiting_input"]

    result, again = invoke(
        run,
        "--job",
        parked["job"]["id"],
        "--cv",
        str(write_cv(workspace)),
        "--adapter",
        "fake",
        "--run-id",
        "explicit-parked",
    )

    assert result.returncode == 6
    assert again["failure"]["reason"] == "waiting_input"
    assert again["waiting_input"]["token"] == parked["token"]
    assert not (workspace / "output" / "sessions" / "explicit-parked").exists()


def test_a_corrupt_parked_record_is_reported_as_json(run, workspace):
    _parked_path(workspace).write_text("{not json", encoding="utf-8")

    result, payload = invoke(
        run,
        "--candidates",
        str(write_candidates(workspace, 1)),
        "--jd-dir",
        str(_jds(workspace, count=1)),
        "--cv",
        str(write_cv(workspace)),
        "--adapter",
        "fake",
        "--target",
        "1",
        "--run-id",
        "corrupt-parked",
    )

    assert result.returncode == 3
    assert payload["failure"]["reason"] == "parked_form_unreadable"


def test_reply_help_is_human_readable(run):
    result = run("career-ops-reply", "--help")

    assert result.returncode == 0
    assert "Resume the LinkedIn form that is parked" in result.stdout
    assert "--answer" in result.stdout
    assert "--token" in result.stdout
    assert "Exit codes:" in result.stdout
    assert "career-ops-run" in result.stdout

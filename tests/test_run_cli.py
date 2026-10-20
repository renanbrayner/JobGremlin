from __future__ import annotations

import json
from pathlib import Path

import pytest

from career_ops.paths import WorkspacePaths
from career_ops.real_adapter import RealApplicationAdapter
from conftest import ScriptedRunner, completed_process, invoke, write_cv


def _events(session_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (session_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_a_verified_run_writes_a_complete_session_and_returns_success(run, workspace):
    cv = write_cv(workspace)

    result, payload = invoke(
        run,
        "--job",
        "4411222",
        "--cv",
        str(cv),
        "--adapter",
        "fake",
        "--fake-scenario",
        "success",
        "--run-id",
        "acceptance-success",
    )

    assert result.returncode == 0
    assert payload["command"] == "career-ops-run"
    assert payload["status"] == "verified"
    assert payload["run_id"] == "acceptance-success"
    assert payload["job"]["id"] == "4411222"
    assert payload["job"]["title"] == "Fake React Engineer"
    assert payload["result"] == {
        "submitted": True,
        "verified": True,
        "clicked": True,
        "reason": "verified",
        "attempts": 1,
        "expected_cv": cv.name,
        "selected_cvs": [cv.name],
        "retryable": False,
    }
    assert payload["failure"] is None
    assert payload["cv"] == str(cv.resolve())

    session_dir = Path(payload["artifacts"]["session_dir"])
    assert session_dir == workspace / "output" / "sessions" / "acceptance-success"
    assert Path(payload["artifacts"]["session_json"]).is_file()
    assert Path(payload["artifacts"]["events"]).is_file()
    assert {Path(path).name for path in payload["artifacts"]["screenshots"]} == {
        "open.png",
        "cv-selection.png",
        "review.png",
        "submit.png",
    }
    assert all(Path(path).is_file() for path in payload["artifacts"]["screenshots"])

    metadata = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "completed"
    assert metadata["job"] == {"id": "4411222"}
    events = _events(session_dir)
    assert [event["stage"] for event in events] == [
        "open",
        "cv_selection",
        "review",
        "submit",
    ]
    assert all(event["run_id"] == "acceptance-success" for event in events)
    assert all(event["status"] == "ok" for event in events)


def test_an_unconfirmed_submission_is_a_failed_run(run, workspace):
    cv = write_cv(workspace)

    result, payload = invoke(
        run,
        "--job",
        "4411222",
        "--cv",
        str(cv),
        "--adapter",
        "fake",
        "--fake-scenario",
        "failure",
        "--run-id",
        "acceptance-failure",
    )

    assert result.returncode == 1
    assert payload["status"] == "failed"
    assert payload["result"]["submitted"] is False
    assert payload["result"]["verified"] is False
    assert payload["result"]["reason"] == "not_confirmed"
    assert payload["failure"]["reason"] == "not_confirmed"
    assert "did not confirm" in payload["failure"]["message"]

    session_dir = Path(payload["artifacts"]["session_dir"])
    assert json.loads((session_dir / "session.json").read_text())["status"] == "failed"
    assert [event["stage"] for event in _events(session_dir)][-1] == "error"


def test_a_wrong_cv_aborts_before_submit_and_is_never_counted(run, workspace):
    cv = write_cv(workspace)

    result, payload = invoke(
        run,
        "--job",
        "4411222",
        "--cv",
        str(cv),
        "--adapter",
        "fake",
        "--fake-scenario",
        "wrong_cv",
        "--run-id",
        "acceptance-wrong-cv",
    )

    assert result.returncode == 1
    assert payload["status"] == "failed"
    assert payload["result"]["reason"] == "wrong_cv"
    assert payload["result"]["selected_cvs"] == ["cv-previous-application.pdf"]
    assert payload["failure"]["retryable"] is False

    session_dir = Path(payload["artifacts"]["session_dir"])
    events = _events(session_dir)
    stages = [event["stage"] for event in events]
    assert "submit" not in stages
    assert stages == ["open", "review", "error"]
    assert events[1]["status"] == "failed"
    assert events[1]["detail"]["reason"] == "wrong_cv"


def test_a_renderer_timeout_exhausts_attempts_with_evidence(run, workspace):
    cv = write_cv(workspace)

    result, payload = invoke(
        run,
        "--job",
        "4411222",
        "--cv",
        str(cv),
        "--adapter",
        "fake",
        "--fake-scenario",
        "timeout",
        "--run-id",
        "acceptance-timeout",
    )

    assert result.returncode == 1
    assert payload["status"] == "failed"
    assert payload["result"]["reason"] == "renderer_timeout"
    assert payload["result"]["attempts"] == 2
    assert payload["result"]["retryable"] is True
    assert payload["failure"]["reason"] == "renderer_timeout"

    session_dir = Path(payload["artifacts"]["session_dir"])
    events = _events(session_dir)
    assert [event["stage"] for event in events] == ["open", "error", "error"]
    error_artifacts = [event["artifact"] for event in events if event["stage"] == "error"]
    assert error_artifacts == ["screenshots/error.png", "screenshots/error-2.png"]
    assert all((session_dir / artifact).is_file() for artifact in error_artifacts)
    assert "submit" not in {event["stage"] for event in events}


def test_a_missing_cv_fails_before_a_session_is_created(run, workspace):
    result, payload = invoke(run, "--job", "4411222", "--adapter", "fake")

    assert result.returncode == 3
    assert payload["status"] == "failed"
    assert payload["result"]["reason"] == "cv_missing"
    assert payload["failure"]["reason"] == "cv_missing"
    assert payload["artifacts"]["session_dir"] is None
    assert not (workspace / "output" / "sessions").exists()


def test_the_newest_workspace_cv_is_the_default(run, workspace):
    older = write_cv(workspace, "cv-renan-older.pdf")
    newer = write_cv(workspace, "cv-renan-newer.pdf")
    older.touch()
    newer.touch()

    result, payload = invoke(
        run,
        "--job",
        "4411222",
        "--adapter",
        "fake",
        "--run-id",
        "acceptance-default-cv",
    )

    assert result.returncode == 0
    assert payload["cv"] == str(newer.resolve())
    assert payload["result"]["expected_cv"] == newer.name


def test_fake_scenario_requires_the_fake_adapter(run):
    result = run(
        "career-ops-run",
        "--job",
        "1",
        "--adapter",
        "real",
        "--fake-scenario",
        "timeout",
    )

    assert result.returncode == 2
    assert "--fake-scenario requires --adapter fake" in result.stderr


def test_help_is_human_readable(run):
    result = run("career-ops-run", "--help")

    assert result.returncode == 0
    assert "Apply to one explicit LinkedIn job" in result.stdout
    assert "--job" in result.stdout
    assert "Exit codes:" in result.stdout
    assert "0  LinkedIn confirmed the application" in result.stdout
    assert "Output (stdout is always one JSON object)" in result.stdout
    assert "--cv output/cv-renan-react.pdf" in result.stdout


def _adapter(
    paths: WorkspacePaths,
    runner: ScriptedRunner,
    **kwargs,
) -> RealApplicationAdapter:
    cv = paths.output / "cv-renan-react.pdf"
    cv.write_bytes(b"%PDF")
    answers = paths.config / "answers-hermes.json"
    answers.write_text("{}", encoding="utf-8")
    return RealApplicationAdapter(
        paths,
        job_id="4411222",
        cv=cv,
        answers=answers,
        runner=runner,
        sleep=lambda _: None,
        environ={},
        **kwargs,
    )


def test_the_real_adapter_opens_a_job_through_jobinfo(paths):
    runner = ScriptedRunner(
        completed_process(
            ["jobinfo"],
            stdout=(
                "some noise\n"
                '{"company":"Acme","title":"React Engineer","applied":false,'
                '"easy":true,"closed":false,"url":"https://www.linkedin.com/jobs/view/4411222/"}\n'
            ),
        )
    )
    adapter = _adapter(paths, runner)

    info = adapter.open()

    assert info.id == "4411222"
    assert info.title == "React Engineer"
    assert info.company == "Acme"
    assert info.blocker is None
    assert Path(runner.calls[0][0]).name == "jobinfo"
    assert runner.calls[0][1] == "4411222"


def test_the_real_adapter_opens_the_next_job_in_a_new_tab_when_one_is_parked(paths):
    runner = ScriptedRunner(
        completed_process(["cdp-targets"], stdout="new: target-2\n"),
        completed_process(
            ["jobinfo"],
            stdout=json.dumps({"title": "React Engineer", "applied": False}) + "\n",
        ),
    )
    adapter = _adapter(paths, runner, parked_target="target-1")

    info = adapter.open()

    assert info.id == "4411222"
    assert [Path(call[0]).name for call in runner.calls] == ["cdp-targets", "jobinfo"]
    assert runner.calls[0][1] == "--new"
    assert runner.calls[1][1] == "4411222"
    assert runner.calls[1][2] == "target-2"


def test_the_real_adapter_fills_a_new_job_in_its_own_tab(paths):
    runner = ScriptedRunner(
        completed_process(["cdp-targets"], stdout="new: target-2\n"),
        completed_process(
            ["jobinfo"],
            stdout=json.dumps({"title": "React Engineer", "applied": False}) + "\n",
        ),
        completed_process(["cdp"], stdout="page\n"),
        completed_process(["cdp"], stdout="arquivo setado: /tmp/cv.pdf\n"),
        completed_process(["easyapply"], stdout="dry-run: nao enviei\n"),
        completed_process(["cdp"], stdout='{"status":"selected"}\n'),
    )
    adapter = _adapter(paths, runner, parked_target="target-1")

    adapter.open()
    adapter.attach(adapter.cv)

    easyapply = runner.calls[4]
    assert Path(easyapply[0]).name == "easyapply"
    assert easyapply[easyapply.index("--target-id") + 1] == "target-2"


def test_the_real_adapter_resumes_the_parked_tab_without_reopening_the_form(paths):
    runner = ScriptedRunner(
        completed_process(
            ["cdp-targets"],
            stdout="page\ttarget-1\tJob\thttps://www.linkedin.com/jobs/view/4411222/\n",
        ),
        completed_process(["easyapply"], stdout="continuando\n"),
        completed_process(["cdp"], stdout='{"status":"already_selected"}\n'),
    )
    adapter = _adapter(paths, runner, resume_target="target-1")

    adapter.attach(adapter.cv)

    assert [Path(call[0]).name for call in runner.calls] == [
        "cdp-targets",
        "easyapply",
        "cdp",
    ]
    easyapply = runner.calls[1]
    assert "--resume" in easyapply
    assert easyapply[easyapply.index("--target-id") + 1] == "target-1"


def test_the_real_adapter_reports_a_missing_parked_tab(paths):
    from career_ops.adapter import ParkedFormLost

    runner = ScriptedRunner(
        completed_process(["cdp-targets"], stdout="page\tother-tab\tJob\thttps://x/\n"),
    )
    adapter = _adapter(paths, runner, resume_target="target-1")

    with pytest.raises(ParkedFormLost):
        adapter.attach(adapter.cv)


def test_the_real_adapter_never_reopens_a_form_that_disappeared(paths):
    from career_ops.adapter import ParkedFormLost

    runner = ScriptedRunner(
        completed_process(
            ["cdp-targets"],
            stdout="page\ttarget-1\tJob\thttps://www.linkedin.com/jobs/view/4411222/\n",
        ),
        completed_process(
            ["easyapply"],
            stdout=">> --resume mas form nao encontrado. Abrindo do zero...\n",
        ),
    )
    adapter = _adapter(paths, runner, resume_target="target-1")

    with pytest.raises(ParkedFormLost):
        adapter.attach(adapter.cv)


@pytest.mark.parametrize(
    ("payload", "blocker"),
    [
        ({"applied": True}, "already_applied"),
        ({"closed": True}, "job_closed"),
        ({"easy": False}, "no_easy_apply"),
    ],
)
def test_the_real_adapter_reports_jobs_that_must_not_be_attempted(
    paths, payload, blocker
):
    runner = ScriptedRunner(completed_process(["jobinfo"], stdout=json.dumps(payload) + "\n"))
    adapter = _adapter(paths, runner)

    assert adapter.open().blocker == blocker


def test_the_real_adapter_preloads_the_cv_then_fills_the_form_without_submitting(paths):
    runner = ScriptedRunner(
        completed_process(["cdp"], stdout="page\n"),
        completed_process(["cdp"], stdout="arquivo setado: /tmp/cv.pdf\n"),
        completed_process(["easyapply"], stdout="dry-run: nao enviei\n"),
        completed_process(["cdp"], stdout='{"status":"selected"}\n'),
    )
    adapter = _adapter(paths, runner)

    adapter.attach(adapter.cv)

    names = [Path(call[0]).name for call in runner.calls]
    assert names == ["cdp", "cdp", "easyapply", "cdp"]
    assert runner.calls[0][1] == "goto"
    assert runner.calls[1][1] == "upload"
    easyapply = runner.calls[2]
    assert "--submit" not in easyapply
    assert "--cv-library-only" in easyapply
    assert str(adapter.cv) in easyapply
    assert runner.calls[3][1] == "eval"
    assert json.dumps(adapter.cv.name.lower()) in runner.calls[3][2]
    assert "__NAME__" not in runner.calls[3][2]


def test_the_real_adapter_reports_exit_6_as_waiting_for_input(paths):
    from career_ops.adapter import WaitingForInput

    runner = ScriptedRunner(
        completed_process(["cdp"], stdout="page\n"),
        completed_process(["cdp"], stdout="arquivo setado: /tmp/cv.pdf\n"),
        completed_process(
            ["easyapply"],
            returncode=6,
            stdout=(
                "   ? [radio: Yes | No]  Are you authorized to work?\n"
                "⚠ FORMULARIO EM ESPERA — respostas necessarias acima.\n"
            ),
        ),
        completed_process(
            ["cdp-targets"],
            stdout="page\ttarget-1\tJob\t"
            "https://www.linkedin.com/jobs/view/4411222/\n",
        ),
    )
    adapter = _adapter(paths, runner)

    with pytest.raises(WaitingForInput) as caught:
        adapter.attach(adapter.cv)

    assert caught.value.questions == (
        "? [radio: Yes | No]  Are you authorized to work?",
    )
    assert caught.value.target == "target-1"
    assert caught.value.pending[0].options == ("Yes", "No")


def test_the_real_adapter_maps_a_subprocess_timeout_to_renderer_timeout(paths):
    import subprocess

    from career_ops.renderer import RendererTimeout

    runner = ScriptedRunner(
        completed_process(["cdp"], stdout="page\n"),
        completed_process(["cdp"], stdout="arquivo setado: /tmp/cv.pdf\n"),
        subprocess.TimeoutExpired(["easyapply"], 30),
    )
    adapter = _adapter(paths, runner)

    with pytest.raises(RendererTimeout) as caught:
        adapter.attach(adapter.cv)

    assert caught.value.label == "fill application form"
    assert caught.value.retryable is True


def test_the_real_adapter_reads_only_the_selected_cv_from_the_page(paths):
    runner = ScriptedRunner(completed_process(["cdp"], stdout='["cv-renan-react.pdf"]\n'))
    adapter = _adapter(paths, runner)

    assert adapter.selected_cvs() == ("cv-renan-react.pdf",)
    assert Path(runner.calls[0][0]).name == "cdp"
    assert runner.calls[0][1] == "eval"
    assert "input[type=radio]" in runner.calls[0][2]


def test_the_real_adapter_submits_through_easyapply_and_verifies_with_jobinfo(paths):
    runner = ScriptedRunner(
        completed_process(["easyapply"], stdout="STATUS FINAL: ENVIADA\n"),
        completed_process(["jobinfo"], stdout=json.dumps({"applied": False}) + "\n"),
        completed_process(["jobinfo"], stdout=json.dumps({"applied": True}) + "\n"),
    )
    adapter = _adapter(paths, runner)

    adapter.submit()
    assert adapter.verify() is True

    easyapply = runner.calls[0]
    assert Path(easyapply[0]).name == "easyapply"
    assert "--resume" in easyapply
    assert "--submit" in easyapply
    assert [Path(call[0]).name for call in runner.calls[1:]] == ["jobinfo", "jobinfo"]


def test_a_waiting_form_returns_exit_6_and_keeps_the_question(run, workspace):
    cv = write_cv(workspace)

    result, payload = invoke(
        run,
        "--job",
        "4411222",
        "--cv",
        str(cv),
        "--adapter",
        "fake",
        "--fake-scenario",
        "waiting_input",
        "--run-id",
        "acceptance-waiting",
    )

    assert result.returncode == 6
    assert payload["status"] == "failed"
    assert payload["result"]["reason"] == "waiting_input"
    assert payload["result"]["retryable"] is True
    assert payload["failure"]["reason"] == "waiting_input"
    assert payload["failure"]["questions"] == [
        "? [radio: Yes | No]  Are you authorized to work?"
    ]

    session_dir = Path(payload["artifacts"]["session_dir"])
    assert json.loads((session_dir / "session.json").read_text())["status"] == "failed"
    assert [event["stage"] for event in _events(session_dir)] == ["open", "error"]


def test_the_real_adapter_without_answers_fails_before_a_session(run, workspace, fake_upstream):
    (fake_upstream / "config" / "answers-hermes.json").unlink()
    cv = write_cv(workspace)

    result, payload = invoke(run, "--job", "4411222", "--cv", str(cv))

    assert result.returncode == 3
    assert payload["result"]["reason"] == "answers_missing"
    assert payload["artifacts"]["session_dir"] is None
    assert not (workspace / "output" / "sessions").exists()


def test_the_real_adapter_reports_a_linkedin_daily_limit(paths):
    from career_ops.adapter import LinkedInDailyLimit

    runner = ScriptedRunner(
        completed_process(["cdp"], stdout="page\n"),
        completed_process(["cdp"], stdout="arquivo setado: /tmp/cv.pdf\n"),
        completed_process(
            ["easyapply"],
            stdout="You've reached the daily limit for applications. Try again tomorrow.\n",
        ),
    )
    adapter = _adapter(paths, runner)

    with pytest.raises(LinkedInDailyLimit) as caught:
        adapter.attach(adapter.cv)

    assert caught.value.reason == "daily_limit"


def test_a_cv_path_in_the_environment_is_expanded(run, workspace, env):
    cv = write_cv(workspace)
    env["CAREER_OPS_CV"] = "$CAREER_OPS_OUTPUT/" + cv.name

    result, payload = invoke(
        run,
        "--job",
        "4411222",
        "--adapter",
        "fake",
        "--run-id",
        "acceptance-env-cv",
    )

    assert result.returncode == 0
    assert payload["cv"] == str(cv.resolve())

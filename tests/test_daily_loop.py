from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from career_ops.cli import main
from career_ops.loop import DailyLoop, LoopConfig, LoopOutcome
from career_ops.queue import Candidate, JobQueue, Selection
from career_ops.run_state import RunState
from conftest import FRONTEND_JD, invoke, write_cv, write_jd_fixtures


def _candidates(workspace: Path, count: int = 25) -> Path:
    path = workspace / "data" / "candidates.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": str(index),
                    "title": "Desenvolvedor React",
                    "location": "Recife, PE",
                    "workplace": "Remote",
                }
                for index in range(1, count + 1)
            ]
        ),
        encoding="utf-8",
    )
    return path


def _jds(workspace: Path, count: int = 25) -> Path:
    return write_jd_fixtures(
        workspace,
        {str(index): FRONTEND_JD for index in range(1, count + 1)},
    )


def _queue(workspace: Path) -> dict:
    return json.loads((workspace / "data" / "queue.json").read_text(encoding="utf-8"))


def _records(workspace: Path) -> dict[str, dict]:
    return {record["id"]: record for record in _queue(workspace)["records"]}


def _sessions(workspace: Path, run_id: str) -> list[str]:
    root = workspace / "output" / "sessions" / run_id
    return sorted(
        (path.name for path in root.iterdir() if path.is_dir()),
        key=lambda name: (int(name.split("-")[0]), name),
    )


def _run_state(workspace: Path, run_id: str) -> dict:
    return json.loads(
        (workspace / "data" / "runs" / f"{run_id}.json").read_text(encoding="utf-8")
    )


def _invoke_daily(
    run,
    workspace,
    *,
    run_id: str,
    target: int,
    scenario: str = "success",
    count: int = 25,
):
    return invoke(
        run,
        "--candidates",
        str(_candidates(workspace, count=count)),
        "--jd-dir",
        str(_jds(workspace, count=count)),
        "--cv",
        str(write_cv(workspace)),
        "--adapter",
        "fake",
        "--fake-scenario",
        scenario,
        "--target",
        str(target),
        "--run-id",
        run_id,
    )


def test_twenty_five_candidates_produce_exactly_twenty_verified_and_no_21st_attempt(
    run, workspace
):
    result, payload = _invoke_daily(run, workspace, run_id="daily-twenty", target=20)

    assert result.returncode == 0
    assert payload["status"] == "verified"
    assert payload["stop_reason"] == "target_reached"
    assert payload["target"] == 20
    assert payload["submitted"] == 20
    assert payload["verified"] == 20
    assert payload["attempts"] == 20
    assert len(payload["applications"]) == 20

    records = _records(workspace)
    assert {job_id for job_id, record in records.items() if record["state"] == "verified"} == {
        str(index) for index in range(1, 21)
    }
    for index in range(21, 26):
        assert records[str(index)]["state"] == "new"
        assert records[str(index)]["jd_path"] is None

    assert _sessions(workspace, "daily-twenty") == [str(index) for index in range(1, 21)]
    state = _run_state(workspace, "daily-twenty")
    assert state["status"] == "verified"
    assert state["stop_reason"] == "target_reached"
    assert state["verified"] == 20


def test_an_interrupted_run_resumes_without_reapplying_verified_jobs(run, workspace):
    first, first_payload = _invoke_daily(
        run, workspace, run_id="daily-resume", target=10
    )
    assert first.returncode == 0
    assert first_payload["verified"] == 10
    assert _sessions(workspace, "daily-resume") == [str(index) for index in range(1, 11)]
    first_events = (
        workspace / "output" / "sessions" / "daily-resume" / "1" / "events.jsonl"
    ).read_text(encoding="utf-8")

    second, second_payload = _invoke_daily(
        run, workspace, run_id="daily-resume", target=20
    )

    assert second.returncode == 0
    assert second_payload["status"] == "verified"
    assert second_payload["submitted"] == 20
    assert second_payload["verified"] == 20
    assert len(second_payload["applications"]) == 10
    assert _sessions(workspace, "daily-resume") == [
        str(index) for index in range(1, 21)
    ]
    assert (
        workspace / "output" / "sessions" / "daily-resume" / "1" / "events.jsonl"
    ).read_text(encoding="utf-8") == first_events
    assert _run_state(workspace, "daily-resume")["verified"] == 20


def test_the_linkedin_daily_limit_interrupts_the_loop_and_is_reported(run, workspace):
    result, payload = _invoke_daily(
        run, workspace, run_id="daily-limit", target=20, scenario="daily_limit"
    )

    assert result.returncode == 1
    assert payload["status"] == "failed"
    assert payload["stop_reason"] == "daily_limit_reached"
    assert payload["submitted"] == 0
    assert payload["attempts"] == 1
    assert payload["failure"]["reason"] == "daily_limit"
    assert len(payload["applications"]) == 1
    assert _sessions(workspace, "daily-limit") == ["1"]

    records = _records(workspace)
    assert records["1"]["state"] == "failed"
    assert records["1"]["reason"] == "daily_limit"
    for index in range(2, 26):
        assert records[str(index)]["state"] == "new"
        assert records[str(index)]["attempts"] == 0

    state = _run_state(workspace, "daily-limit")
    assert state["status"] == "failed"
    assert state["stop_reason"] == "daily_limit_reached"


def test_a_second_process_cannot_start_while_the_run_lock_is_held(run, workspace):
    lock_path = workspace / "data" / "run.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        blocked, blocked_payload = _invoke_daily(
            run, workspace, run_id="daily-locked", target=1
        )

    assert blocked.returncode == 3
    assert blocked_payload["failure"]["reason"] == "run_locked"
    assert not (workspace / "output" / "sessions" / "daily-locked").exists()

    allowed, allowed_payload = _invoke_daily(
        run, workspace, run_id="daily-locked", target=1
    )
    assert allowed.returncode == 0
    assert allowed_payload["status"] == "verified"


def test_a_job_is_attempted_at_most_twice_per_run(run, workspace):
    result, payload = _invoke_daily(
        run,
        workspace,
        run_id="daily-attempts",
        target=1,
        scenario="timeout",
        count=1,
    )

    assert result.returncode == 1
    assert payload["stop_reason"] == "queue_exhausted"
    assert payload["attempts"] == 2
    assert len(payload["applications"]) == 2
    assert _sessions(workspace, "daily-attempts") == ["1", "1-2"]
    record = _records(workspace)["1"]
    assert record["state"] == "failed"
    assert record["attempts"] == 2


def test_a_click_without_confirmation_is_submitted_but_never_verified(run, workspace):
    result, payload = _invoke_daily(
        run,
        workspace,
        run_id="daily-unconfirmed",
        target=1,
        scenario="failure",
        count=1,
    )

    assert result.returncode == 1
    assert payload["submitted"] == 1
    assert payload["verified"] == 0
    assert payload["result"]["clicked"] is True
    assert payload["result"]["submitted"] is False
    assert payload["stop_reason"] == "queue_exhausted"
    assert _sessions(workspace, "daily-unconfirmed") == ["1"]
    record = _records(workspace)["1"]
    assert record["state"] == "failed"
    assert record["reason"] == "not_confirmed"
    assert _run_state(workspace, "daily-unconfirmed")["verified"] == 0


def test_a_closed_job_is_ineligible_and_does_not_create_a_second_attempt(run, workspace):
    result, payload = _invoke_daily(
        run,
        workspace,
        run_id="daily-closed",
        target=1,
        scenario="job_closed",
        count=1,
    )

    assert result.returncode == 1
    assert payload["failure"]["reason"] == "job_closed"
    assert payload["attempts"] == 1
    assert _sessions(workspace, "daily-closed") == ["1"]
    record = _records(workspace)["1"]
    assert record["state"] == "ineligible"
    assert record["reason"] == "job_closed"
    assert record["attempts"] == 1


def test_an_interrupted_attempt_is_abandoned_and_verified_jobs_are_not_reapplied(
    run, workspace, paths
):
    run_id = "daily-crash"
    queue = JobQueue.load(paths)
    queue.ingest(
        [
            Candidate(
                id="1",
                title="Desenvolvedor React",
                location="Recife, PE",
                workplace="Remote",
            ),
            Candidate(
                id="2",
                title="Desenvolvedor React",
                location="Recife, PE",
                workplace="Remote",
            ),
            Candidate(
                id="3",
                title="Desenvolvedor React",
                location="Recife, PE",
                workplace="Remote",
            ),
        ]
    )
    queue.complete("1", "verified", "verified", {"run_id": run_id})
    queue.mark("2", "eligible", None, {})
    queue.begin("2")
    queue.save()

    state = RunState.load_or_create(paths, run_id=run_id, target=2)
    state.verified = 1
    state.record_job(
        "1",
        state="verified",
        reason="verified",
        attempts=1,
        verified=True,
        submitted=True,
        waiting=False,
    )
    state.save()

    result, payload = _invoke_daily(
        run, workspace, run_id=run_id, target=2, count=3
    )

    assert result.returncode == 0
    assert payload["verified"] == 2
    assert payload["submitted"] == 2
    assert _sessions(workspace, run_id) == ["3"]
    records = _records(workspace)
    assert records["1"]["state"] == "verified"
    assert records["2"]["state"] == "failed"
    assert records["2"]["reason"] == "run_interrupted"
    assert records["2"]["attempts"] == 1
    assert records["3"]["state"] == "verified"
    assert _run_state(workspace, run_id)["jobs"]["2"]["reason"] == "run_interrupted"


class _StepMonotonic:
    def __init__(self, values: Sequence[float]) -> None:
        self._values = list(values)
        self._last = self._values[-1] if self._values else 0.0

    def __call__(self) -> float:
        if self._values:
            self._last = self._values.pop(0)
        return self._last


def test_the_time_budget_stops_before_opening_the_next_job(
    workspace, env, capsys
):
    fixed = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    candidates = _candidates(workspace, count=5)
    jds = _jds(workspace, count=5)
    cv = write_cv(workspace)

    exit_code = main(
        [
            "--candidates",
            str(candidates),
            "--jd-dir",
            str(jds),
            "--cv",
            str(cv),
            "--adapter",
            "fake",
            "--target",
            "5",
            "--max-seconds",
            "10",
            "--run-id",
            "daily-budget",
        ],
        environ=env,
        clock=lambda: fixed,
        monotonic=_StepMonotonic([0, 0, 0, 0, 20]),
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["stop_reason"] == "time_budget_exhausted"
    assert payload["submitted"] == 1
    assert len(payload["applications"]) == 1
    assert _sessions(workspace, "daily-budget") == ["1"]
    assert _records(workspace)["2"]["state"] == "new"


def test_an_unexpected_loop_crash_still_writes_a_report(
    workspace, env, capsys, monkeypatch
):
    candidates = _candidates(workspace, count=1)
    jds = _jds(workspace, count=1)
    cv = write_cv(workspace)

    def crash(self, *args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(DailyLoop, "run", crash)

    exit_code = main(
        [
            "--candidates",
            str(candidates),
            "--jd-dir",
            str(jds),
            "--cv",
            str(cv),
            "--adapter",
            "fake",
            "--target",
            "1",
            "--run-id",
            "daily-crash",
        ],
        environ=env,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "failed"
    assert payload["stop_reason"] == "unexpected_error"
    assert payload["failure"]["reason"] == "unexpected_error"
    assert payload["report_error"] is None
    assert Path(payload["report"]["markdown"]).is_file()
    assert payload["summary"]["status"] == "failed"
    assert _run_state(workspace, "daily-crash")["stop_reason"] == "unexpected_error"


class _CountingSource:
    def __init__(self, candidates: Sequence[Candidate]) -> None:
        self.candidates = list(candidates)
        self.calls = 0

    def discover(self) -> Sequence[Candidate]:
        self.calls += 1
        return list(self.candidates)


class _ScriptedSource:
    """A discovery source that answers with one batch per call, then nothing."""

    def __init__(self, batches: Sequence[Sequence[Candidate]]) -> None:
        self._batches = [list(batch) for batch in batches]
        self.calls = 0

    def discover(self) -> Sequence[Candidate]:
        index = self.calls
        self.calls += 1
        return list(self._batches[index]) if index < len(self._batches) else []


class _RejectingProcessor:
    """Hand out seeded jobs one at a time; the injected apply rejects them."""

    def __init__(self, job_ids: Sequence[str]) -> None:
        self._job_ids = list(job_ids)

    def next_eligible(self) -> Selection | None:
        if not self._job_ids:
            return None
        job_id = self._job_ids.pop(0)
        return Selection(
            job_id=job_id,
            candidate=Candidate(id=job_id),
            jd_path=None,
            profile=None,
            decision=None,
        )


class _NullProcessor:
    def next_eligible(self) -> Selection | None:
        return None


def _loop(paths, *, run_id: str, source: _CountingSource, backlog: int) -> LoopOutcome:
    queue = JobQueue.load(paths)
    if backlog:
        queue.ingest([Candidate(id=f"seed-{index}") for index in range(backlog)])
    state = RunState.load_or_create(paths, run_id=run_id, target=1)
    loop = DailyLoop(
        queue=queue,
        processor=_NullProcessor(),  # type: ignore[arg-type]
        source=source,
        config=LoopConfig(target=1, low_watermark=5),
        state=state,
        apply=_unexpected_apply,
        resolve_cv=_unexpected_cv,
    )
    return loop.run()


def _unexpected_apply(selection: Selection, cv: Path) -> Mapping[str, object]:
    raise AssertionError("the loop must not apply when no candidate is selected")


def _unexpected_cv(selection: Selection) -> tuple[Path, None]:
    raise AssertionError("the loop must not resolve a CV when no candidate is selected")


def test_discovery_is_only_called_when_the_backlog_is_low(paths):
    source = _CountingSource([])
    outcome = _loop(paths, run_id="discovery-high", source=source, backlog=6)

    assert outcome.stop_reason == "queue_exhausted"
    assert source.calls == 0


def test_an_empty_backlog_triggers_one_discovery_attempt(paths):
    source = _CountingSource([])
    outcome = _loop(paths, run_id="discovery-empty", source=source, backlog=0)

    assert outcome.stop_reason == "queue_exhausted"
    assert source.calls == 1


def _closed_application(selection: Selection, cv: Path) -> Mapping[str, object]:
    return {
        "status": "failed",
        "run_id": "discovery-reopen",
        "job": selection.as_job(),
        "result": {
            "submitted": False,
            "verified": False,
            "clicked": False,
            "reason": "job_closed",
            "attempts": 1,
            "retryable": False,
        },
        "failure": {"reason": "job_closed", "message": "closed", "retryable": False},
        "artifacts": {"session_dir": None},
        "cv": str(cv),
    }


def _unused_cv(selection: Selection) -> tuple[Path, None]:
    return Path("unused-cv.md"), None


def test_discovery_reopens_after_the_backlog_shrinks(paths):
    source = _ScriptedSource([[], [Candidate(id="late")]])
    queue = JobQueue.load(paths)
    queue.ingest([Candidate(id="seed")])
    queue.mark("seed", "eligible", None, {})
    state = RunState.load_or_create(paths, run_id="discovery-reopen", target=1)
    loop = DailyLoop(
        queue=queue,
        processor=_RejectingProcessor(["seed"]),  # type: ignore[arg-type]
        source=source,
        config=LoopConfig(target=1, low_watermark=1),
        state=state,
        apply=_closed_application,
        resolve_cv=_unused_cv,
    )

    outcome = loop.run()

    assert outcome.stop_reason == "queue_exhausted"
    # The first discovery returned nothing, but the source is consulted again
    # once the backlog shrinks instead of staying exhausted for the whole run.
    assert source.calls == 2
    assert any(result.job_id == "late" for result in outcome.ingested)
    assert queue.get("seed").state == "ineligible"
    assert queue.get("late").state == "new"

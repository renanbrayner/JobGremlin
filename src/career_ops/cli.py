"""``career-ops-run`` — apply to one explicit LinkedIn job and report JSON.

The command is deliberately narrow: one job per invocation, one observable
session, no queue and no CV generation (those arrive in later tickets).  It
picks an expected PDF, drives an ``ApplicationAdapter`` and returns success only
when LinkedIn confirms the application.  ``--adapter fake`` runs the whole
orchestration without a browser and is what the acceptance tests use.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping, Sequence

from career_ops.adapter import AdapterError, ApplicationAdapter, WaitingForInput
from career_ops.eligibility import EligibilityRules
from career_ops.fake_adapter import FAKE_SCENARIOS, FakeApplicationAdapter, FakeScenario
from career_ops.job_description import (
    DirectoryJobDescriptionFetcher,
    HttpJobDescriptionFetcher,
    JobDescriptionFetcher,
)
from career_ops.paths import WorkspacePaths, expand_path, load_environment, resolve_paths
from career_ops.queue import (
    EnqueueResult,
    JobQueue,
    QueueProcessor,
    load_candidates,
)
from career_ops.real_adapter import (
    DEFAULT_APPLY_TIMEOUT_SECONDS,
    DEFAULT_JOBINFO_TIMEOUT_SECONDS,
    RealApplicationAdapter,
)
from career_ops.renderer import RendererWatchdog, resolve_renderer_timeout
from career_ops.session import SessionRecorder
from career_ops.submission import SubmissionGuard, SubmissionResult

COMMAND = "career-ops-run"
EXIT_VERIFIED = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_PRECONDITION = 3
EXIT_WAITING_INPUT = 6

_BLOCKER_MESSAGES = {
    "already_applied": "LinkedIn already shows an application for this job",
    "job_closed": "the job is no longer accepting applications",
    "no_easy_apply": "the job does not offer Easy Apply",
}

_HELP_EPILOG = """\
Two modes:
  --job <id>          apply to one explicit job (the original one-job slice)
  --candidates <file> ingest a JSON/TSV candidate list, shortlist it, fetch the
                      JD lazily, apply the first eligible job and persist the
                      queue in data/queue.json
  --requeue-reason    with --candidates, explicitly allow blocked ids to return
                      to `new` (recorded in the queue history)

Output (stdout is always one JSON object):
  {
    "command": "career-ops-run",
    "status": "verified" | "failed",
    "run_id": "2026-10-19T12-00-00Z",
    "job": {"id": "...", "title": "...", "company": "...", ...},
    "result": {"submitted": true, "verified": true, "reason": "verified", ...},
    "failure": null | {"reason": "...", "message": "...", "retryable": false},
    "artifacts": {"session_dir": "...", "session_json": "...", "events": "...",
                  "screenshots": ["..."]},
    "cv": "/abs/path/cv-....pdf",
    "queue": {                         # only in --candidates mode
      "path": "/abs/path/data/queue.json",
      "selection": {"id": "...", "profile": {...}, "decision": {...}},
      "ingested": [{"id": "...", "status": "enqueued", "reason": null}],
      "record": {"id": "...", "state": "verified", ...},
      "records": [{"id": "...", "state": "verified", ...}]
    }
  }

Exit codes:
  0  LinkedIn confirmed the application (status "verified")
  1  the application was not verified (status "failed"), including when the
     candidate list has no eligible job
  2  invalid command-line arguments or an invalid candidate file
  3  missing CV/answers/candidates/JD source or invalid configuration
  6  the form is waiting for an answer (form left open)

Examples:
  career-ops-run --job 4411222 --cv output/cv-renan-react.pdf
  career-ops-run --job 4411222 --cv output/cv-renan-react.pdf --adapter fake
  career-ops-run --candidates data/candidates.json --cv output/cv-renan-react.pdf
  career-ops-run --candidates data/candidates.json --jd-dir data/jd-fixtures \\
    --adapter fake --run-id queue-demo
  career-ops-run --candidates data/candidates.json --requeue-reason "jd now available"
  career-ops-run --help

The real adapter needs an authenticated CDP browser already running (see the
README).  It never changes the Hermes files, ~/.local/bin or the upstream
career-ops checkout.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=COMMAND,
        description=(
            "Apply to one explicit LinkedIn job or to the first eligible job from "
            "a persistent candidate queue, record a session and return JSON. "
            "Success is reported only when LinkedIn confirms the application."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_HELP_EPILOG,
    )
    parser.add_argument(
        "--job",
        help="LinkedIn job id to apply to (mutually exclusive with --candidates)",
    )
    parser.add_argument(
        "--candidates",
        help=(
            "JSON array/object or TSV list of candidates; the first eligible job "
            "is applied and the queue is persisted in data/queue.json"
        ),
    )
    parser.add_argument(
        "--jd-dir",
        help=(
            "read JD text files as <job-id>.txt from this directory instead of "
            "LinkedIn's guest endpoint (offline runs and tests)"
        ),
    )
    parser.add_argument(
        "--requeue-reason",
        help=(
            "explicitly allow blocked ids in --candidates mode to return to the "
            "queue; the reason is recorded in the queue history"
        ),
    )
    parser.add_argument(
        "--cv",
        help=(
            "PDF to attach (default: $CAREER_OPS_CV, then the newest "
            "output/cv-*.pdf in the workspace)"
        ),
    )
    parser.add_argument(
        "--answers",
        help=(
            "answers JSON (default: $CAREER_OPS_ANSWERS, then the workspace or "
            "upstream config/answers-hermes.json)"
        ),
    )
    parser.add_argument(
        "--run-id",
        help="session directory name under output/sessions/ (default: UTC timestamp)",
    )
    parser.add_argument(
        "--adapter",
        choices=("real", "fake"),
        default="real",
        help="browser implementation; use fake for tests and demos (default: real)",
    )
    parser.add_argument(
        "--fake-scenario",
        choices=FAKE_SCENARIOS,
        default="success",
        help="outcome produced by --adapter fake (default: success)",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.adapter != "fake" and args.fake_scenario != "success":
        parser.error("--fake-scenario requires --adapter fake")
    if args.job is not None and args.candidates is not None:
        parser.error("pass exactly one of --job or --candidates")
    if args.job is None and args.candidates is None:
        parser.error("pass one of --job or --candidates")
    if args.jd_dir and not args.candidates:
        parser.error("--jd-dir requires --candidates")
    if args.requeue_reason and not args.candidates:
        parser.error("--requeue-reason requires --candidates")
    job_id = ""
    if args.job is not None:
        job_id = args.job.strip()
        if not job_id:
            parser.error("--job must not be empty")

    environment = load_environment(environ)
    try:
        paths = resolve_paths(environment)
        renderer_timeout = resolve_renderer_timeout(environment)
        apply_timeout = _positive_float(
            environment.get("CAREER_OPS_APPLY_TIMEOUT_SECONDS"),
            DEFAULT_APPLY_TIMEOUT_SECONDS,
            "CAREER_OPS_APPLY_TIMEOUT_SECONDS",
        )
    except ValueError as exc:
        return _emit(
            _error_payload(
                job_id=job_id or None,
                reason="configuration_error",
                message=str(exc),
            ),
            EXIT_PRECONDITION,
        )

    cv, cv_error = _resolve_cv(args.cv, environment, paths)
    if cv is None or cv_error is not None:
        return _emit(
            _error_payload(
                job_id=job_id or None,
                reason="cv_missing",
                message=cv_error or "no CV to attach",
            ),
            EXIT_PRECONDITION,
        )

    answers: Path | None = None
    if args.adapter == "real":
        answers, answers_error = _resolve_answers(args.answers, environment, paths)
        if answers is None or answers_error is not None:
            return _emit(
                _error_payload(
                    job_id=job_id or None,
                    reason="answers_missing",
                    message=answers_error or "no answers file found",
                    cv=cv,
                ),
                EXIT_PRECONDITION,
            )

    if args.candidates is not None:
        return _run_queue(
            args,
            environment=environment,
            paths=paths,
            cv=cv,
            answers=answers,
            apply_timeout=apply_timeout,
            renderer_timeout=renderer_timeout,
        )

    adapter = _build_adapter(
        args.adapter,
        args.fake_scenario,
        paths,
        environment,
        job_id=job_id,
        cv=cv,
        answers=answers,
        apply_timeout=apply_timeout,
    )
    watchdog = _build_watchdog(args.adapter, renderer_timeout, apply_timeout)

    try:
        session = SessionRecorder.create(
            paths,
            run_id=args.run_id,
            job={"id": job_id},
            screenshotter=adapter.capture,
        )
    except ValueError as exc:
        reason = "invalid_run_id" if "run id" in str(exc) else "configuration_error"
        return _emit(
            _error_payload(job_id=job_id, reason=reason, message=str(exc), cv=cv),
            EXIT_USAGE if reason == "invalid_run_id" else EXIT_PRECONDITION,
        )

    payload = _run_application(
        session=session,
        adapter=adapter,
        watchdog=watchdog,
        job_id=job_id,
        cv=cv,
    )
    return _emit(payload, _exit_code(payload))


def _run_queue(
    args: argparse.Namespace,
    *,
    environment: Mapping[str, str],
    paths: WorkspacePaths,
    cv: Path,
    answers: Path | None,
    apply_timeout: float,
    renderer_timeout: float,
) -> int:
    candidates_path = expand_path(args.candidates, environment)
    if not candidates_path.is_file():
        return _emit(
            _error_payload(
                job_id=None,
                reason="candidates_missing",
                message=f"candidate list not found: {candidates_path}",
                cv=cv,
            ),
            EXIT_PRECONDITION,
        )

    fetcher: JobDescriptionFetcher
    if args.jd_dir:
        jd_dir = expand_path(args.jd_dir, environment)
        if not jd_dir.is_dir():
            return _emit(
                _error_payload(
                    job_id=None,
                    reason="jd_source_missing",
                    message=f"JD directory not found: {jd_dir}",
                    cv=cv,
                ),
                EXIT_PRECONDITION,
            )
        fetcher = DirectoryJobDescriptionFetcher(jd_dir)
    else:
        fetcher = HttpJobDescriptionFetcher()

    try:
        rules = EligibilityRules.from_paths(paths)
    except ValueError as exc:
        return _emit(
            _error_payload(
                job_id=None,
                reason="configuration_error",
                message=str(exc),
                cv=cv,
            ),
            EXIT_PRECONDITION,
        )

    try:
        candidates = load_candidates(candidates_path)
    except ValueError as exc:
        return _emit(
            _error_payload(
                job_id=None,
                reason="invalid_candidates",
                message=str(exc),
                cv=cv,
            ),
            EXIT_USAGE,
        )

    try:
        queue = JobQueue.load(paths)
    except ValueError as exc:
        return _emit(
            _error_payload(
                job_id=None,
                reason="configuration_error",
                message=str(exc),
                cv=cv,
            ),
            EXIT_PRECONDITION,
        )

    ingested = queue.ingest(candidates, requeue_reason=args.requeue_reason)
    selection = QueueProcessor(queue, fetcher, rules=rules).next_eligible()
    if selection is None:
        payload = _queue_empty_payload(queue=queue, ingested=ingested, cv=cv)
        return _emit(payload, EXIT_FAILED)

    initial_job = selection.as_job()
    adapter = _build_adapter(
        args.adapter,
        args.fake_scenario,
        paths,
        environment,
        job_id=selection.job_id,
        cv=cv,
        answers=answers,
        apply_timeout=apply_timeout,
    )
    watchdog = _build_watchdog(args.adapter, renderer_timeout, apply_timeout)

    try:
        session = SessionRecorder.create(
            paths,
            run_id=args.run_id,
            job=initial_job,
            screenshotter=adapter.capture,
        )
    except ValueError as exc:
        reason = "invalid_run_id" if "run id" in str(exc) else "configuration_error"
        return _emit(
            _error_payload(
                job_id=selection.job_id,
                reason=reason,
                message=str(exc),
                cv=cv,
            ),
            EXIT_USAGE if reason == "invalid_run_id" else EXIT_PRECONDITION,
        )

    queue.begin(selection.job_id)
    payload = _run_application(
        session=session,
        adapter=adapter,
        watchdog=watchdog,
        job_id=selection.job_id,
        cv=cv,
        initial_job=initial_job,
    )
    _record_queue_outcome(queue, selection.job_id, payload)
    payload["queue"] = {
        "path": str(queue.path),
        "selection": selection.as_dict(),
        "ingested": [result.as_dict() for result in ingested],
        "record": queue.get(selection.job_id).as_dict(),
        "records": [record.as_dict() for record in queue.records.values()],
    }
    return _emit(payload, _exit_code(payload))


def _queue_empty_payload(
    *,
    queue: JobQueue,
    ingested: Sequence[EnqueueResult],
    cv: Path,
) -> dict[str, object]:
    payload = _envelope(
        run_id=None,
        job={"id": None},
        cv=cv,
        result=SubmissionResult(
            submitted=False,
            attempts=0,
            reason="no_eligible_job",
        ),
        message=(
            "no candidate passed the title/location filters and the eligibility rules"
        ),
        artifacts=_empty_artifacts(),
    )
    payload["queue"] = {
        "path": str(queue.path),
        "selection": None,
        "ingested": [result.as_dict() for result in ingested],
        "record": None,
        "records": [record.as_dict() for record in queue.records.values()],
    }
    return payload


def _record_queue_outcome(
    queue: JobQueue,
    job_id: str,
    payload: Mapping[str, object],
) -> None:
    failure = payload.get("failure")
    reason = failure.get("reason") if isinstance(failure, Mapping) else None
    if not isinstance(reason, str):
        result = payload.get("result")
        reason = str(result.get("reason")) if isinstance(result, Mapping) else "unknown"

    if payload.get("status") == "verified":
        state = "verified"
    elif reason == "waiting_input":
        state = "waiting_input"
    elif reason in _BLOCKER_MESSAGES:
        state = "ineligible"
    else:
        state = "failed"

    detail: dict[str, object] = {"run_id": payload.get("run_id"), "reason": reason}
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, Mapping) and artifacts.get("session_dir") is not None:
        detail["session_dir"] = artifacts["session_dir"]
    queue.complete(job_id, state, reason, detail)


def _run_application(
    *,
    session: SessionRecorder,
    adapter: ApplicationAdapter,
    watchdog: RendererWatchdog,
    job_id: str,
    cv: Path,
    initial_job: Mapping[str, object] | None = None,
) -> dict[str, object]:
    session_status = "failed"
    job_payload: dict[str, object] = (
        dict(initial_job) if initial_job is not None else {"id": job_id}
    )
    try:
        info = adapter.open()
        job_payload = {**job_payload, **info.as_dict()}
        _capture(session, "open", job_id)
        blocker = info.blocker
        if blocker is not None:
            message = _BLOCKER_MESSAGES[blocker]
            session.fail(message, job_id=job_id, detail={"reason": blocker})
            return _payload(
                session=session,
                job=job_payload,
                cv=cv,
                result=SubmissionResult(submitted=False, attempts=0, reason=blocker),
                message=message,
            )

        guard = SubmissionGuard(session, watchdog, recover=adapter.recover)
        result = guard.submit(job_id=job_id, expected_cv=cv, adapter=adapter)
        if result.submitted:
            session_status = "completed"
        return _payload(
            session=session,
            job=job_payload,
            cv=cv,
            result=result,
            message=(
                "LinkedIn confirmed the application"
                if result.submitted
                else _reason_message(result.reason)
            ),
        )
    except WaitingForInput as exc:
        session.fail(
            exc,
            job_id=job_id,
            detail={"reason": exc.reason, "questions": list(exc.questions)},
        )
        return _payload(
            session=session,
            job=job_payload,
            cv=cv,
            result=SubmissionResult(
                submitted=False,
                attempts=0,
                reason=exc.reason,
                retryable=True,
            ),
            message=str(exc),
            questions=exc.questions,
        )
    except AdapterError as exc:
        session.fail(exc, job_id=job_id, detail={"reason": exc.reason})
        return _payload(
            session=session,
            job=job_payload,
            cv=cv,
            result=SubmissionResult(
                submitted=False,
                attempts=0,
                reason=exc.reason,
                retryable=True,
            ),
            message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - a failure must still produce JSON and a session
        session.fail(exc, job_id=job_id, detail={"reason": "internal_error"})
        return _payload(
            session=session,
            job=job_payload,
            cv=cv,
            result=SubmissionResult(
                submitted=False,
                attempts=0,
                reason="internal_error",
            ),
            message=f"{type(exc).__name__}: {exc}",
        )
    finally:
        session.close(session_status)


def _payload(
    *,
    session: SessionRecorder,
    job: Mapping[str, object],
    cv: Path,
    result: SubmissionResult,
    message: str,
    questions: Sequence[str] = (),
) -> dict[str, object]:
    screenshots = sorted(
        path.relative_to(session.root).as_posix()
        for path in session.screenshots_dir.glob("*.png")
        if path.is_file()
    )
    return _envelope(
        run_id=session.run_id,
        job=job,
        cv=cv,
        result=result,
        message=message,
        questions=questions,
        artifacts={
            "session_dir": str(session.root),
            "session_json": str(session.root / "session.json"),
            "events": str(session.events_path),
            "screenshots": [str(session.root / name) for name in screenshots],
        },
    )


def _error_payload(
    *,
    job_id: str | None,
    reason: str,
    message: str,
    cv: Path | None = None,
) -> dict[str, object]:
    return _envelope(
        run_id=None,
        job={"id": job_id},
        cv=cv,
        result=SubmissionResult(submitted=False, attempts=0, reason=reason),
        message=message,
        artifacts=_empty_artifacts(),
    )


def _empty_artifacts() -> dict[str, object]:
    return {
        "session_dir": None,
        "session_json": None,
        "events": None,
        "screenshots": [],
    }


def _envelope(
    *,
    run_id: str | None,
    job: Mapping[str, object],
    cv: Path | None,
    result: SubmissionResult,
    message: str,
    artifacts: Mapping[str, object],
    questions: Sequence[str] = (),
) -> dict[str, object]:
    failure: dict[str, object] | None = None
    if not result.verified:
        failure = {
            "reason": result.reason,
            "message": message,
            "retryable": result.retryable,
        }
        if questions:
            failure["questions"] = list(questions)
    return {
        "command": COMMAND,
        "status": "verified" if result.verified else "failed",
        "run_id": run_id,
        "job": dict(job),
        "result": _result_dict(result),
        "failure": failure,
        "artifacts": dict(artifacts),
        "cv": str(cv) if cv is not None else None,
    }


def _result_dict(result: SubmissionResult) -> dict[str, object]:
    return {
        "submitted": result.submitted,
        "verified": result.verified,
        "reason": result.reason,
        "attempts": result.attempts,
        "expected_cv": result.expected_cv,
        "selected_cvs": list(result.selected_cvs),
        "retryable": result.retryable,
    }


def _capture(session: SessionRecorder, stage: str, job_id: str) -> None:
    try:
        session.capture(stage, job_id=job_id)
    except Exception:  # noqa: BLE001 - evidence must never change the outcome
        pass


def _build_adapter(
    adapter_name: str,
    scenario: FakeScenario,
    paths: WorkspacePaths,
    environment: Mapping[str, str],
    *,
    job_id: str,
    cv: Path,
    answers: Path | None,
    apply_timeout: float,
) -> ApplicationAdapter:
    if adapter_name == "fake":
        return FakeApplicationAdapter(job_id=job_id, cv=cv, scenario=scenario)
    if answers is None:
        raise AssertionError("the real adapter requires an answers file")
    return RealApplicationAdapter(
        paths,
        job_id=job_id,
        cv=cv,
        answers=answers,
        environ=environment,
        apply_timeout=apply_timeout,
    )


def _build_watchdog(
    adapter_name: str,
    renderer_timeout: float,
    apply_timeout: float,
) -> RendererWatchdog:
    if adapter_name == "fake":
        return RendererWatchdog(renderer_timeout)
    # The guard wraps whole adapter methods, and one real method may run several
    # subprocesses with their own deadlines.  Keep the outer deadline above the
    # worst case (two preload calls, easyapply and the CV selection, or three
    # verification calls) so the adapter's precise ``RendererTimeout`` wins.
    outer = apply_timeout + 3 * DEFAULT_JOBINFO_TIMEOUT_SECONDS + renderer_timeout
    return RendererWatchdog(outer)


def _resolve_cv(
    raw: str | None,
    environment: Mapping[str, str],
    paths: WorkspacePaths,
) -> tuple[Path | None, str | None]:
    configured = raw or environment.get("CAREER_OPS_CV")
    if configured:
        candidate = expand_path(configured, environment)
        if not candidate.is_file():
            return None, f"CV not found: {candidate}"
        return candidate.resolve(), None

    candidates = sorted(
        paths.output.glob("cv-*.pdf"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None, (
            "no CV found: pass --cv, set CAREER_OPS_CV or generate one in "
            f"{paths.output}"
        )
    return candidates[0].resolve(), None


def _resolve_answers(
    raw: str | None,
    environment: Mapping[str, str],
    paths: WorkspacePaths,
) -> tuple[Path | None, str | None]:
    configured = raw or environment.get("CAREER_OPS_ANSWERS")
    if configured:
        candidate = expand_path(configured, environment)
        if not candidate.is_file():
            return None, f"answers file not found: {candidate}"
        return candidate.resolve(), None
    found = paths.read_config("answers-hermes.json")
    if found is None:
        return None, (
            f"answers file not found in {paths.config} or {paths.upstream / 'config'}"
        )
    return found.resolve(), None


def _positive_float(raw: str | None, default: float, name: str) -> float:
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero, got {raw!r}")
    return value


def _reason_message(reason: str) -> str:
    return {
        "not_confirmed": "LinkedIn did not confirm the application",
        "wrong_cv": "the selected CV is not the expected PDF",
        "missing_cv": "no CV is selected on the form",
        "renderer_timeout": "the renderer did not answer before the deadline",
        "renderer_timeout_after_submit": (
            "the renderer timed out after the submit click; LinkedIn may already "
            "have registered the application"
        ),
        "renderer_recovery_failed": "the renderer could not be recovered",
        "exhausted": "the application used all attempts without a confirmation",
    }.get(reason, reason.replace("_", " "))


def _exit_code(payload: Mapping[str, object]) -> int:
    if payload.get("status") == "verified":
        return EXIT_VERIFIED
    failure = payload.get("failure")
    if isinstance(failure, Mapping) and failure.get("reason") == "waiting_input":
        return EXIT_WAITING_INPUT
    return EXIT_FAILED


def _emit(payload: Mapping[str, object], exit_code: int) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

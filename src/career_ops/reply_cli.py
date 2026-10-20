"""``career-ops-reply`` — answer a parked form and resume it in one call.

A daily run leaves at most one form open when it cannot answer a question. The
parked record under ``data/parked-form.json`` names the job, the CDP tab and the
questions. This command validates the answers, merges them into the workspace
``config/answers-hermes.json`` and resumes the same tab, then reports one JSON
object exactly like ``career-ops-run``.

The Hermes bridge, the cron and the allowlist are out of scope: this command is
only the contract they will call.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence

from career_ops import cli
from career_ops.adapter import PendingQuestion
from career_ops.catalog import build_epilog
from career_ops.fake_adapter import FAKE_SCENARIOS, FakeApplicationAdapter, FakeScenario
from career_ops.parked import ANSWERS_FILENAME, ParkedForm, ParkedFormStore
from career_ops.paths import WorkspacePaths, expand_path, load_environment, resolve_paths
from career_ops.queue import JobQueue, record_application_outcome
from career_ops.real_adapter import (
    DEFAULT_APPLY_TIMEOUT_SECONDS,
    RealApplicationAdapter,
)
from career_ops.renderer import resolve_renderer_timeout
from career_ops.run_lock import LOCK_FILENAME, RunLock, RunLocked
from career_ops.run_state import RunState, utcnow
from career_ops.session import SessionRecorder

COMMAND = "career-ops-reply"
EXIT_VERIFIED = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_PRECONDITION = 3
EXIT_WAITING_INPUT = 6

SUMMARY = "Answer a parked LinkedIn form and resume it in one call."

EXIT_CODES = (
    (EXIT_VERIFIED, "LinkedIn confirmed the resumed application"),
    (EXIT_FAILED, "the form resumed but the application failed or was not confirmed"),
    (
        EXIT_USAGE,
        "invalid arguments or an answer that does not match a pending question",
    ),
    (
        EXIT_PRECONDITION,
        "no parked form, token/run/job mismatch, lost CV or answers file unwritable",
    ),
    (
        EXIT_WAITING_INPUT,
        "the resumed form stopped on another unknown question (still parked)",
    ),
)

EXAMPLES = (
    "career-ops-reply --run-id daily-2026-10-20 --job 4411222 --token a1b2c3 \\\n"
    '    --answer "Are you authorized to work?=Yes"',
    "career-ops-reply --run-id daily-2026-10-20 --job 4411222 --token a1b2c3 \\\n"
    '    --answer "Are you authorized to work?=Yes" --adapter fake '
    "--fake-scenario success",
    "career-ops-reply --help",
)

OUTPUT_SCHEMA = {
    "format": "json",
    "schema": {
        "type": "object",
        "required": [
            "command",
            "status",
            "run_id",
            "job",
            "result",
            "failure",
            "artifacts",
            "cv",
            "waiting_input",
            "answers",
        ],
        "properties": {
            "command": {"const": COMMAND},
            "status": {"type": "string", "enum": ["verified", "failed"]},
            "run_id": {"type": ["string", "null"]},
            "job": {"type": "object"},
            "result": {"type": "object"},
            "failure": {"type": ["object", "null"]},
            "artifacts": {"type": "object"},
            "cv": {"type": ["string", "null"]},
            "waiting_input": {"type": ["object", "null"]},
            "answers": {"type": ["object", "null"]},
            "run": {"type": "object"},
            "queue": {"type": "object"},
            "parked_form_error": {"type": "string"},
        },
        "additionalProperties": True,
    },
}

_HELP_EPILOG = build_epilog(
    """\
Resume the LinkedIn form that is parked after `career-ops-run` exited 6.

The run JSON contains the pending questions, their options and the resume token:

  "waiting_input": {
    "token": "a1b2c3...",
    "run_id": "daily-2026-10-20",
    "job": {"id": "4411222", "company": "Acme", ...},
    "target": "CDP-TARGET-ID",
    "questions": [
      {"text": "Are you authorized to work?", "kind": "radio",
       "options": ["Yes", "No"]}
    ]
  }

Each --answer is "<question>=<answer>". The question may be the full text or a
unique part of it; radio/select answers must match one of the listed options.
Answers are merged into the workspace config/answers-hermes.json (never into the
read-only upstream checkout) and the form is resumed through the stored target.
A lost tab is reported as `parked_form_lost` and is never counted as sent.

Output (stdout is always one JSON object) includes:
  command, status, run_id, job, result, failure, artifacts, cv, waiting_input
  and answers: {"path": "...", "written": ["question", ...]}.
""",
    EXIT_CODES,
    EXAMPLES,
)


class InvalidAnswer(ValueError):
    """One supplied answer cannot be applied to the parked questions."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=COMMAND,
        description=(
            "Validate answers for the parked LinkedIn form, write them to the "
            "workspace answers file and resume the same tab."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_HELP_EPILOG,
    )
    parser.add_argument("--run-id", required=True, help="run that parked the form")
    parser.add_argument("--job", required=True, help="LinkedIn job id of the parked form")
    parser.add_argument(
        "--token",
        required=True,
        help="resume token from the run JSON waiting_input.token",
    )
    parser.add_argument(
        "--answer",
        action="append",
        default=[],
        metavar="QUESTION=ANSWER",
        help="answer to one pending question (repeatable)",
    )
    parser.add_argument(
        "--answers",
        help="JSON object (or path to one) with question => answer entries",
    )
    parser.add_argument(
        "--answers-file",
        help=(
            "workspace answers file to update (default: config/answers-hermes.json, "
            "or $CAREER_OPS_ANSWERS)"
        ),
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
    clock: Callable[[], datetime] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.adapter != "fake" and args.fake_scenario != "success":
        parser.error("--fake-scenario requires --adapter fake")
    if not args.answer and not args.answers:
        parser.error("pass at least one --answer or --answers")
    if not args.job.strip():
        parser.error("--job must not be empty")
    if not args.token.strip():
        parser.error("--token must not be empty")

    now = clock or utcnow
    environment = load_environment(environ)
    try:
        paths = resolve_paths(environment)
        renderer_timeout = resolve_renderer_timeout(environment)
        apply_timeout = cli._positive_float(
            environment.get("CAREER_OPS_APPLY_TIMEOUT_SECONDS"),
            DEFAULT_APPLY_TIMEOUT_SECONDS,
            "CAREER_OPS_APPLY_TIMEOUT_SECONDS",
        )
        answers_path = _answers_path(args.answers_file, environment, paths)
        paths.assert_writable(answers_path)
    except ValueError as exc:
        return cli._emit(
            _reply(_error(reason="configuration_error", message=str(exc))),
            EXIT_PRECONDITION,
        )

    store = ParkedFormStore(paths, clock=now)
    try:
        parked = store.load()
    except ValueError as exc:
        return cli._emit(
            _reply(_error(reason="parked_form_unreadable", message=str(exc))),
            EXIT_PRECONDITION,
        )
    if parked is None:
        return cli._emit(
            _reply(_error(reason="no_parked_form", message="no parked form in this workspace")),
            EXIT_PRECONDITION,
        )
    if (
        parked.run_id != args.run_id.strip()
        or parked.job_id != args.job.strip()
        or parked.token != args.token.strip()
    ):
        return cli._emit(
            _reply(
                _error(
                    reason="parked_form_mismatch",
                    message=(
                        "run, job and token must match the parked form "
                        f"(parked job {parked.job_id!r}, run {parked.run_id!r})"
                    ),
                )
            ),
            EXIT_PRECONDITION,
        )

    cv = Path(parked.cv) if parked.cv else None
    if cv is None or not cv.is_file():
        return cli._emit(
            _reply(
                _error(
                    reason="cv_missing",
                    message=(
                        f"the CV used by the parked form was not found: {parked.cv!r}"
                    ),
                )
            ),
            EXIT_PRECONDITION,
        )
    if parked.target is None:
        # Without the exact tab id a resume would reopen the form from scratch,
        # which is exactly what parking is meant to avoid.
        return cli._emit(
            _reply(
                _error(
                    reason="parked_target_missing",
                    message="the parked form has no CDP target to resume",
                )
            ),
            EXIT_PRECONDITION,
        )

    try:
        answers = _collect_answers(args.answer, args.answers, environment)
        validated = validate_answers(parked.questions, answers)
    except (InvalidAnswer, ValueError) as exc:
        payload = _error(reason="invalid_answer", message=str(exc))
        payload["waiting_input"] = parked.as_dict()
        return cli._emit(_reply(payload), EXIT_USAGE)

    try:
        written = write_answers(answers_path, validated, assert_writable=paths.assert_writable)
    except (OSError, ValueError) as exc:
        payload = _error(reason="answers_unwritable", message=str(exc))
        payload["waiting_input"] = parked.as_dict()
        return cli._emit(_reply(payload), EXIT_PRECONDITION)

    adapter = _build_adapter(
        args.adapter,
        args.fake_scenario,
        paths,
        environment,
        parked=parked,
        cv=cv,
        answers_path=answers_path,
        apply_timeout=apply_timeout,
    )
    watchdog = cli._build_watchdog(args.adapter, renderer_timeout, apply_timeout)

    try:
        with RunLock(paths.data / LOCK_FILENAME, assert_writable=paths.assert_writable, clock=now):
            session = SessionRecorder.create(
                paths,
                run_id=parked.run_id,
                job=parked.job,
                screenshotter=adapter.capture,
                clock=now,
                subdir=parked.job_id,
            )
            payload = cli._run_application(
                session=session,
                adapter=adapter,
                watchdog=watchdog,
                job_id=parked.job_id,
                cv=cv,
                resume_job=parked.job,
            )
    except RunLocked as exc:
        return cli._emit(
            _reply(_error(reason="run_locked", message=str(exc))),
            EXIT_PRECONDITION,
        )
    except ValueError as exc:
        return cli._emit(
            _reply(_error(reason="configuration_error", message=str(exc))),
            EXIT_PRECONDITION,
        )

    try:
        payload = cli._park_if_waiting(
            payload,
            store=store,
            run_id=parked.run_id,
            target_goal=parked.target_goal,
        )
    except ValueError as exc:
        payload["parked_form_error"] = str(exc)
    waiting_again = payload.get("waiting_input") is not None
    if not waiting_again:
        try:
            store.clear()
        except (OSError, ValueError) as exc:
            payload["parked_form_error"] = str(exc)

    payload["answers"] = {"path": str(answers_path), "written": written}
    _persist(paths, parked, payload, clock=now)
    return cli._emit(_reply(payload), cli._exit_code(payload))


def validate_answers(
    questions: Sequence[PendingQuestion],
    answers: Mapping[str, str],
) -> dict[str, str]:
    """Resolve each supplied key to one pending question and validate the value."""
    validated: dict[str, str] = {}
    for key, raw_value in answers.items():
        question = _match_question(questions, key)
        if question is None:
            available = "; ".join(question.text for question in questions) or "none"
            raise InvalidAnswer(
                f"no pending question matches {key!r}; pending: {available}"
            )
        value = str(raw_value).strip()
        if not value:
            raise InvalidAnswer(f"answer for {question.text!r} must not be empty")
        if question.kind in {"radio", "select"} and question.options:
            matching = [
                option
                for option in question.options
                if option.casefold() == value.casefold()
            ]
            if not matching:
                raise InvalidAnswer(
                    f"answer {value!r} is not valid for {question.text!r}; "
                    f"choose one of: {', '.join(question.options)}"
                )
            value = matching[0]
        validated[question.text] = value
    return validated


def write_answers(
    path: Path,
    answers: Mapping[str, str],
    *,
    assert_writable,
) -> list[str]:
    """Merge answers into the workspace file, preserving unrelated entries."""
    existing: dict[str, str] = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read answers file {path}: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError(f"answers file {path} must contain a JSON object")
        existing = {str(key): str(value) for key, value in payload.items()}
    existing.update({key: value for key, value in answers.items()})
    assert_writable(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return list(answers)


def _match_question(
    questions: Sequence[PendingQuestion],
    key: str,
) -> PendingQuestion | None:
    needle = key.strip().casefold()
    if not needle:
        return None
    exact = [question for question in questions if question.text.casefold() == needle]
    if exact:
        return exact[0]
    contained = [
        question for question in questions if needle in question.text.casefold()
    ]
    return contained[0] if len(contained) == 1 else None


def _collect_answers(
    raw_answers: Sequence[str],
    raw_document: str | None,
    environment: Mapping[str, str],
) -> dict[str, str]:
    answers: dict[str, str] = {}
    if raw_document:
        text = raw_document.strip()
        if text.startswith("{"):
            payload = json.loads(text)
        else:
            path = expand_path(raw_document, environment)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ValueError(f"could not read answers file {path}: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("--answers must contain a JSON object")
        answers.update({str(key): str(value) for key, value in payload.items()})
    for item in raw_answers:
        key, separator, value = item.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"invalid --answer {item!r}: use QUESTION=ANSWER")
        answers[key.strip()] = value.strip()
    return answers


def _answers_path(
    raw: str | None,
    environment: Mapping[str, str],
    paths: WorkspacePaths,
) -> Path:
    configured = raw or environment.get("CAREER_OPS_ANSWERS")
    if configured:
        return expand_path(configured, environment)
    return paths.config / ANSWERS_FILENAME


def _build_adapter(
    adapter_name: str,
    scenario: FakeScenario,
    paths: WorkspacePaths,
    environment: Mapping[str, str],
    *,
    parked: ParkedForm,
    cv: Path,
    answers_path: Path,
    apply_timeout: float,
):
    if adapter_name == "fake":
        return FakeApplicationAdapter(
            job_id=parked.job_id,
            cv=cv,
            scenario=scenario,
            resume=True,
            target=parked.target,
        )
    return RealApplicationAdapter(
        paths,
        job_id=parked.job_id,
        cv=cv,
        answers=answers_path,
        environ=environment,
        apply_timeout=apply_timeout,
        resume_target=parked.target,
    )


def _persist(
    paths: WorkspacePaths,
    parked: ParkedForm,
    payload: dict[str, object],
    *,
    clock,
) -> None:
    """Update the queue and run state after a resume, without hiding the result."""
    try:
        queue = JobQueue.load(paths, clock=clock)
        if parked.job_id in queue.records:
            record_application_outcome(queue, parked.job_id, payload)
    except ValueError:
        payload["queue_error"] = "could not update the queue after the resume"

    try:
        state = RunState.load_or_create(
            paths,
            run_id=parked.run_id,
            target=parked.target_goal,
            clock=clock,
        )
        verified = payload.get("status") == "verified"
        if verified and parked.job_id not in state.verified_jobs():
            state.verified += 1
        state.record_job(
            parked.job_id,
            state=_state(payload),
            reason=_reason(payload),
            attempts=_attempts(paths, parked.job_id),
            verified=verified,
            submitted=bool(_mapping(payload.get("result")).get("clicked")),
            waiting=_reason(payload) == "waiting_input",
            cv=str(parked.cv) if parked.cv else None,
            session_dir=_session_dir(payload),
            duration_ms=0,
        )
        if verified and state.verified >= state.target:
            state.finish(status="verified", stop_reason="target_reached")
        state.save()
        payload["run"] = state.snapshot()
    except ValueError:
        payload["run_error"] = "could not update the run state after the resume"


def _attempts(paths: WorkspacePaths, job_id: str) -> int:
    try:
        queue = JobQueue.load(paths)
    except ValueError:
        return 0
    record = queue.records.get(job_id)
    return record.attempts if record is not None else 0


def _state(payload: Mapping[str, object]) -> str:
    if payload.get("status") == "verified":
        return "verified"
    if _reason(payload) == "waiting_input":
        return "waiting_input"
    return "failed"


def _reason(payload: Mapping[str, object]) -> str | None:
    failure = payload.get("failure")
    if isinstance(failure, Mapping) and failure.get("reason") is not None:
        return str(failure["reason"])
    return None


def _session_dir(payload: Mapping[str, object]) -> str | None:
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, Mapping) and artifacts.get("session_dir") is not None:
        return str(artifacts["session_dir"])
    return None


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _error(*, reason: str, message: str) -> dict[str, object]:
    return cli._error_payload(job_id=None, reason=reason, message=message)


def _reply(payload: dict[str, object]) -> dict[str, object]:
    payload["command"] = COMMAND
    payload.setdefault("answers", None)
    return payload


if __name__ == "__main__":
    raise SystemExit(main())

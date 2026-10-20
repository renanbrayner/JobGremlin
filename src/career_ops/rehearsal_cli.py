"""Developer-only rehearsal and handoff evidence runner.

This is not a Hermes command.  It runs the real ``career-ops-run`` CLI three
times with the fake adapter, in a throwaway workspace below
``output/rehearsals/<date>/``:

1. one explicit candidate (target 1);
2. a mixed shortlist with title, location and eligibility discards (target 3);
3. twenty-five candidates that stop exactly at twenty verified (target 20).

Before and after the runs it fingerprints ``~/.hermes``, the allowlist, cron,
the installed command entry points and the configured read-only career-ops
checkout.  The report and the machine-readable evidence land in
``docs/rehearsals/``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from career_ops.isolation import default_targets, take_snapshot
from career_ops.paths import REPO_ROOT, load_environment, resolve_paths
from career_ops.rehearsal import (
    RehearsalStep,
    render_rehearsal_report,
)

FRONTEND_JD = """\
Desenvolvedor Front-end Sênior

Requisitos:
- React e TypeScript.
"""

BACKEND_JD = """\
Desenvolvedor Backend Sênior

Requisitos:
- Python e Django.
"""

FULLSTACK_JD = """\
Desenvolvedor Full Stack Sênior

Requisitos:
- React, Node.js e TypeScript.
"""

DEVOPS_JD = """\
Software Engineer

Requirements:
- Kubernetes and Terraform.
"""

ONE = "rehearsal-one"
THREE = "rehearsal-three"
TWENTY = "rehearsal-twenty"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rehearsal",
        description=(
            "Run the 1/3/20 job rehearsal with the fake adapter, compare it with "
            "the 19/10 baseline and fingerprint the current installation."
        ),
    )
    parser.add_argument(
        "--date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="report date and run-id suffix (default: today in UTC)",
    )
    parser.add_argument(
        "--workspace-root",
        help="throwaway workspace (default: output/rehearsals/<date>/workspace)",
    )
    parser.add_argument(
        "--docs-dir",
        default=str(REPO_ROOT / "docs" / "rehearsals"),
        help="where to write <date>.md and <date>.json (default: docs/rehearsals)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    date = args.date.strip()
    if not date:
        return _fail("--date must not be empty")

    workspace_root = (
        Path(args.workspace_root)
        if args.workspace_root
        else REPO_ROOT / "output" / "rehearsals" / date / "workspace"
    ).resolve()
    docs_dir = Path(args.docs_dir).resolve()

    try:
        environment = load_environment(dict(os.environ))
        current = resolve_paths(environment)
    except ValueError as exc:
        return _fail(f"invalid workspace configuration: {exc}")

    targets = default_targets(
        current,
        environ=environment,
        home=_home(environment),
    )
    before = take_snapshot(targets)

    try:
        _prepare_workspace(
            workspace_root,
            protected=(
                _home(environment) / ".hermes",
                _home(environment) / ".local" / "bin",
                current.upstream,
            ),
        )
        run_environment = _run_environment(environment, workspace_root, current)
        steps = [
            _run_one(run_environment, workspace_root, date),
            _run_three(run_environment, workspace_root, date),
            _run_twenty(run_environment, workspace_root, date),
        ]
    except RehearsalError as exc:
        return _fail(str(exc))
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        return _fail(f"{type(exc).__name__}: {exc}")

    after = take_snapshot(targets)
    isolation = after.compare(before)
    if not isolation["unchanged"]:
        changed = [
            str(target.get("name"))
            for target in _targets(isolation)
            if target.get("changed")
        ]
        return _fail(f"the current installation changed during the rehearsal: {changed}")

    markdown, report = render_rehearsal_report(
        date=date,
        steps=steps,
        isolation=isolation,
        root=REPO_ROOT,
    )
    docs_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = docs_dir / f"{date}.md"
    json_path = docs_dir / f"{date}.json"
    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    payload = {
        "command": "rehearsal",
        "status": "ok",
        "date": date,
        "workspace": str(workspace_root),
        "report": {"markdown": str(markdown_path), "json": str(json_path)},
        "steps": [
            {
                "label": step.label,
                "run_id": step.run_id,
                "target": step.target,
                "status": step.status,
                "stop_reason": step.stop_reason,
                "verified": step.metrics()["verified"],
                "submitted": step.metrics()["submitted"],
                "artifacts": step.artifacts(root=REPO_ROOT),
            }
            for step in steps
        ],
        "isolation": isolation,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


class RehearsalError(RuntimeError):
    """A rehearsal round did not produce the expected result."""


def _prepare_workspace(root: Path, *, protected: Sequence[Path]) -> None:
    if root in {Path("/"), Path.home(), REPO_ROOT}:
        raise RehearsalError(f"refusing to replace unsafe workspace {root}")
    for path in protected:
        resolved = path.resolve()
        if root == resolved or root.is_relative_to(resolved):
            raise RehearsalError(
                f"refusing to replace {root}: it is inside the protected path {resolved}"
            )
    if root.exists():
        shutil.rmtree(root)
    for name in ("config", "data", "output"):
        (root / name).mkdir(parents=True)


def _run_environment(
    environment: Mapping[str, str],
    workspace: Path,
    current,
) -> dict[str, str]:
    values = dict(environment)
    values.update(
        {
            "CAREER_OPS_HOME": str(workspace),
            "CAREER_OPS_CONFIG": str(workspace / "config"),
            "CAREER_OPS_DATA": str(workspace / "data"),
            "CAREER_OPS_OUTPUT": str(workspace / "output"),
            "CAREER_OPS_SCRIPTS": str(current.scripts),
            "CAREER_OPS_UPSTREAM": str(current.upstream),
            # The three rounds must stay available for the report.
            "CAREER_OPS_RETENTION_RUNS": "3",
        }
    )
    return values


def _run_one(environment: Mapping[str, str], root: Path, date: str) -> RehearsalStep:
    candidates = _candidates(root, "one", [(101, "Desenvolvedor React", "Recife, PE", "Remote")])
    jds = _jds(root, "one", {"101": FRONTEND_JD})
    return _invoke(
        environment,
        candidates=candidates,
        jd_dir=jds,
        target=1,
        run_id=f"{ONE}-{date}",
        expected=1,
        label="1 vaga",
    )


def _run_three(environment: Mapping[str, str], root: Path, date: str) -> RehearsalStep:
    candidates = _candidates(
        root,
        "three",
        [
            (201, "Desenvolvedor Backend", "Recife, PE", "Remote"),
            (202, "QA Automation Engineer", "Recife, PE", "Remote"),
            (203, "Desenvolvedor Backend", "São Paulo, SP", "Híbrido"),
            (204, "Software Engineer", "Recife, PE", "Remote"),
            (205, "Desenvolvedor Backend", "Recife, PE", "Remote"),
            (206, "Desenvolvedor Backend", "Recife, PE", "Remote"),
        ],
    )
    jds = _jds(
        root,
        "three",
        {
            "201": BACKEND_JD,
            "204": DEVOPS_JD,
            "205": BACKEND_JD,
            "206": BACKEND_JD,
        },
    )
    return _invoke(
        environment,
        candidates=candidates,
        jd_dir=jds,
        target=3,
        run_id=f"{THREE}-{date}",
        expected=3,
        label="3 vagas",
    )


def _run_twenty(environment: Mapping[str, str], root: Path, date: str) -> RehearsalStep:
    candidates = _candidates(
        root,
        "twenty",
        [
            (300 + index, "Desenvolvedor Full Stack", "Recife, PE", "Remote")
            for index in range(1, 26)
        ],
    )
    jds = _jds(
        root,
        "twenty",
        {str(300 + index): FULLSTACK_JD for index in range(1, 26)},
    )
    return _invoke(
        environment,
        candidates=candidates,
        jd_dir=jds,
        target=20,
        run_id=f"{TWENTY}-{date}",
        expected=20,
        label="20 vagas",
    )


def _invoke(
    environment: Mapping[str, str],
    *,
    candidates: Path,
    jd_dir: Path,
    target: int,
    run_id: str,
    expected: int,
    label: str,
) -> RehearsalStep:
    scripts_dir = Path(environment["CAREER_OPS_SCRIPTS"])
    result = subprocess.run(
        [
            str(scripts_dir / "career-ops-run"),
            "--candidates",
            str(candidates),
            "--jd-dir",
            str(jd_dir),
            "--adapter",
            "fake",
            "--target",
            str(target),
            "--run-id",
            run_id,
        ],
        env=dict(environment),
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RehearsalError(
            f"{label}: career-ops-run did not return JSON (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        ) from exc
    if result.returncode != 0:
        raise RehearsalError(
            f"{label}: career-ops-run exited {result.returncode}: "
            f"{payload.get('failure') or payload}"
        )
    if payload.get("status") != "verified":
        raise RehearsalError(f"{label}: expected verified, got {payload.get('status')}")
    if payload.get("verified") != expected:
        raise RehearsalError(
            f"{label}: expected {expected} verified, got {payload.get('verified')}"
        )
    if payload.get("stop_reason") != "target_reached":
        raise RehearsalError(
            f"{label}: expected target_reached, got {payload.get('stop_reason')}"
        )

    summary_path = (
        Path(environment["CAREER_OPS_OUTPUT"]) / "sessions" / run_id / "summary.json"
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    _assert_complete(environment, run_id=run_id, expected=expected, summary=summary)
    return RehearsalStep(label=label, run_id=run_id, summary=summary)


def _assert_complete(
    environment: Mapping[str, str],
    *,
    run_id: str,
    expected: int,
    summary: Mapping[str, object],
) -> None:
    run_dir = Path(environment["CAREER_OPS_OUTPUT"]) / "sessions" / run_id
    report = summary.get("report")
    if not isinstance(report, Mapping):
        raise RehearsalError(f"{run_id}: summary has no report paths")
    for name in ("markdown", "html"):
        if not Path(str(report.get(name))).is_file():
            raise RehearsalError(f"{run_id}: missing {name}")
    for name in ("summary.txt", "summary.json"):
        if not (run_dir / name).is_file():
            raise RehearsalError(f"{run_id}: missing {name}")
    if summary.get("verified") != expected:
        raise RehearsalError(
            f"{run_id}: summary reports {summary.get('verified')} verified, expected {expected}"
        )

    sessions = sorted(path for path in run_dir.iterdir() if path.is_dir())
    if len(sessions) != expected:
        raise RehearsalError(
            f"{run_id}: expected {expected} sessions, found {len(sessions)}"
        )
    for session in sessions:
        for name in ("session.json", "events.jsonl"):
            if not (session / name).is_file():
                raise RehearsalError(f"{run_id}: {session.name} is missing {name}")
        screenshots = list((session / "screenshots").glob("*.png"))
        if len(screenshots) < 4:
            raise RehearsalError(
                f"{run_id}: {session.name} has only {len(screenshots)} screenshots"
            )


def _candidates(
    root: Path,
    name: str,
    entries: Sequence[tuple[int, str, str, str]],
) -> Path:
    path = root / "data" / f"candidates-{name}.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": str(job_id),
                    "title": title,
                    "location": location,
                    "workplace": workplace,
                }
                for job_id, title, location, workplace in entries
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _jds(root: Path, name: str, entries: Mapping[str, str]) -> Path:
    directory = root / "data" / f"jd-{name}"
    directory.mkdir(parents=True, exist_ok=True)
    for job_id, text in entries.items():
        (directory / f"{job_id}.txt").write_text(text, encoding="utf-8")
    return directory


def _targets(isolation: Mapping[str, object]) -> list[Mapping[str, object]]:
    targets = isolation.get("targets")
    if not isinstance(targets, list):
        return []
    return [target for target in targets if isinstance(target, Mapping)]


def _home(environment: Mapping[str, str]) -> Path:
    raw = environment.get("HOME", "").strip()
    return Path(raw) if raw else Path.home()


def _fail(message: str) -> int:
    print(json.dumps({"command": "rehearsal", "status": "failed", "message": message}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

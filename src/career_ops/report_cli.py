"""``career-ops-report`` — rebuild one run's reports and apply retention.

The command is read-only with respect to LinkedIn and the upstream checkout.  It
reads ``data/runs/<run_id>.json`` and the session artifacts, writes
``report.md``/``report.html`` plus the text/JSON summaries into the run's
session directory, and prunes finished runs beyond the retention window.  If the
requested run is older than the window, its report is written first and the run
is then removed.
"""

from __future__ import annotations

import argparse
import json
from typing import Mapping, Sequence

from career_ops.catalog import build_epilog
from career_ops.paths import load_environment, resolve_paths
from career_ops.report import (
    DEFAULT_RETENTION_RUNS,
    ReportError,
    build_run_report,
    latest_run_id,
    prune_runs,
    retention_limit,
)

COMMAND = "career-ops-report"
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_PRECONDITION = 3

SUMMARY = "Rebuild one run's Markdown/HTML report, summaries and retention."

EXIT_CODES = (
    (EXIT_OK, "reports generated"),
    (EXIT_FAILED, "the requested run does not exist or is unreadable"),
    (EXIT_USAGE, "invalid command-line arguments"),
    (EXIT_PRECONDITION, "invalid workspace configuration or a retention failure"),
)

EXAMPLES = (
    "career-ops-report --run-id daily-2026-10-20",
    "career-ops-report --run-id daily-2026-10-20 --json",
    "career-ops-report --run-id daily-2026-10-20 --keep 5",
    "career-ops-report --run-id daily-2026-10-20 --no-prune",
    "career-ops-report --help",
)

OUTPUT_SCHEMA = {
    "format": "text (default) or json (--json)",
    "schema": {
        "type": "object",
        "required": [
            "command",
            "status",
            "run_id",
            "artifacts",
        ],
        "properties": {
            "command": {"const": COMMAND},
            "status": {"type": "string"},
            "run_id": {"type": ["string", "null"]},
            "failure": {"type": "object"},
            "summary": {"type": "object"},
            "jobs": {"type": "array"},
            "artifacts": {"type": "object"},
            "retention": {"type": "object"},
        },
        "additionalProperties": True,
    },
}

_HELP_EPILOG = build_epilog(
    """\
Output (stdout):
  Human mode prints the short text summary. With --json it prints one JSON
  object with the funnel, per-job rows, artifact paths and the pruned runs.

Reports are written into output/sessions/<run_id>/:
  report.md      funnel, discards and one row per job
  report.html    the same report with screenshot thumbnails
  summary.txt    short text summary for people
  summary.json   machine-readable summary for Hermes

Retention keeps the last three finished runs by default
(CAREER_OPS_RETENTION_RUNS or --keep); unfinished runs are never removed. A
requested run outside the window is reported first and then removed. No file
from Hermes, the cron, ~/.local/bin or the upstream career-ops checkout is read
or written.
""",
    EXIT_CODES,
    EXAMPLES,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=COMMAND,
        description=(
            "Generate the Markdown/HTML report and text/JSON summaries for one "
            "run, then keep only the most recent finished runs."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_HELP_EPILOG,
    )
    parser.add_argument(
        "--run-id",
        help="run to report (default: the most recently finished run)",
    )
    parser.add_argument(
        "--keep",
        type=int,
        help=(
            "finished runs to retain after reporting "
            f"(default: {DEFAULT_RETENTION_RUNS} or $CAREER_OPS_RETENTION_RUNS)"
        ),
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="generate the report without applying retention",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the machine-readable summary instead of the text summary",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.keep is not None and args.keep < 1:
        parser.error("--keep must be at least 1")
    run_id = args.run_id.strip() if isinstance(args.run_id, str) else args.run_id
    if run_id == "":
        parser.error("--run-id must not be empty")

    environment = load_environment(environ)
    try:
        paths = resolve_paths(environment)
        keep = (
            DEFAULT_RETENTION_RUNS
            if args.no_prune
            else retention_limit(args.keep, environment)
        )
    except ValueError as exc:
        return _emit(
            _error_payload(run_id, "configuration_error", str(exc)),
            EXIT_PRECONDITION,
        )

    if run_id is None:
        run_id = latest_run_id(paths)
        if run_id is None:
            return _emit(
                _error_payload(None, "run_not_found", "no finished run was found"),
                EXIT_FAILED,
            )

    try:
        report = build_run_report(paths, run_id)
    except ReportError as exc:
        return _emit(
            _error_payload(run_id, exc.reason, exc.message),
            EXIT_FAILED if exc.reason in {"run_not_found", "run_unreadable"} else EXIT_PRECONDITION,
        )
    except ValueError as exc:
        return _emit(
            _error_payload(run_id, "invalid_run_id", str(exc)),
            EXIT_USAGE,
        )

    pruned: tuple[str, ...] = ()
    if not args.no_prune:
        try:
            pruned = prune_runs(paths, keep=keep)
        except (OSError, ValueError) as exc:
            return _emit(
                _error_payload(run_id, "retention_failed", str(exc)),
                EXIT_PRECONDITION,
            )

    if args.json:
        payload = {
            "command": COMMAND,
            "status": report.summary.get("status"),
            "run_id": run_id,
            "summary": dict(report.summary),
            "jobs": [job.as_dict() for job in report.jobs],
            "artifacts": report.artifacts.as_dict(),
            "retention": {"keep": keep, "removed": list(pruned)},
        }
        return _emit(payload, EXIT_OK)

    print(report.text, end="")
    if pruned:
        print(f"Retenção: {len(pruned)} sessão(ões) antiga(s) removida(s): {', '.join(pruned)}")
    return EXIT_OK


def _error_payload(run_id: str | None, reason: str, message: str) -> dict[str, object]:
    return {
        "command": COMMAND,
        "status": "failed",
        "run_id": run_id,
        "failure": {"reason": reason, "message": message},
        "artifacts": {},
    }


def _emit(payload: Mapping[str, object], exit_code: int) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

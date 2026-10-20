"""``career-ops-help`` — discover the CLI without reverse engineering it.

The human overview and the ``--json`` catalog are both rendered from
``career_ops.catalog.REGISTRY``.  The catalog is read-only: it resolves no
workspace paths and touches no browser, Hermes file or upstream checkout.
"""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from career_ops.catalog import build_catalog, format_examples, format_exit_codes, render_text

COMMAND = "career-ops-help"
EXIT_OK = 0
EXIT_USAGE = 2

SUMMARY = "Show the human command overview or the machine-readable JSON catalog."

EXIT_CODES = (
    (EXIT_OK, "the overview or catalog was printed"),
    (EXIT_USAGE, "invalid command-line arguments"),
)

EXAMPLES = (
    "career-ops-help",
    "career-ops-help --json",
    "career-ops-help --help",
)

OUTPUT_SCHEMA = {
    "format": "text (default) or json (--json)",
    "schema": {
        "type": "object",
        "required": ["command", "schema_version", "isolation", "commands"],
        "properties": {
            "command": {"const": COMMAND},
            "schema_version": {"type": "integer"},
            "isolation": {"type": "object"},
            "commands": {"type": "array"},
        },
        "additionalProperties": True,
    },
}

_HELP_EPILOG = (
    """\
Print the command overview, or one JSON catalog with each command's name,
description, arguments, options, examples, exit codes and output schema.

The catalog is generated from the command registry, so it always covers the
commands this repo ships. Every command also accepts `--help` for its own
usage and examples.

JobGremlin runs in parallel and in isolation. It never changes Hermes, the cron
job, the allowlist, ~/.local/bin or the current career-ops checkout.

"""
    + "Exit codes:\n"
    + format_exit_codes(EXIT_CODES)
    + "\nExamples:\n"
    + format_examples(EXAMPLES)
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=COMMAND,
        description=(
            "Show the human command overview or the machine-readable catalog "
            "used by Hermes to integrate with this CLI."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_HELP_EPILOG,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the machine-readable command catalog instead of the overview",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.json:
        print(json.dumps(build_catalog(), ensure_ascii=False, indent=2))
    else:
        print(render_text(), end="")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

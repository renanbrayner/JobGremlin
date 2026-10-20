# Pin Python and checks with uv

## Context

The repo documented `python3 -m pytest`, but the default shell interpreter was
an asdf-managed Python 3.10 without pytest. Tests also inherited asdf shims while
overriding `HOME`, so the suite could fail for reasons unrelated to the code.
Ruff and mypy existed only as manual commands.

## Decision

The repo pins Python 3.14 in `.python-version`, declares test and lint tools in
the `dev` dependency group, and commits `uv.lock`. `./scripts/check` is the one
command that runs the suite, mypy and ruff. Local hooks and CI call the same
script.

## Invariants

- A fresh clone runs `uv sync --all-groups` and then `./scripts/check`.
- `scripts/check` uses `uv run --locked`; an out-of-date lock is an error, not a
  silent environment change.
- Tests resolve Python through `sys.executable` and Node through a stable system
  path, never through a developer-specific shim.
- CI runs the same script with a locked environment.

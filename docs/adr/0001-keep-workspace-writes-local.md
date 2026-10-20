# Keep workspace writes local and the upstream read-only

## Context

JobGremlin runs in parallel with the existing Hermes and career-ops setup. A
failed experiment must not change the cron, the allowlist, `~/.local/bin` or the
installed career-ops checkout. At the same time, the new flow needs the current
profile, CV bases, templates and historical data.

## Decision

The repo is the only write target. `config/`, `data/` and `output/` belong to the
workspace. The installed career-ops checkout is a read-only dependency for
inputs and build helpers.

## Invariants

- A command fails before writing when `CAREER_OPS_CONFIG`, `CAREER_OPS_DATA` or
  `CAREER_OPS_OUTPUT` resolves inside `CAREER_OPS_UPSTREAM`.
- Copied scripts are real files, never symlinks into the upstream or
  `~/.local/bin`.
- Missing personal files are read from the upstream, but generated CVs, logs,
  sessions and screenshots always land in the workspace.
- Tests use a temporary fake upstream and assert that its snapshot does not
  change.

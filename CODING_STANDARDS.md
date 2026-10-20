# Coding Standards

Read this during review, not during implementation. Mechanical rules live in
`./scripts/check`; this file records the judgement calls a reviewer should apply
to this repo.

## Configuration and paths

- Resolve workspace paths and environment values through `career_ops.paths`
  (`resolve_paths`, `load_environment`). Do not read `os.environ`, `Path.home()`
  or `$HOME` directly for a workspace path.
- New configuration follows the documented precedence: real environment,
  `config/career-ops.env`, then a safe workspace default.
- Treat `CAREER_OPS_UPSTREAM` as read-only. A write guard must run before any
  side effect, not after it.

## External effects

- Put browser/CDP access, subprocesses, screenshots and filesystem side effects
  behind a small injectable callable or protocol. The core flow must be testable
  without LinkedIn, Chromium or `grim`.
- A guard names the exact state it depends on. For CVs, read the selected
  attachment, never the profile library.
- A retry must be safe by construction. If a click or upload may already have
  happened, the result is not retryable without an explicit external check.

## Observation

- Every application stage writes one event using the schema documented in the
  README. Do not add a second event shape for a new module.
- Record evidence before returning a failure. A screenshot failure must not
  change the application outcome.
- Keep `submitted` and `verified` distinct. Only `verified` counts as success.

## Tests

- Test observable behavior through a public seam: CLI output, result values,
  session artifacts, or calls to an injected fake.
- Use the shared fixtures in `tests/conftest.py` (`workspace`, `fake_upstream`,
  `env`, `run`, shared fakes) instead of copying them into a test module.
- A regression test must reproduce the production failure, not a nearby symptom.
  The 19/10 case freezes the CV upload, not a later read.

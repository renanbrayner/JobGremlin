# Count an application only after LinkedIn confirms it

## Context

The 19/10 reference run submitted nothing because the CV upload froze the
renderer. A retry after a click is dangerous: the click may already have created
an application. A form can also reuse the PDF selected in a previous application,
so "a CV is attached" is not evidence that the tailored PDF was used.

## Decision

The submission guard checks the exact selected CV before clicking submit and
accepts only LinkedIn confirmation as success. A timeout before the click is
recoverable. A timeout after the click, or a click without confirmation, is
recorded as failed and is not automatically retried.

## Invariants

- A wrong or missing selected CV aborts before the submit click and is never
  counted as submitted.
- The expected CV is attached under the renderer deadline before the selection is
  read back.
- A pre-click timeout records evidence (with `grim` fallback), recovers the
  browser and allows at most one more attempt.
- `not_confirmed` and post-click timeouts have `retryable = False`; a later
  process must check LinkedIn before attempting the job again.
- Only `verified` increments the daily target.

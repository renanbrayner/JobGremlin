# JobGremlin

Deterministic CLI for LinkedIn applications, built in parallel with the existing
Hermes and career-ops installation.

## Language

**Workspace**:
The writable area of this repo: `config/`, `data/` and `output/`. Persistent
writes stay here.
_Avoid_: repo, project (when the read-only upstream is meant)

**Upstream**:
The installed career-ops checkout configured by `CAREER_OPS_UPSTREAM`. It is a
read-only dependency for profile, CV bases, templates, helpers and historical
data.
_Avoid_: old system, legacy checkout

**Run**:
One invocation of the daily flow, identified by `run_id`.
_Avoid_: batch, round

**Run state**:
The persisted counters for one **Run**: `data/runs/<run_id>.json`, with the
target, verified count and the outcome per job. Resuming reads it so confirmed
applications are never reapplied or counted twice.
_Avoid_: checkpoint (the queue still owns each job's state)

**Stop reason**:
Why the daily loop ended: `target_reached`, `queue_exhausted`,
`time_budget_exhausted`, `daily_limit_reached`, `run_locked` or
`unexpected_error`.
_Avoid_: error (a stop is not always a failure)

**Session**:
The observable record of one application attempt: `session.json`,
`events.jsonl` and screenshots under `output/sessions/<run_id>/`.
_Avoid_: log, trace

**Event**:
One line in `events.jsonl`, following the fixed schema in the README.
_Avoid_: log line

**Application stage**:
A named step in the application flow: `open`, `form_page`, `cv_selection`,
`review`, `submit`, `waiting` or `error`.
_Avoid_: step, phase

**Report**:
The human-readable record of one **Run**: `report.md` and `report.html` with the
funnel, one row per **Job** and links/thumbnails for the **Session** evidence.
_Avoid_: dashboard, log

**Summary**:
The compact machine-readable view of one **Run**: `summary.txt` for people and
`summary.json` for Hermes. It carries the funnel, blockers, per-job rows and
artifact paths.
_Avoid_: report (the summary is a separate consumption format)

**Retention**:
The rule that keeps the three most recent finished **Runs** and removes older
`output/sessions/<run_id>/` directories and their run state. Unfinished runs are
never removed by retention.
_Avoid_: cleanup (the policy, not the action)

**Video**:
An optional `video.mp4` recording of one daily **Run**, off by default.
_Avoid_: recording (ambiguous with a session)

**Job state**:
The explicit lifecycle of a job: `new`, `title_rejected`, `jd_fetched`,
`ineligible`, `eligible`, `cv_ready`, `applying`, `waiting_input`, `submitted`,
`verified` or `failed`.
_Avoid_: status (when the state machine is meant)

**Shortlist**:
Pool jobs that survived the title and location filters.
_Avoid_: queue (the queue may include jobs from previous days)

**Eligible**:
A shortlisted job whose structured JD profile passes the deterministic rules.
_Avoid_: match

**Selected CV**:
The exact PDF currently selected on the application form.
_Avoid_: attached CV (the profile library may contain many PDFs while only one is selected)

**CV cache**:
The workspace index of generated CVs, keyed by skill fingerprint and gated by
language, family and seniority. A hit reuses the PDF and records another origin
job; a miss generates and indexes a new one.
_Avoid_: CV library (that is the LinkedIn profile list)

**CV decision**:
The auditable hit/miss result for one job: score, threshold, chosen CV and the
reason a cached CV was rejected.
_Avoid_: match (that is the job eligibility decision)

**Renderer timeout**:
A watchdog deadline for one browser operation. When it expires before the submit
click, the browser can be recovered and the attempt retried.
_Avoid_: renderer freeze (the timeout detects the freeze; it is not the cause)

**Submitted**:
The submit click happened. This does not prove that LinkedIn accepted the
application.
_Avoid_: sent, applied

**Verified**:
LinkedIn confirmed the application. Only a verified application counts toward
the daily target.
_Avoid_: submitted, successful

**Parked form**:
The single application form left open on an unknown question, recorded in
`data/parked-form.json` with the job, the pending questions, the CDP target and
a resume token. The loop continues in another tab while it waits.
_Avoid_: pending application, queued form

**Parked form limit**:
The rule that a workspace parks at most one form. A second job that stops on an
unknown question fails with `parked_form_limit`; it never replaces the parked
form.
_Avoid_: waiting queue

**Reply**:
`career-ops-reply` validates answers, merges them into the workspace answers
file and resumes the **Parked form** on its stored target.
_Avoid_: submit (a reply resumes a form; it does not bypass the CV/submit guard)

**Command registry**:
The single list of command modules in `career_ops.catalog.REGISTRY` from which
`career-ops-help` renders both the human overview and the JSON catalog.
_Avoid_: command list (a second hand-maintained list would drift from the CLI)

**Catalog**:
The machine-readable JSON returned by `career-ops-help --json`: for each command
its name, description, arguments, options, examples, exit codes and output
schema.
_Avoid_: help (the human overview is a separate rendering)

## Relationships

- A **Run** contains one or more **Sessions**.
- A **Run** has one **Report**, one **Summary** and an optional **Video**.
- A **Session** contains many **Events**, one per **Application stage**.
- A **Job** moves through **Job states** and can be retried only while it has not
  reached a terminal verified state.
- A **Selected CV** must match the expected PDF before the submit click.
- A **Job** has one **CV decision**; a **CV cache** hit links the job to an
  existing CV as an additional origin.
- A **Submitted** application becomes **Verified** only after confirmation.
- A **Run** parks at most one **Parked form**; a **Reply** resumes it on the
  stored CDP target and never reopens the form when the tab is still alive.

## Flagged ambiguities

- "attached CV" used to mean both the profile library and the PDF selected on the
  form. Resolved: **Selected CV** is the form state; "CV library" is the list of
  PDFs in the profile.
- "submitted" used to mean both the click and LinkedIn confirmation. Resolved:
  **Submitted** is the click; **Verified** is the confirmation.

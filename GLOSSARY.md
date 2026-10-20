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

## Relationships

- A **Run** contains one or more **Sessions**.
- A **Session** contains many **Events**, one per **Application stage**.
- A **Job** moves through **Job states** and can be retried only while it has not
  reached a terminal verified state.
- A **Selected CV** must match the expected PDF before the submit click.
- A **Submitted** application becomes **Verified** only after confirmation.

## Flagged ambiguities

- "attached CV" used to mean both the profile library and the PDF selected on the
  form. Resolved: **Selected CV** is the form state; "CV library" is the list of
  PDFs in the profile.
- "submitted" used to mean both the click and LinkedIn confirmation. Resolved:
  **Submitted** is the click; **Verified** is the confirmation.

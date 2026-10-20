# 07: Loop diário até 20 verificadas

**What to build:** o sistema executa o loop diário completo, busca vagas sob demanda, processa uma por vez e para exatamente ao atingir 20 candidaturas verificadas, ao esgotar o tempo ou ao detectar limite do LinkedIn.

**Blocked by:** 05 (Fila, filtros e elegibilidade), 06 (Cache de CV e tailoring)

**Status:** done

- [x] O loop busca novos candidatos apenas quando a fila está baixa.
- [x] O loop processa uma candidatura por vez, sem paralelismo de aplicação.
- [x] O contador só incrementa após confirmação do LinkedIn.
- [x] O loop para exatamente em 20 envios verificados e não inicia uma 21ª tentativa.
- [x] O loop respeita orçamento máximo de tempo.
- [x] O loop interrompe e reporta ao detectar limite diário do LinkedIn.
- [x] Cada vaga tem no máximo duas tentativas.
- [x] A execução tem lock para impedir rodadas simultâneas.
- [x] Uma rodada interrompida pode ser retomada sem reaplicar vagas confirmadas.
- [x] Testes com adaptador fake provam 25 candidatos → exatamente 20 envios, retomada e parada por limite.

## Comments

Implementation notes:

- `career_ops.loop.DailyLoop` owns the policy; the CLI wires the real
  workspace. It processes one selection at a time, checks `target` before
  opening the next job, and stops exactly at the verified target (a 21st
  attempt never starts).
- Run state lives in `data/runs/<run_id>.json`: `verified`, `attempts`, and a
  per-job record. Resume is by `--run-id`, so verified jobs are not reapplied
  and the count continues where it stopped.
- `submitted` counts submit clicks observed by the run; `verified` counts only
  LinkedIn confirmations. A click without confirmation is reported as
  `submitted=1, verified=0`.
- The lock is a non-blocking `flock` on `data/run.lock`; a second process exits
  `3` with `failure.reason = "run_locked"` and writes no state.
- Time budget (`--max-seconds`, default 4h, `0` disables) is checked before
  each job. `max_attempts_per_job` (default `2`) retries transient failures
  through the queue; `job_closed`, `already_applied`, `no_easy_apply` and
  `daily_limit` are not retried.
- Discovery is lazy: the source is called only when the backlog is at or below
  `--queue-low-watermark` (default `5`). A discovery that adds nothing is
  remembered, but it reopens after the backlog shrinks, so a slow source is
  consulted again.
- A stale `applying` job from a crashed process becomes `failed` with
  `run_interrupted` and is never retried automatically, because the submit
  click may already have happened.
- Fake adapter scenarios now include `daily_limit` and `job_closed`; the
  real adapter detects the LinkedIn daily-limit marker. `README.md`,
  `GLOSSARY.md` and `config/career-ops.env.example` document the new flags,
  env vars and exit codes.
- Tests (`tests/test_daily_loop.py`) cover 25 candidates → exactly 20 verified
  with no 21st attempt, resume, daily-limit stop, run lock, max attempts,
  time budget, lazy discovery, discovery reopening, unconfirmed clicks, closed
  jobs and interrupted `applying` jobs. `./scripts/check` passes (218 tests,
  mypy and ruff clean).

Two-axis review (standards + spec) findings addressed:

- Distinguished `submitted` (click) from `verified` (confirmation) in the loop,
  run state, result JSON and tests.
- Made `daily_limit` non-retryable and a loop stop reason; the adapter reports
  it instead of retrying the same job.
- Fixed stale `applying` handling on resume (abandoned as `run_interrupted`).
- Reused the queue's retry reason/state instead of reconstructing them, and
  reused the session directory recorded by the queue.
- Reopened discovery after the backlog shrinks instead of treating the source
  as exhausted for the whole run.
- Corrected the README fake scenarios and exit code `6` documentation.

Accepted remainders:

- The time budget is checked between jobs, not inside a browser operation; a
  single application can overshoot the budget by its own bounded duration
  (the per-operation renderer deadline). Checking mid-operation would leave
  the session without a reliable outcome.
- Blocker maps and payload parsing helpers are duplicated between the queue
  and the loop; extracting them would widen this ticket's surface and is left
  for a later cleanup.
- Run-level payload navigation is intentionally primitive (`Mapping` +
  `isinstance` checks) to keep the loop decoupled from the adapter's concrete
  result type.

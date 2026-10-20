# 09: Formulário em espera e CLI de resposta

**What to build:** quando o formulário pedir uma resposta desconhecida, ele fica estacionado em uma aba, a vaga vira `waiting_input` e o loop continua na próxima vaga. A CLI expõe as perguntas e permite gravar respostas e retomar o formulário em uma única chamada.

**Blocked by:** 07 (Loop diário até 20 verificadas)

**Status:** done

- [x] Exit 6 marca a vaga como `waiting_input` e mantém o formulário aberto.
- [x] O loop continua na próxima vaga enquanto o formulário espera.
- [x] No máximo um formulário fica estacionado por vez.
- [x] As perguntas pendentes ficam disponíveis em JSON com vaga, empresa, opções e token de retomada.
- [x] `career-ops-reply` valida as respostas, grava no arquivo de respostas do workspace paralelo e retoma o formulário correto.
- [x] A retomada usa a aba e o target corretos, sem reabrir o formulário do zero quando a sessão continua viva.
- [x] Se a aba foi perdida, a vaga é marcada como falha recuperável, nunca como enviada.
- [x] O comando tem `--help` em texto humano.
- [x] Testes cobrem exit 6, limite de um formulário, resposta válida, resposta inválida, retomada e aba perdida.
- [x] O Hermes, o cron e a allowlist não são alterados; a CLI apenas expõe o contrato para integração futura.

## Comments

Implementation notes:

- `career_ops.parked` owns the single `data/parked-form.json` record: token,
  run, job (with company/url), questions with kind/options, CDP target, CV,
  session directory and the original target goal. A second waiting job is
  rejected with `parked_form_limit`, its tab is closed, and the event log
  records the decision; the original parked form is never replaced.
- `career_ops.cli` now attaches `waiting_input` to every run payload (including
  the crash path) and exposes `failure.pending` with the structured questions.
  `career-ops-run --job <parked job>` refuses to reopen its own parked form
  (exit 6, `waiting_input`) and points at `career-ops-reply`.
- `career-ops-reply` validates each answer against exactly one pending question
  (full text or a unique fragment), enforces radio/select options, merges the
  answers into the workspace `config/answers-hermes.json` (or
  `--answers-file`/`CAREER_OPS_ANSWERS` inside the workspace), resumes, and
  updates the queue plus run state so a verified reply counts once.
- The real adapter passes `--target-id` to `jobinfo`, `cdp` (goto/upload/eval/
  shot), `easyapply` and the screenshotter. When another form is parked, the
  next job opens a fresh tab and preloads the CV there; a resume checks that the
  stored tab still shows the job and that `easyapply` found the open form, so a
  lost or navigated tab becomes `parked_form_lost` (retryable, never sent)
  instead of a silent reopen. `scripts/cdp` gained `--target-id`; `jobinfo`
  accepts an optional target id. No Hermes/cron/allowlist changes.
- Tests in `tests/test_waiting_input.py` cover exit 6, loop continuation with a
  normal job while parked, the one-form limit (including the `waiting` event),
  valid/invalid answers, resume, re-park, lost tab, token mismatch, corrupt
  record, same-job guard and the human `--help`. `./scripts/check` passes (252
  tests, mypy and ruff clean).

Two-axis review (standards + spec) findings addressed:

- Guarded corrupt parked records at run entry and in reply; run/reply JSON
  reports `parked_form_unreadable`/`parked_form_error` instead of a traceback.
- Removed the second waiting-question wire shape (`failure.questions` strings);
  only structured `failure.pending` and `waiting_input.questions` remain.
- Recorded a `waiting` event with `parked_form_limit` before closing the extra
  tab, so session artifacts match the queue/payload.
- Target validation now checks both the CDP id and the job URL; `--target-id`
  is also applied to the CV preload and screenshot commands, not only
  `easyapply`, so a parked tab cannot be navigated by the next job.
- Submit-time waiting questions fall back to the job tab target.
- Centralized test helpers (`write_candidates`, `read_queue`, `read_run_state`,
  `write_jds`) in `tests/conftest.py`.
- Removed unused `PendingQuestion.answer_key`/`ParkedFormStore.answers_path`,
  checked `PARKED_VERSION`, extracted `_easyapply_argv`, and reused
  `cli._exit_code`.

Accepted remainders:

- A parked record corrupted while a run is already in flight is treated as "no
  parked target" for the next job (the entry guard catches the normal cases).
  The file is only written atomically by this process; external corruption
  mid-run would surface as `unexpected_error` with `parked_form_error`.
- `career-ops-reply` reuses private helpers from `career_ops.cli` (application,
  watchdog, payload, parking). Extracting a shared resume service would widen
  this ticket; the two commands remain one package and the seam is the CLI.
- The one-form limit makes the second waiting job a terminal `failed`
  (`parked_form_limit`), requeueable with `--requeue-reason`. Auto-requeueing it
  would spin until attempts are exhausted while the first form still waits.
- `_persist` updates queue and run state from the reply so the verified counter
  and report remain truthful; this is a small extension of "devolve o resultado
  em JSON" and does not touch Hermes/cron/allowlist.

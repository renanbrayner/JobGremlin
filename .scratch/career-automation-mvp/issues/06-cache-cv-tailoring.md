# 06: Cache de CV e tailoring

**What to build:** cada vaga elegível usa um CV gerado por vaga ou reutiliza um CV com match alto. O cache é indexado por competências, idioma, família e senioridade, e só reutiliza quando não falta nenhuma competência obrigatória.

**Blocked by:** 05 (Fila, filtros e elegibilidade)

**Status:** done

- [x] O perfil da vaga gera um fingerprint de competências.
- [x] O cache tem índice consultável e metadados legíveis por CV.
- [x] O reuso exige mesmo idioma, família compatível, senioridade compatível e zero must-have faltando.
- [x] O reuso exige similaridade ponderada de pelo menos 0.90, configurável.
- [x] Em cache hit, o CV existente é reutilizado e a vaga é registrada como origem adicional.
- [x] Em cache miss, um CV novo é gerado e indexado.
- [x] O CV não contém nome de empresa; a cover letter continua específica por vaga.
- [x] O relatório registra cache hit/miss, score, CV usado e motivo da decisão.
- [x] O `openai-tailor` é chamado apenas em cache miss.
- [x] Testes cobrem hit exato, alta similaridade, idioma diferente, senioridade incompatível, must-have faltando e score abaixo do threshold.

## Comments

Implementation notes:

- `data/cv-cache/index.json` is the queryable index; each
  `data/cv-cache/<cv-id>.json` is the readable per-CV metadata; PDFs live under
  `output/cv-cache/`. The CV id is
  `cv-<family>-<stack>-<language>-<seniority>-<fingerprint>`.
- The fingerprint is SHA-256/12 over the sorted required and preferred skills,
  so extraction order and duplicates do not matter.
- Gates run in order: CV file exists, language equality, family compatibility,
  seniority compatibility, no missing must-have, non-zero score, weighted score
  `>= min_score` (default 0.90). Similarity weighs required skills 3 and
  preferred skills 1. A full-stack CV may serve frontend/backend roles; the
  reverse is rejected. An undetected (`unknown`) language never reuses.
- Threshold precedence: `--cv-min-score` > `CAREER_OPS_CV_MIN_SCORE` >
  `config/cv-cache.json` > 0.90. `--cv-min-score` requires `--candidates`.
- The cache activates only in `--candidates` mode without an explicit `--cv`
  or `CAREER_OPS_CV`; an explicit CV is a manual override and is never indexed.
- Every decision is emitted as `cv_cache` in the CLI envelope and mirrored in
  the queue record detail (`detail.cv` + `detail.cv_cache`): hit/miss, score,
  threshold, CV id/path, fingerprint, considered entries, missing must-haves
  and reason. The Markdown/HTML report remains ticket 08's deliverable, which
  consumes this record.
- On a miss `CvSelector` calls the `CvTailor` adapter once and indexes the
  result; on a hit it only appends the job as an origin. `--adapter fake` uses
  `FakeCvTailor`, which writes an audit line per generation to
  `data/tailor-calls.jsonl`. `CommandCvTailor` is the only path to
  `openai-tailor.mjs`/`generate-pdf.mjs`.
- Company safety: the upstream receives a minimal report built from
  `JobProfile` (no company), the JD with the employer redacted, and the
  generated HTML is rejected (`company_name_in_cv`, non-retryable) if the full
  name or a distinctive brand token still appears. Cover letters are not cached
  or modified here; they stay per-job.
- Tests: `tests/test_cv_cache.py` (gates, similarity, index/origins,
  fingerprint), `tests/test_cv_tailoring.py` (command adapter, redaction,
  leak rejection), `tests/test_cv_cache_cli.py` (CLI miss→hit, language,
  seniority, must-have, below-threshold, manual override). `./scripts/check`
  passes: 205 tests, mypy and ruff clean.

Two-axis review (standards + spec) findings addressed:

- Fixed the family gate: a full-stack job could previously reuse a
  frontend-only CV. Added unit and CLI coverage for the direction.
- Fixed unknown-language reuse: `unknown` == `unknown` is now a miss.
- Made non-retryability live on `CvGenerationError` and propagate to both the
  queue detail and the CLI failure envelope; `jd_missing` is non-retryable.
- Company leak detection now also catches a partial brand name (`Acme Inc`
  caught in `Acme`), and redaction removes the brand token.
- Deduplicated cache JSON writes and skill-set construction.
- Moved shared CLI test helpers (`invoke`, `write_cv`, `write_jd_fixtures`)
  into `tests/conftest.py`.
- Added CLI coverage for seniority, must-have and below-threshold scenarios.

Accepted remainders:

- A malformed cache/index (`ValueError`) returns `configuration_error` without
  marking the job failed: it is a workspace-level error, and dropping the job
  would lose an otherwise eligible candidate. The job stays eligible.
- The index is authoritative; a crash between the metadata write and the index
  write can leave an unindexed metadata file. Deleting the index rebuilds from
  the per-CV files. No merge heuristic is attempted.
- Threshold configuration has three surfaces because the ticket asks for a
  configurable value, while the CLI flag keeps manual runs reproducible.
- Cover-letter generation is outside this repository slice; this change only
  guarantees the cached CV stays company-free.


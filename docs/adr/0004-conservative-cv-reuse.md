# Reuse a CV only through conservative, explainable gates

## Context

Generating a CV per application costs time and model calls, but reusing the
wrong CV is worse than generating a new one. LinkedIn reuses the PDF selected in
a previous application, so a stale or employer-specific CV can silently travel
to another company. The CV also has to stay safe to reuse: an employer name in
the document makes every later reuse a leak.

## Decision

A generated CV is indexed by the job profile under `data/cv-cache/`. A later job
reuses it only when every hard gate passes:

- identical language;
- compatible role family (`fullstack` can serve `frontend`/`backend`, not the
  reverse);
- identical seniority, or `unspecified` on either side;
- no must-have skill from the job missing from the CV.

The remaining score is the job's weighted skill coverage: a required skill
weighs three times a preferred skill. The default reuse threshold is `0.90`,
configurable in `config/cv-cache.json`, `CAREER_OPS_CV_MIN_SCORE` or
`--cv-min-score`. A miss generates one CV and indexes it. A hit appends the job
to the CV's origins.

The real generator wraps the upstream `openai-tailor.mjs` and
`generate-pdf.mjs` inside a staging root under `data/`. It receives a minimal
report assembled from the structured profile, redacts the employer name from the
JD, and rejects an HTML result that still contains it. The upstream checkout is
read-only; PDFs land in `output/cv-cache/`. Cover letters are per job and are not
stored in the cache.

## Invariants

- A cache hit never misses a must-have skill, even when the similarity score is
  high.
- The index (`data/cv-cache/index.json`) and the per-CV metadata
  (`data/cv-cache/<cv-id>.json`) are both readable and agree on the CV path,
  profile keys, fingerprint and origins.
- A generated CV contains no employer name; a leaked name fails the job instead
  of indexing the CV.
- `openai-tailor` runs only on a cache miss. A hit performs no model call.
- An explicit `--cv` is a manual override and bypasses the cache.
- On doubt, the decision is a miss: missing skills, incompatible profile or a
  score below the threshold all generate a new CV.

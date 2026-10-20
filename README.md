# JobGremlin (workspace paralelo)

CLI determinística de candidaturas, em desenvolvimento **em paralelo e isolada**
do sistema atual. O Hermes, o cron, a allowlist, `~/.local/bin` e o checkout
atual do `career-ops` não são movidos, alterados nem desligados por este repo.

Este primeiro slice entrega a base versionada e isolada: os scripts do fluxo
atual foram copiados para `scripts/`, o workspace tem configuração, dados e
outputs próprios, e a suíte pytest roda localmente.

## Garantias de isolamento

- Escritas persistentes acontecem apenas em `config/`, `data/` e `output/`
  deste repo. (O `apply-one` usa um log temporário em `$TMPDIR`, como antes.)
- O checkout instalado (`~/.local/share/career-ops`, configurável) é usado
  somente como leitura: perfil, `cv.md`, bases de CV, templates, helpers de
  build e dados históricos.
- Scripts copiados não têm caminhos `/home/<usuário>` hardcoded nem chamam
  binários de `~/.local/bin`.
- Os scripts recusam escrever dentro do upstream. Se `CAREER_OPS_DATA`,
  `CAREER_OPS_OUTPUT` ou `CAREER_OPS_CONFIG` apontarem para dentro dele, o
  comando falha antes de qualquer escrita.
- Nenhum symlink é criado em `~/.local/bin`; os scripts do repo são arquivos
  reais e executáveis.
- A suíte automatizada usa um upstream falso temporário e prova que os comandos
  não alteram seus arquivos.

## Layout

```
.
├── config/              # configuração local (pessoal, gitignored quando aplicável)
├── data/                # fila, JDs, logs e estado de execução
├── output/              # CVs e artefatos gerados
├── scripts/             # cópias isoladas dos scripts do fluxo
│   └── lib/             # contrato compartilhado de caminhos (bash/node/python)
├── src/career_ops/      # pacote Python (path contract; CLI nasce nos próximos tickets)
├── tests/               # pytest: paths, smoke dos comandos e isolamento
├── docs/                # documentação de agentes
└── .scratch/            # spec e issues do MVP
```

## Configuração

Os caminhos podem ser definidos por variáveis de ambiente ou por um arquivo
`config/career-ops.env` (copie de `config/career-ops.env.example`). Precedência:

1. variável de ambiente real;
2. `config/career-ops.env`;
3. default seguro dentro do workspace.

| Variável | Default | Papel |
| --- | --- | --- |
| `CAREER_OPS_HOME` | raiz deste repo | raiz do workspace |
| `CAREER_OPS_UPSTREAM` | `~/.local/share/career-ops` | checkout atual, **somente leitura** |
| `CAREER_OPS_CONFIG` | `$CAREER_OPS_HOME/config` | configuração própria |
| `CAREER_OPS_DATA` | `$CAREER_OPS_HOME/data` | dados e logs próprios |
| `CAREER_OPS_OUTPUT` | `$CAREER_OPS_HOME/output` | CVs e artefatos próprios |
| `CAREER_OPS_SCRIPTS` | `$CAREER_OPS_HOME/scripts` | scripts copiados |
| `CAREER_OPS_ENV_FILE` | `$CAREER_OPS_CONFIG/career-ops.env` | arquivo de override |

Configurações pessoais (por exemplo `config/profile.yml`,
`config/answers-hermes.json`, `config/cv-facts.json` e `cv.md`) são lidas do
workspace quando existem e, caso contrário, do upstream. Elas ficam fora do git
por padrão. O `cv.md`, quando copiado para o workspace, habilita o fact gate do
`generate-pdf.mjs` upstream.

## Rodando a suíte

Requer Python 3.11+ e pytest (já disponível no ambiente).

```bash
python3 -m pytest
```

Os testes cobrem:

- resolução de caminhos e recusa de escrita no upstream;
- classificação de pool, recuperação de títulos, enrich com pool ausente e
  build de CV contra um upstream falso;
- smoke de todos os entrypoints copiados (`--help`, uso inválido, `cdp-targets`
  contra um servidor CDP falso);
- garantia de que os comandos não alteram o upstream falso.

## Smoke tests manuais

Os comandos abaixo não tocam o LinkedIn. Rode a partir da raiz do repo:

```bash
# caminhos resolvidos
PYTHONPATH=src python3 -c 'from career_ops.paths import resolve_paths; print(resolve_paths())'

# os scripts executam a partir do workspace
scripts/career-ops-browser --check
scripts/cdp | head -5 || true
scripts/easyapply --help | head -5
scripts/career-ops-jd 2>&1 | head -2 || true
scripts/apply-one 2>&1 | head -2 || true
```

Fluxo atual, quando o navegador CDP já estiver autenticado:

```bash
scripts/career-ops-pool                 # grava data/pool-YYYY-MM-DD.tsv
scripts/career-ops-enrich               # grava data/jd-YYYY-MM-DD/ e -enriched.tsv
scripts/career-ops-triage --json        # classifica a shortlist
scripts/career-ops-cv --slug teste --lang pt
scripts/apply-one <job-id> output/cv-*.pdf
```

## O que foi copiado

De `~/.local/bin` para `scripts/`, com caminhos reparametrizados:

`career-ops-pool`, `career-ops-triage`, `career-ops-enrich`,
`career-ops-pool-fix-titles`, `career-ops-cv`, `career-ops-jd`,
`career-ops-browser`, `career-ops-apply-queue`, `apply-one`, `cdp`,
`cdp-targets`, `cdp-unstick`, `easyapply`, `jobinfo`, `form-dump.js` e
`jd-extract.js`.

Continuam como dependência de leitura no upstream: `build-cv-html.mjs`,
`generate-pdf.mjs`, templates, `config/profile.yml`, `cv.md`, `cv-base-*.json`
e dados históricos. O `openai-tailor` também será chamado de lá nos próximos
tickets.

Os defaults de caminho foram reparametrizados para o workspace. Em particular,
`career-ops-apply-queue` prefere o CV mais recente em `output/` e, na ausência
dele, o último CV do fluxo atual no upstream. `career-ops-pool`,
`career-ops-browser`, `cdp` e `cdp-targets` honram `CDP_PORT`.

## Sessões observáveis

Cada execução de aplicação grava uma sessão em
`output/sessions/<run_id>/`:

```
output/sessions/<run_id>/
├── session.json         # run_id, status, created_at, finished_at, job
├── events.jsonl         # um evento JSON por linha, append-only
└── screenshots/         # evidência visual, nomes estáveis por etapa
```

Eventos seguem este schema fixo:

```json
{
  "ts": "2026-10-19T12:00:00.320000+00:00",
  "run_id": "2026-10-19-morning",
  "job_id": "4411222",
  "stage": "form_page",
  "page": 1,
  "status": "ok",
  "duration_ms": 320,
  "artifact": "screenshots/001-form-page-1.png",
  "detail": null
}
```

As etapas registradas pelo adaptador são `open`, `form_page` (com `page`),
`cv_selection`, `review`, `submit`, `waiting` e `error`. Screenshots são
nomeadas pela etapa (`open.png`, `form-page-1.png`, `review.png`, ...); uma
segunda captura bem-sucedida da mesma etapa recebe sufixo (`error-2.png`), sem
renomear as anteriores. Cada evento aponta para o arquivo correspondente em
`artifact`.

O rastreamento é exposto por `career_ops.session.SessionRecorder`; a captura
fica atrás de um callable injetável (`career_ops.capture`). Em timeout do CDP,
o recorder tenta automaticamente uma captura do sistema com `grim` antes de
marcar o evento como falho; quando o fallback funciona, o evento mantém o
status da etapa e registra `detail.source = "fallback"`. Uma aplicação que
levanta exceção (ou chama `SessionRecorder.fail`) ainda fecha a sessão com
`status: failed`, um evento `error` e a screenshot de erro (ou a captura via
`grim` quando o renderer está travado), então a sessão continua inspecionável.

## Navegador em paralelo

Por padrão os scripts usam o mesmo perfil e a mesma porta CDP do sistema atual
para reaproveitar o login. Para uma rodada realmente simultânea, use um perfil e
uma porta separados:

```bash
LINKEDIN_PROFILE_DIR=~/.local/share/browser-profiles/linkedin-parallel \
CDP_PORT=9334 scripts/career-ops-browser
```

## Limitações conhecidas deste slice

- A CLI determinística (`career-ops-run`, `career-ops-reply`,
  `career-ops-status`, `career-ops-report`, `career-ops-help`) ainda não existe;
  ela é construída nos próximos tickets.
- O build de CV delega aos helpers do upstream. O HTML/PDF e o índice de PDFs
  são gravados em `output/` e `data/`; para o fact gate completo, copie
  `cv.md`/`config/profile.yml` para o workspace quando quiser uma visão local.
- A integração com Hermes, Telegram, cron e allowlist está fora deste escopo.

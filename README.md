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
│   ├── check            # pytest + mypy + ruff
│   └── lib/             # contrato compartilhado de caminhos (bash/node/python)
├── src/career_ops/      # pacote Python (contratos reutilizáveis; CLI nos próximos tickets)
├── tests/               # pytest: paths, smoke dos comandos e isolamento
├── docs/adr/            # decisões de arquitetura
├── docs/agents/         # convenções para agentes
├── GLOSSARY.md          # vocabulário do domínio
├── CODING_STANDARDS.md  # critérios de review
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
| `CAREER_OPS_RENDERER_TIMEOUT_SECONDS` | `30` | prazo rígido por operação do navegador |
| `CAREER_OPS_APPLY_TIMEOUT_SECONDS` | `420` | prazo de um `easyapply` completo por vaga |
| `CAREER_OPS_CV_MIN_SCORE` | `0.90` | similaridade mínima para reutilizar um CV do cache |
| `CAREER_OPS_ENV_FILE` | `$CAREER_OPS_CONFIG/career-ops.env` | arquivo de override |

Configurações pessoais (por exemplo `config/profile.yml`,
`config/answers-hermes.json`, `config/cv-facts.json` e `cv.md`) são lidas do
workspace quando existem e, caso contrário, do upstream. Elas ficam fora do git
por padrão. O `cv.md`, quando copiado para o workspace, habilita o fact gate do
`generate-pdf.mjs` upstream.

## Desenvolvimento

Requer `uv` e o Python fixado em `.python-version` (3.14; o pacote declara
`>=3.11`). O repo declara as ferramentas de desenvolvimento em
`pyproject.toml`, com versões travadas em `uv.lock`.

```bash
uv sync --all-groups
git config core.hooksPath .githooks   # uma vez; instala o pre-commit local
./scripts/check
```

O hook roda o mesmo `./scripts/check` antes de cada commit. O CI
(`.github/workflows/check.yml`) usa o mesmo comando com o lock travado.

## Rodando a suíte

`./scripts/check` roda pytest, mypy e ruff. Para rodar apenas a suíte:

```bash
uv run pytest
uv run pytest tests/test_submission.py
```

Os testes cobrem:

- resolução de caminhos e recusa de escrita no upstream;
- classificação de pool, recuperação de títulos, enrich com pool ausente e
  build de CV contra um upstream falso;
- smoke de todos os entrypoints copiados (`--help`, uso inválido, `cdp-targets`
  contra um servidor CDP falso);
- `career-ops-run` de ponta a ponta com o adaptador fake (sucesso, não
  confirmado, CV errado, timeout e CV ausente), incluindo o JSON e a sessão;
- fila de candidatos, filtros de título e localização, perfil estruturado da JD,
  elegibilidade determinística, dedupe e JD ausente;
- cache de CV: hit exato, alta similaridade, idioma, família, senioridade,
  must-have faltando, score abaixo do threshold, geração no miss, origem
  adicional no hit e tailoring chamado só no miss;
- o adaptador real embrulha `jobinfo`/`easyapply`/`cdp` sem alterar os scripts;
- garantia de que os comandos não alteram o upstream falso.

## Smoke tests manuais

Os comandos abaixo não tocam o LinkedIn. Rode a partir da raiz do repo:

```bash
# caminhos resolvidos
uv run python -c 'from career_ops.paths import resolve_paths; print(resolve_paths())'

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

O recorder suporta as etapas `open`, `form_page` (com `page`), `cv_selection`,
`review`, `submit`, `waiting` e `error`. O `career-ops-run` registra hoje
`open`, `cv_selection`, `review`, `submit` e `error`; as capturas por página do
formulário (`form_page`) ainda dependem de instrumentar o `easyapply` copiado.
Screenshots são nomeadas pela etapa (`open.png`, `form-page-1.png`,
`review.png`, ...); uma segunda captura bem-sucedida da mesma etapa recebe
sufixo (`error-2.png`), sem renomear as anteriores. Cada evento aponta para o
arquivo correspondente em `artifact`.

O rastreamento é exposto por `career_ops.session.SessionRecorder`; a captura
fica atrás de um callable injetável (`career_ops.capture`). Em timeout do CDP,
o recorder tenta automaticamente uma captura do sistema com `grim` antes de
marcar o evento como falho; quando o fallback funciona, o evento mantém o
status da etapa e registra `detail.source = "fallback"`. Uma aplicação que
levanta exceção (ou chama `SessionRecorder.fail`) ainda fecha a sessão com
`status: failed`, um evento `error` e a screenshot de erro (ou a captura via
`grim` quando o renderer está travado), então a sessão continua inspecionável.

## Anexo de CV e renderer travado

O envio é protegido por três peças em `src/career_ops/`:

- `cv_attachment.verify_cv_attachment(expected, selected)` compara o nome do
  PDF esperado com **apenas o CV selecionado** no formulário (não a biblioteca
  inteira), sem aceitar fallback. CV errado ou ausente vira `WrongCvAttached` e
  a candidatura **não** é enviada.
- `renderer.RendererWatchdog` dá um prazo rígido a cada operação do navegador,
  configurável por `CAREER_OPS_RENDERER_TIMEOUT_SECONDS` (padrão 30s), tanto
  pelo ambiente quanto por `config/career-ops.env`. Ao estourar, levanta
  `RendererTimeout` com `retryable = True`.
  `CommandRecovery`/`cdp_unstick_recovery` executam o `cdp-unstick` copiado e
  `RecoverableBrowser` descarta o socket antigo e reconecta no **mesmo target**
  antes de uma nova tentativa, sem destruir uma aba em espera.
- `submission.SubmissionGuard` orquestra a ordem segura: anexa o CV esperado
  sob deadline, relê somente o CV selecionado, captura `cv_selection` e
  `review`, clica em enviar, captura `submit` e só considera a vaga enviada
  quando o LinkedIn confirma (`verify()`). Um timeout antes do clique registra
  erro (com fallback para `grim`), recupera o navegador e tenta de novo, no
  máximo duas vezes. Um timeout depois do clique, ou um envio sem confirmação,
  não é marcado como retryable: o LinkedIn pode já ter registrado a candidatura.

O adaptador real do ticket #04 usa esse núcleo; os scripts copiados
(`easyapply`, `apply-one`) não foram alterados neste slice.

```bash
CAREER_OPS_RENDERER_TIMEOUT_SECONDS=20 uv run pytest tests/test_submission.py
```

## Aplicar uma vaga (`career-ops-run`)

`scripts/career-ops-run --job <id>` executa uma vaga explícita de ponta a ponta
e devolve **um objeto JSON** em stdout. Ele só retorna sucesso (exit `0`) quando
o `jobinfo` confirma que o LinkedIn registrou a candidatura; um clique sem
confirmação é `status: "failed"` com motivo `not_confirmed`.

```bash
# CV explícito
scripts/career-ops-run --job 4411222 --cv output/cv-renan-react-2026-10-19.pdf

# sem --cv: usa $CAREER_OPS_CV ou o cv-*.pdf mais recente de output/
scripts/career-ops-run --job 4411222

# ensaio sem navegador, com o adaptador fake
scripts/career-ops-run --job 4411222 --cv output/cv-renan-react.pdf \
  --adapter fake --fake-scenario success
```

O adaptador fake (`--adapter fake`) aceita cinco cenários: `success`,
`failure` (envio sem confirmação), `wrong_cv` (PDF anterior selecionado),
`timeout` (upload do CV congela o renderer) e `waiting_input` (formulário para
numa pergunta e fica aberto, exit `6`). Ele executa o mesmo orquestrador e grava
uma sessão real em `output/sessions/<run_id>/`, sem tocar no LinkedIn.

Saída (resumida):

```json
{
  "command": "career-ops-run",
  "status": "verified",
  "run_id": "2026-10-19T12-00-00Z",
  "job": {"id": "4411222", "title": "...", "company": "...", "applied": false},
  "result": {"submitted": true, "verified": true, "reason": "verified",
             "attempts": 1, "expected_cv": "cv-....pdf",
             "selected_cvs": ["cv-....pdf"], "retryable": false},
  "failure": null,
  "artifacts": {
    "session_dir": ".../output/sessions/2026-10-19T12-00-00Z",
    "session_json": ".../session.json",
    "events": ".../events.jsonl",
    "screenshots": [".../screenshots/open.png", ".../screenshots/submit.png"]
  },
  "cv": ".../output/cv-....pdf"
}
```

Exit codes: `0` verificado, `1` não verificado, `2` argumentos inválidos, `3`
CV/answers/configuração ausente e `6` formulário aguardando resposta (a aba fica
aberta). `--help` imprime o texto humano, o schema e os exit codes.

O adaptador real embrulha os scripts copiados sem alterá-los:

1. `jobinfo` abre a vaga e informa `applied`, `closed` e `easy`;
2. `cdp` pré-carrega o PDF em `/jobs/application-settings/` (sem abrir o file
   picker nativo) e escolhe o rádio do CV esperado quando a tela oferece um;
3. `easyapply --cv-library-only` preenche o formulário e para na revisão;
4. o guard do ticket #03 relê **somente o CV selecionado**, tira as screenshots
   e clica em enviar;
5. `easyapply --resume --submit` envia e `jobinfo` confirma.

O `easyapply` copiado não foi alterado e mantém seus próprios fallbacks
internos. O guard deste repo é a barreira final: se o CV selecionado não for o
PDF esperado, o clique de envio não acontece.

Cada chamada externa tem deadline; um timeout de subprocesso vira
`RendererTimeout`, registra evidência (com fallback `grim`) e aciona o
`cdp-unstick`. `CAREER_OPS_APPLY_TIMEOUT_SECONDS` limita um `easyapply` completo.

### Smoke test manual do adaptador real

O teste automatizado nunca usa o LinkedIn. Para validar o adaptador real, com um
navegador CDP já autenticado:

```bash
# 1. perfil/porta paralelos (o login atual continua intocado)
export LINKEDIN_PROFILE_DIR=~/.local/share/browser-profiles/linkedin-parallel
export CDP_PORT=9334
scripts/career-ops-browser

# 2. CV de teste (o gerador por vaga chega no ticket #06)
scripts/career-ops-cv --slug smoke --lang pt

# 3. uma única vaga, observando o JSON e a sessão
scripts/career-ops-run --job <job-id> --cv output/cv-smoke-*.pdf
ls output/sessions/<run_id>/
```

O `CDP_PORT=9334` exportado é essencial: sem ele, `scripts/cdp` usaria a porta
do navegador do sistema atual (9333) e a rodada deixaria de ser paralela.

O smoke test só é considerado bem-sucedido com `status: "verified"`; qualquer
outro resultado deve ser diagnosticado pelas screenshots e pelo `events.jsonl`.

## Fila, filtros e elegibilidade (`--candidates`)

`career-ops-run --candidates <arquivo>` aceita uma lista de candidatos, mantém
uma fila persistente em `data/queue.json` e aplica **a primeira vaga elegível**.
O formato pode ser JSON (array ou `{"candidates": [...]}`) ou TSV no formato do
`career-ops-pool`/`career-ops-enrich` (o TSV enriquecido traz localização e
modelo de trabalho; o pool puro só tem título e tende a ser rejeitado pelo
filtro de localização).

```bash
# JSON: id, title, company, location, workplace, is_remote, url
scripts/career-ops-run --candidates data/candidates.json \
  --cv output/cv-renan-react.pdf

# ensaio offline: as JDs vêm de data/jd-fixtures/<job-id>.txt
scripts/career-ops-run --candidates data/candidates.json \
  --jd-dir data/jd-fixtures --cv output/cv-renan-react.pdf \
  --adapter fake --run-id queue-demo
```

A fila guarda um registro por `id` e nunca repete um id que já está em estado
terminal (`title_rejected`, `ineligible`, `failed`, `waiting_input`, `submitted`,
`verified`, `applying`) sem um motivo explícito.
Duplicatas dentro da mesma lista e em execuções seguintes voltam com
`status: "skipped"` e o motivo (`duplicate`, `blocked:<estado>`,
`already_applied`, `job_closed`, `discarded`). Se um id já na fila aparecer
depois como aplicado, fechado ou descartado, ele é movido para `ineligible` com
o motivo correspondente. Para retomar uma vaga terminal, passe
`--requeue-reason "<motivo>"`: ela volta para `new`, o motivo fica no histórico
da fila e a vaga é reavaliada. Estados usados neste slice: `new`,
`title_rejected`, `jd_fetched`, `eligible`, `ineligible`, `applying`,
`waiting_input`, `failed`, `submitted`, `verified`.

O campo `history` do `queue.json` é o rastro de auditoria da fila (enfileirado,
rejeitado, reenfileirado, tentativa e resultado). Ele é separado do
`events.jsonl` da sessão, que segue o schema de estágios de aplicação.

### Filtros rápidos (antes da JD)

- **Título**: rejeita estágio (`title_internship`), júnior (`title_junior`), QA
  (`title_qa`), segurança (`title_security`), infraestrutura/DevOps
  (`title_infra`), liderança/arquitetura/gestão (`title_leadership`) e funções
  fora de desenvolvimento (`title_non_dev`). Título vazio vira `title_missing`.
- **Localização**: aceita remoto em qualquer lugar (com `reason: null` e
  `detail.workplace: "remote"`) ou presencial/híbrido na região de Recife (com
  `reason: null` e `detail.workplace` `"on_site"` ou `"hybrid"`). Rejeita
  híbrido fora da região (`location_hybrid`), presencial fora da região
  (`location_outside_region`) e localização ausente (`location_missing`).
  Como a máquina de estados explícita não tem um estado de localização, a
  rejeição fica em `ineligible` com `detail.filter: "location"` e o motivo
  específico do filtro.
- Só depois dos dois filtros a JD é buscada. A busca real usa o endpoint guest
  do LinkedIn; `--jd-dir` lê `<job-id>.txt` para rodadas offline. JD ausente
  vira `failed` com `reason: "jd_missing"` e a fila continua na próxima vaga.

### Perfil estruturado e elegibilidade

Cada JD baixada vira um `JobProfile` determinístico com `language` (`pt`, `en`
ou `unknown`), `family` (`frontend`, `backend`, `fullstack`, `mobile`, `data`,
`devops`, `qa`, `other`), `seniority` (`intern`, `junior`, `mid`, `senior`,
`lead`, `unspecified`), `required_skills` e `preferred_skills`. As skills são
extraídas de seções de requisitos/diferenciais por um vocabulário fixo; nenhum
LLM participa.

As regras de elegibilidade são configuráveis em `config/eligibility.json`
(opcional; na ausência do arquivo valem os defaults):

```json
{
  "languages": ["pt", "en"],
  "families": ["frontend", "backend", "fullstack", "mobile"],
  "seniorities": ["mid", "senior", "unspecified"]
}
```

A decisão é auditável: `reason` é `eligible`, `language_unsupported`,
`family_not_targeted` ou `seniority_not_targeted`, e `checks` registra todas as
regras avaliadas. A vaga elegível é encaminhada ao fluxo de aplicação; o
registro passa por `applying` e termina em `verified`, `waiting_input`,
`ineligible` ou `failed`. As demais sobreviventes ficam em `new`, sem JD
baixada, para a próxima execução ou para o loop diário do ticket #07.

O JSON de saída em modo fila acrescenta:

```json
"queue": {
  "path": ".../data/queue.json",
  "selection": {"id": "4411222", "profile": {...}, "decision": {...}},
  "ingested": [{"id": "4411222", "status": "enqueued", "reason": null}],
  "record": {"id": "4411222", "state": "verified", ...},
  "records": [{"id": "4411222", "state": "verified", ...}]
}
```

Se nenhuma vaga passar pelos filtros e pela elegibilidade, o comando devolve
exit `1` com `failure.reason = "no_eligible_job"` e a fila completa no JSON.

## Cache e geração de CV

No modo `--candidates`, quando nenhum `--cv` é passado (e `CAREER_OPS_CV` não
está definido), cada vaga elegível reutiliza um CV compatível ou gera um novo.
Cada CV gerado recebe um identificador legível com família, stack, idioma,
senioridade e fingerprint de competências:

```
output/cv-cache/cv-frontend-react-typescript-pt-senior-8f14e45fceea.pdf
data/cv-cache/index.json                     # índice consultável
data/cv-cache/cv-frontend-react-typescript-pt-senior-8f14e45fceea.json
```

O índice guarda path, idioma, família, senioridade, skills e fingerprint; o
arquivo por CV acrescenta `created_at`, `updated_at` e as vagas de origem. Um
cache hit reutiliza o PDF existente e adiciona a vaga às origens; um miss gera
um PDF novo e o indexa. O `openai-tailor` só é chamado no miss.

O reuso é conservador e exige **todos** os gates:

- mesmo idioma;
- família compatível (`fullstack` serve `frontend`/`backend`; o contrário não);
- mesma senioridade (ou `unspecified` de um dos lados);
- nenhuma skill obrigatória faltando;
- similaridade ponderada `>= 0.90` (skill obrigatória pesa 3, preferida pesa 1).

O threshold é configurável em `config/cv-cache.json`, por
`CAREER_OPS_CV_MIN_SCORE` ou por `--cv-min-score`:

```json
{"min_score": 0.95}
```

Cada execução de fila acrescenta ao JSON:

```json
"cv_cache": {
  "hit": false,
  "reason": "cache_miss",
  "miss_reason": "score_below_threshold",
  "score": 0.857,
  "threshold": 0.9,
  "cv_id": "cv-frontend-react-typescript-pt-senior-8f14e45fceea",
  "cv": ".../output/cv-cache/cv-...pdf",
  "fingerprint": "8f14e45fceea",
  "considered": 2,
  "missing_required": []
}
```

`miss_reason` é um dos `cache_empty`, `language_mismatch`,
`family_incompatible`, `seniority_incompatible`, `must_have_missing`,
`score_below_threshold`, `no_skills` ou `cv_file_missing`. A decisão também é
gravada em `queue.json` (`record.detail.cv_cache` e `record.detail.cv`) para o
relatório do ticket #08.

Um `--cv` explícito continua sendo override manual: ele ignora o cache e não
chama o tailor. O CV gerado nunca contém o nome da empresa; o relatório enviado
ao tailor é montado só do perfil estruturado, a JD é redigida e um HTML que
ainda contenha o nome da empresa é rejeitado. A cover letter permanece
específica por vaga e não entra no cache.

Com `--adapter fake`, a geração usa um `FakeCvTailor` local: ele grava um PDF de
placeholder e uma linha por chamada em `data/tailor-calls.jsonl`, o que permite
provar em teste que o tailor só rodou no miss. O tailor real fica atrás de
`career_ops.cv_tailoring.CommandCvTailor` e escreve em um staging root sob
`data/cv-cache/work/`, sem tocar no checkout upstream.

## Navegador em paralelo

Por padrão os scripts usam o mesmo perfil e a mesma porta CDP do sistema atual
para reaproveitar o login. Para uma rodada realmente simultânea, use um perfil e
uma porta separados:

```bash
LINKEDIN_PROFILE_DIR=~/.local/share/browser-profiles/linkedin-parallel \
CDP_PORT=9334 scripts/career-ops-browser
```

## Limitações conhecidas deste slice

- `career-ops-run` já aplica **uma** vaga explícita ou a primeira vaga elegível
  de uma lista persistente, com cache/geração de CV no modo fila. O loop diário
  com meta de 20, `career-ops-reply`, `career-ops-status`,
  `career-ops-report` e `career-ops-help --json` ainda são construídos nos
  próximos tickets.
- O build de CV delega aos helpers do upstream (`openai-tailor.mjs` e
  `generate-pdf.mjs`), copiando `cv.md`/`config/profile.yml` para um staging root
  do workspace. O tailor real é validado por testes com runner injetado e pelo
  smoke manual; a suíte automatizada nunca chama o modelo.
- A integração com Hermes, Telegram, cron e allowlist está fora deste escopo.

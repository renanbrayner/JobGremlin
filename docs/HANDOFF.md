# Handoff — JobGremlin para integração com o Hermes

Status: **MVP validado em paralelo; integração com Hermes, Telegram, cron e
allowlist ainda é responsabilidade do Renan.** O sistema atual não foi movido,
alterado nem desligado.

Este documento é o pacote de entrega para integrar a CLI determinística ao
Hermes. A fonte autoritativa do contrato é sempre `career-ops-help --json`;
`docs/handoff/help-catalog.json` é um snapshot gerado do mesmo registro de
comandos e conferido pela suíte.

## O que está pronto

- `career-ops-run` aplica uma vaga explícita ou executa o loop diário por vaga,
  com fila persistente, filtros, elegibilidade, cache de CV, lock, retomada e
  meta de verificadas.
- `career-ops-reply` responde ao único formulário estacionado e o retoma na aba
  original.
- `career-ops-report` regenera relatório, resumos e retenção de uma rodada.
- `career-ops-help` mostra a visão humana; `--json` publica o catálogo que o
  Hermes deve consumir.
- Cada vaga tem sessão observável (`session.json`, `events.jsonl`,
  screenshots) e cada rodada tem `report.md`, `report.html`, `summary.txt` e
  `summary.json`.
- O ensaio paralelo executou 1, 3 e 20 vagas com o adaptador fake e fez
  fingerprint antes/depois de Hermes, cron, allowlist, `~/.local/bin` e do
  checkout atual do career-ops. Os caminhos existentes permaneceram idênticos;
  os ausentes neste ambiente foram registrados como ausentes antes e depois.
  Veja [`docs/rehearsals/2026-10-20.md`](rehearsals/2026-10-20.md) e o JSON
  `docs/rehearsals/2026-10-20.json`.

## Descobrindo a CLI (`career-ops-help --json`)

```bash
scripts/career-ops-help
scripts/career-ops-help --json
scripts/career-ops-help --help
```

O catálogo JSON tem este envelope:

| Campo | Conteúdo |
| --- | --- |
| `command` | `"career-ops-help"` |
| `schema_version` | `1` |
| `isolation` | resumo do isolamento, caminhos de escrita e lista do que não é alterado |
| `commands` | um item por comando registrado |

Cada item de `commands` traz `name`, `summary`, `description`, `usage`,
`arguments`, `options`, `examples`, `exit_codes` e `output`. O campo `output`
contém o formato e o schema JSON da saída daquele comando. O schema do próprio
catálogo está em
[`docs/schema/help-catalog.schema.json`](schema/help-catalog.schema.json); o
snapshot legível está em
[`docs/handoff/help-catalog.json`](handoff/help-catalog.json).

Regere o snapshot depois de mudar qualquer comando:

```bash
scripts/career-ops-help --json > docs/handoff/help-catalog.json
```

## Comandos e exit codes

Todos os comandos aceitam `--help` com uso, argumentos, opções, exit codes,
exemplos e, quando aplicável, o schema de saída.

### `career-ops-run`

Aplica uma vaga (`--job <id>`) ou executa o loop diário (`--candidates
<arquivo>`) com meta (`--target N`). Em modo fila, sem `--cv`, o CV é
reutilizado do cache ou gerado por vaga. O contador só avança quando o
`jobinfo` confirma o envio; `submitted` registra o clique e `verified` registra
a confirmação do LinkedIn.

| Exit code | Significado |
| --- | --- |
| 0 | LinkedIn confirmou a aplicação e a meta de verificadas foi atingida |
| 1 | meta não atingida (fila esgotada, orçamento de tempo, limite diário ou falha na última vaga), inclusive sem vaga elegível |
| 2 | argumentos inválidos ou arquivo de candidatos inválido |
| 3 | CV/answers/candidatos/fonte de JD ausente, configuração inválida ou outra rodada segurando `data/run.lock` |
| 6 | fila esgotada com um formulário aguardando resposta; a aba fica aberta e deve ser respondida com `career-ops-reply` |

O `--help` do comando documenta todos os argumentos, incluindo `--target`,
`--max-seconds`, `--max-attempts`, `--queue-low-watermark`, `--cv-min-score`,
`--run-id`, `--video`, `--adapter` e `--fake-scenario`.

### `career-ops-reply`

Valida as respostas, grava no arquivo de respostas do workspace e retoma a aba
estacionada sem reabrir o formulário.

| Exit code | Significado |
| --- | --- |
| 0 | LinkedIn confirmou a aplicação retomada |
| 1 | o formulário retomou, mas a aplicação falhou ou não foi confirmada |
| 2 | argumento inválido ou resposta que não corresponde a uma pergunta pendente |
| 3 | sem formulário estacionado, token/run/vaga divergentes, CV perdido ou arquivo de respostas não gravável |
| 6 | o formulário retomado parou em outra pergunta e continua estacionado |

Argumentos principais: `--run-id`, `--job`, `--token`, `--answer
"PERGUNTA=RESPOSTA"` (repetível), `--answers`, `--answers-file`, `--adapter`,
`--fake-scenario`. Use `career-ops-reply --help` para o texto completo.

### `career-ops-report`

Regenera os quatro artefatos de uma rodada a partir do estado persistido e
aplica a retenção.

| Exit code | Significado |
| --- | --- |
| 0 | relatórios gerados |
| 1 | a rodada pedida não existe ou está ilegível |
| 2 | argumentos inválidos |
| 3 | configuração do workspace inválida ou falha de retenção |

Argumentos principais: `--run-id`, `--keep`, `--no-prune`, `--json`, `--help`.
O modo humano imprime o resumo curto; `--json` imprime o funil, as linhas por
vaga, os caminhos dos artefatos e as rodadas removidas.

### `career-ops-help`

| Exit code | Significado |
| --- | --- |
| 0 | a visão humana ou o catálogo foi impresso |
| 2 | argumentos inválidos |

Argumentos principais: `--json`, `--help`.

## Formato de saída

O `career-ops-run` imprime sempre **um objeto JSON** em stdout. Os campos
principais são:

| Campo | Conteúdo |
| --- | --- |
| `status` | `verified` ou `failed` |
| `submitted` | cliques de envio, incluindo um clique não confirmado |
| `target` | meta de verificadas da rodada |
| `verified` | confirmações do LinkedIn; apenas estas contam para a meta |
| `waiting` | vagas aguardando resposta |
| `run_id` | identificador da rodada e do diretório de sessão |
| `job` | vaga processada (`id`, `title`, `company`, `applied`, ...) |
| `result` | resultado da última tentativa (`submitted`, `verified`, `reason`, `attempts`, ...) |
| `failure` | `null` ou `{reason, message, retryable}` |
| `artifacts` | `session_dir`, `session_json`, `events` e lista de `screenshots` |
| `cv` | PDF usado na última aplicação |
| `waiting_input` | `null` ou o formulário estacionado com token, vaga, target e perguntas |
| `report` | caminhos de `report.md`, `report.html`, `summary.txt` e `summary.json` |
| `report_error` | `null` ou o motivo de uma falha ao gerar o relatório |
| `summary` | funil, bloqueios e status da rodada |
| `queue` | fila persistida, seleção, registros e histórico (modo `--candidates`) |
| `applications` | tentativas da rodada (modo `--candidates`) |

O schema completo de cada comando está em `career-ops-help --json` e em
`docs/handoff/help-catalog.json`. O `career-ops-reply` usa o mesmo envelope e
acrescenta `answers` (`path` e perguntas gravadas). O `career-ops-report --json`
devolve `summary`, `jobs`, `artifacts` e `retention`.

Formato do formulário estacionado:

```json
"waiting_input": {
  "token": "a1b2c3d4e5f6a7b8",
  "run_id": "daily-2026-10-20",
  "job": {"id": "4411222", "company": "Acme", "title": "React Engineer"},
  "target": "CDP-TARGET-ID",
  "target_goal": 20,
  "questions": [
    {"text": "Are you authorized to work?", "kind": "radio",
     "options": ["Yes", "No"]}
  ]
}
```

## Artefatos e caminhos

Tudo abaixo fica dentro do workspace (`CAREER_OPS_HOME`, por padrão este repo).
A raiz de cada rodada é `output/sessions/<run_id>/`:

```
config/
  answers-hermes.json          # respostas gravadas por career-ops-reply
  eligibility.json             # opcional; regras determinísticas de elegibilidade
  cv-cache.json                # opcional; threshold de reuso do CV

data/
  queue.json                   # fila persistente e histórico por vaga
  run.lock                     # lock de execução (flock não bloqueante)
  runs/<run_id>.json           # contadores, meta e resultado por vaga
  parked-form.json             # no máximo um formulário estacionado
  cv-cache/index.json          # índice consultável de CVs
  cv-cache/<cv-id>.json        # metadados e vagas de origem de um CV

output/
  cv-cache/<cv-id>.pdf         # PDFs gerados/reutilizados
  sessions/<run_id>/
    report.md                  # funil e uma linha por vaga
    report.html                # o mesmo relatório com thumbnails
    summary.txt                # resumo curto para pessoas
    summary.json               # resumo máquina para o Hermes
    video.mp4                  # opcional, desligado por padrão
    <job-id>/
      session.json
      events.jsonl             # um evento JSON por linha
      screenshots/open.png
      screenshots/cv-selection.png
      screenshots/review.png
      screenshots/submit.png
      screenshots/error*.png   # quando houver falha
```

Cada tentativa tem seu próprio subdiretório; a segunda tentativa da mesma vaga
vira `<job-id>-2/`. A retenção padrão mantém as três últimas rodadas completas
(`CAREER_OPS_RETENTION_RUNS=3`); rodadas em andamento nunca são removidas.

O schema dos eventos por linha está documentado no
[`README.md`](../README.md#sessões-observáveis). O resumo máquina
`summary.json` é o arquivo que o Hermes deve ler quando quiser o funil, os
bloqueios, as linhas por vaga e os caminhos sem abrir o relatório HTML.

## O que ainda depende do Hermes

O CLI não configura nem altera o Hermes, o cron ou a allowlist. A integração
que falta é:

1. **Agendamento**: o cron do Hermes deve chamar
   `scripts/career-ops-run --candidates ... --target 20 --max-seconds 14400
   --run-id daily-<data>` e ler o JSON de stdout.
2. **Allowlist**: se o executor do Hermes restringe comandos, libere apenas os
   quatro scripts de `scripts/` e os argumentos necessários. A allowlist real
   não é editada por este repo.
3. **Ponte de perguntas**: quando `waiting_input` não for `null`, o Hermes deve
   encaminhar as perguntas ao Telegram e chamar `career-ops-reply` com
   `--run-id`, `--job`, `--token` e `--answer`. O CLI não implementa Telegram
   nem a ponte.
4. **Contagem**: use `verified`, nunca `submitted`, para a meta diária.
5. **Execução em paralelo**: use um perfil de navegador e uma porta CDP
   separados (`LINKEDIN_PROFILE_DIR`, `CDP_PORT=9334`). O login atual continua
   intocado; dois processos não podem compartilhar a mesma porta.
6. **Cutover do cron**: manter o job atual enquanto o novo fluxo não tiver um
   smoke real bem-sucedido. O desligamento do job antigo é decisão do Renan.
7. **Status da rodada**: `career-ops-status` ainda não existe. Até lá, use o
   JSON de `career-ops-run`, `data/runs/<run_id>.json`, `summary.json` ou
   `career-ops-report --json`.

## Limitações conhecidas

- `career-ops-status` ainda não foi construído; faz parte de um ticket próprio.
- O ensaio de 1/3/20 vagas usa o adaptador fake. Ele valida orquestração,
  decisões, relatório, artefatos e isolamento, mas **não** valida o LinkedIn,
  upload real, CAPTCHA ou comportamento do renderer.
- O adaptador real exige um navegador CDP autenticado e é validado por smoke
  manual; a suíte automatizada nunca usa LinkedIn real.
- O `easyapply` copiado ainda não captura screenshots por página do formulário
  (`form_page`); as etapas `open`, `cv_selection`, `review`, `submit` e `error`
  já são registradas pelo guard.
- Só existe **um formulário estacionado por workspace**. Uma segunda vaga que
  pare em pergunta termina com `parked_form_limit` e não substitui a primeira.
- A geração real de CV depende dos helpers do upstream (`openai-tailor.mjs`,
  `generate-pdf.mjs`), de `cv.md` e de `config/profile.yml`; o ensaio usa o
  `FakeCvTailor`.
- Vídeo é opcional e depende de uma ferramenta de captura disponível; falha de
  vídeo nunca muda o resultado da rodada.
- O sistema é single-user e não tem dashboard/servidor em tempo real.
- Não há follow-up automático de candidaturas, entrevistas ou mensagens.
- Não há suporte a fontes de vagas além do LinkedIn.

## Isolamento e verificação final

O ensaio faz um fingerprint **antes e depois** das três rodadas e compara:

- `~/.hermes`;
- `~/.hermes/allowlist.json` (ou `HERMES_ALLOWLIST`);
- `crontab -l` e `~/.config/systemd/user` (ou `HERMES_CRON`);
- `~/.local/bin`;
- o checkout configurado em `CAREER_OPS_UPSTREAM`.

O resultado fica na seção “Verificação de isolamento” de
[`docs/rehearsals/2026-10-20.md`](rehearsals/2026-10-20.md): **inalterado**.
Alvos que não existem na máquina aparecem como “ausente (antes e depois)”,
também sem alteração; um comando de leitura indisponível (por exemplo
`crontab -l` ausente) é marcado como “comando indisponível”. Neste ambiente o
checkout do career-ops e a allowlist não existem, então a prova real foi a
ausência idêntica antes/depois. A suíte repete a prova com um `HOME` falso
povoado, inclusive upstream, para exercitar o caminho de arquivos existentes.
Para repetir na máquina real:

```bash
# use os caminhos reais quando forem diferentes dos defaults
HERMES_ALLOWLIST=~/.hermes/allowlist.json \
HERMES_CRON=~/.hermes/cron.json \
CAREER_OPS_UPSTREAM=~/.local/share/career-ops \
scripts/rehearsal --date 2026-10-20
```

A suíte também prova o isolamento com um `HOME` temporário povoado com
`~/.hermes`, allowlist, `~/.local/bin`, timers e upstream falso; nenhum
comando escreve nesses caminhos. O sistema atual continua operando ao lado do
novo porque o novo só escreve em `config/`, `data/` e `output/` deste repo e
lê o upstream sem alterar. Neste ambiente o sistema antigo não está instalado,
então não foi possível executá-lo para observar a coexistência; o que foi
observado é que seus caminhos não foram tocados.

## Ensaio paralelo e linha de base

O ensaio executou:

- **1 vaga**: 1 verificada, sessão completa com screenshots e relatório.
- **3 vagas**: shortlist mista com descarte por título, localização e
  elegibilidade; 3 verificadas, 1 CV gerado e 2 reutilizados.
- **20 vagas**: 25 candidatos, 20 JDs lidas, 20 verificadas e parada exata em
  `target_reached`, sem 21ª tentativa.

A linha de base de 19/10 tinha 1.950 cards, 344 vagas únicas, 129 na shortlist,
12 JDs lidas, 4 elegíveis, 0 envios e 0 verificadas porque o renderer congelou
no upload do CV. A comparação completa está em
[`docs/rehearsals/2026-10-20.md`](rehearsals/2026-10-20.md). O ensaio não
reexecuta os 1.950 cards; ele compara as etapas a partir de listas de
candidatos e fixtures de JD.

## Checklist de cutover

1. Rodar o smoke real de uma vaga com perfil/porta separados e confirmar
   `status: "verified"` e as screenshots.
2. Rodar uma meta pequena (`--target 3`) no navegador paralelo e revisar
   `report.html` e `summary.json`.
3. Liberar os quatro scripts na allowlist do Hermes, sem copiar symlinks para
   `~/.local/bin`.
4. Fazer o Hermes chamar `career-ops-run` no horário atual, mantendo o job
   antigo ativo.
5. Comparar duas rodadas reais antes de desligar o job antigo.
6. Configurar a ponte de `waiting_input` → Telegram → `career-ops-reply`.
7. Só então decidir o cutover. O rollback é simples: o sistema antigo nunca foi
   alterado.

# 05: Fila, filtros e elegibilidade

**What to build:** o sistema recebe uma lista de candidatos, deduplica, filtra título e localização, baixa somente a JD necessária, monta um perfil estruturado e aplica elegibilidade determinística. A primeira vaga elegível segue para aplicação.

**Blocked by:** 04 (CLI de uma vaga com adaptador de aplicação)

**Status:** done

- [x] O sistema aceita uma lista de candidatos e mantém uma fila persistente.
- [x] IDs já aplicados, fechados ou descartados não voltam para a fila sem motivo.
- [x] O filtro de título rejeita QA, segurança, infraestrutura, liderança, estágio e júnior, com motivo registrado.
- [x] O filtro de localização aceita remoto ou presencial na região de Recife e rejeita híbrido/presencial fora da região.
- [x] A JD é baixada apenas para candidatos que passaram pelos filtros rápidos.
- [x] O perfil da vaga registra idioma, família, senioridade, skills obrigatórias e skills preferidas.
- [x] A elegibilidade produz uma decisão e um motivo auditável por vaga.
- [x] A primeira vaga elegível é encaminhada ao fluxo de aplicação.
- [x] Testes cobrem título, localização, dedupe, JD ausente, perfil estruturado e motivos de inelegibilidade.
- [x] O sistema atual permanece intocado.

## Comments

- `career_ops.queue` mantém `data/queue.json` com um registro por `id`, estado,
  motivo, detalhe, perfil, decisão e histórico de auditoria. `career-ops-run
  --candidates <json|tsv>` carrega a lista, deduplica, aplica os filtros rápidos
  e só busca a JD dos sobreviventes; `--jd-dir` lê JDs offline e o modo real usa
  o endpoint guest do LinkedIn. A JD fica em `data/jds/<id>.txt`.
- Filtros em `career_ops.job_filters`: título rejeita estágio, júnior, QA,
  segurança, infraestrutura/DevOps, liderança e títulos fora de desenvolvimento
  com motivos estáveis (`title_*`). Localização aceita remoto em qualquer lugar
  ou presencial/híbrido na região de Recife; híbrido ou presencial fora da
  região e localização ausente são rejeitados (`location_*`). Como a máquina de
  estados explícita não tem estado de localização, a rejeição é gravada como
  `ineligible` com `detail.filter: "location"` e o motivo específico.
- `career_ops.job_profile` monta idioma, família, senioridade, skills
  obrigatórias e preferidas de forma determinística. `career_ops.eligibility`
  compara esse perfil com regras configuráveis em `config/eligibility.json`
  (defaults: pt/en, frontend/backend/fullstack/mobile, mid/senior/unspecified) e
  devolve `eligible` + `checks` + motivo (`language_unsupported`,
  `family_not_targeted`, `seniority_not_targeted`).
- O `QueueProcessor` devolve a primeira vaga elegível ao fluxo de aplicação; as
  demais ficam em `new`, sem JD baixada, para a próxima execução. O resultado da
  aplicação volta para a fila (`applying` → `verified`, `waiting_input`,
  `ineligible` ou `failed`). `--requeue-reason` é a única forma de trazer um id
  terminal de volta, e o motivo fica no histórico.
- Revisão (standards + spec) aplicada: um id que já estava na fila e reaparece
  como aplicado/fechado/descartado passa para `ineligible` (antes era ignorado
  como duplicata); `jd_fetched` é retomável, então uma interrupção entre baixar
  a JD e decidir não deixa a vaga presa; híbrido em Recife passou a ser aceito,
  alinhado à spec de evitar apenas híbrido fora da região; a rejeição de
  localização voltou para `ineligible` + detalhe para respeitar a máquina de
  estados e o `GLOSSARY.md`; o histórico da fila foi explicitamente separado do
  `events.jsonl` de sessão no README; fixtures de JD DevOps foram
  compartilhadas em `tests/conftest.py`; campos não usados de `JobProfile`
  foram removidos. Testes de CLI cobrem agora os motivos
  `language_unsupported`, `family_not_targeted`, `seniority_not_targeted` e o
  fluxo de requeue explícito.
- Remainders aceitos: `title_non_dev` também barra design/vendas/marketing/
  dados, além das categorias pedidas, porque o sinal de desenvolvimento
  (`_DEV_SIGNAL`) aceitaria títulos como "Business Development Representative";
  é um filtro barato e títulos-alvo continuam passando. `applying` permanece
  bloqueante: repetir uma aplicação interrompida sem checagem externa poderia
  aplicar duas vezes (ADR-0002/standards). A duplicação de padrões de
  título/senioridade entre `job_filters` e `job_profile` e o uso de strings para
  estados foram mantidos por serem vocabulários pequenos e estáveis neste
  slice. `STABLE_PATH` em `tests/conftest.py` é uma linha pré-existente fora do
  escopo deste ticket.
- `./scripts/check`: 176 testes, mypy sem erros e ruff limpo. Nenhum arquivo do
  Hermes, de `~/.local/bin` ou do checkout atual do career-ops foi tocado.

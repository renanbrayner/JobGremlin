# 04: CLI de uma vaga com adaptador de aplicação

**What to build:** `career-ops-run --job <id>` aplica uma vaga de ponta a ponta no workspace paralelo, usando um adaptador real ou fake, grava os artefatos da sessão, verifica o LinkedIn e devolve JSON.

**Blocked by:** 02 (Rastreamento visual e eventos de uma aplicação), 03 (Anexo de CV confiável e recuperação de renderer travado)

**Status:** done

- [x] O comando aceita uma vaga explícita e executa o fluxo completo de uma candidatura.
- [x] O adaptador de aplicação tem contrato estreito para abrir, aplicar, verificar e capturar tela.
- [x] A implementação real embrulha os scripts existentes sem alterar o sistema atual.
- [x] A implementação fake permite testar sucesso, falha, CV errado e timeout.
- [x] O comando só retorna sucesso quando o LinkedIn confirma a candidatura.
- [x] O JSON de saída informa status, vaga, resultado, artefatos e motivo de falha.
- [x] O comando tem `--help` em texto humano.
- [x] Testes de aceitação rodam contra o adaptador fake e um smoke test real é documentado.
- [x] Nenhum arquivo do Hermes, do `~/.local/bin` ou do career-ops atual é modificado.

## Comments

- `scripts/career-ops-run` chama `career_ops.cli.main()`. O fluxo é: cria a
  sessão observável, `adapter.open()` (bloqueia `already_applied`, `job_closed`
  e `no_easy_apply`), captura `open`, delega o envio ao `SubmissionGuard` do
  ticket #03 e só devolve sucesso quando `verify()` confirma. O JSON traz
  `status`, `job`, `result`, `failure` e `artifacts` (sessão, eventos e
  screenshots), além de `run_id` e `cv`. Exit codes: `0` verificado, `1` não
  verificado, `2` uso inválido, `3` CV/answers/configuração e `6` formulário em
  espera.
- Contrato estreito em `career_ops.adapter.ApplicationAdapter`: `open`,
  `attach`/`selected_cvs`/`submit`/`verify` (via `SubmissionAdapter`),
  `capture` e `recover`. `JobInfo` carrega o estado da vaga e o bloqueio.
- `RealApplicationAdapter` embrulha `jobinfo`, `cdp` e `easyapply` sem editá-los:
  pré-carrega o PDF em `/jobs/application-settings/`, preenche com
  `--cv-library-only` (sem `--submit`), escolhe o rádio do CV quando existe,
  submete com `--resume --submit` e confirma com `jobinfo`. Timeout de
  subprocesso vira `RendererTimeout`; `cdp-unstick` recupera entre tentativas.
  `CAREER_OPS_APPLY_TIMEOUT_SECONDS` (default 420) limita um `easyapply`
  completo.
- `FakeApplicationAdapter` cobre `success`, `failure`, `wrong_cv`, `timeout` e
  `waiting_input`; os testes de aceitação executam o CLI real em subprocesso
  contra o workspace temporário e leem o JSON e a sessão.
- Revisão (standards + spec) aplicada: cenário `waiting_input` e exit 6
  testados; configuração expandida por `career_ops.paths.expand_path` (sem
  `os.environ` direto no CLI); fixtures/fakes compartilhados em
  `tests/conftest.py`; `CommandOutput.argv` e contadores não usados removidos;
  parsing de `cdp eval` e checagem de exit 6 deduplicados; envelope JSON
  unificado; deadline externo corrigido; isolamento upstream/home cobre o novo
  comando; smoke test documentado com `CDP_PORT=9334` exportado.
- Remainders aceitos: capturas por página (`form_page`) exigem instrumentar o
  `easyapply` copiado (fora do escopo deste ticket; o recorder já suporta a
  etapa e o README registra a limitação); `resume` no contrato do adaptador
  fica para o ticket #09 (`career-ops-reply`), junto com o fluxo de resposta.
  Detecção de vaga fechada/já aplicada e `--run-id` foram adicionados por
  alinhamento direto com a spec (linhas 80 e 90), não por scope creep.
- `./scripts/check`: 101 testes, mypy sem erros e ruff limpo. Nenhum arquivo do
  Hermes, de `~/.local/bin` ou do checkout upstream foi tocado.

# 03: Anexo de CV confiável e recuperação de renderer travado

**What to build:** o fluxo de anexar CV deixa de ser uma bomba-relógio. Se o CV esperado não estiver anexado, a candidatura não é enviada. Se o renderer congelar, o sistema registra evidência e falha de forma recuperável.

**Blocked by:** 02 (Rastreamento visual e eventos de uma aplicação)

**Status:** done

- [x] O sistema compara o CV anexado com o CV esperado antes de enviar.
- [x] Se o CV estiver errado, a candidatura é abortada e marcada como falha, nunca como enviada.
- [x] O sistema detecta timeout ou congelamento de renderer dentro de um limite configurável.
- [x] Em congelamento, uma captura via `grim` é salva junto com o erro.
- [x] A vaga pode ser tentada de novo sem corromper a sessão do navegador.
- [x] O caso de 19/10 está coberto por teste de regressão.
- [x] Testes simulam CV errado, timeout e retry seguro.
- [x] Nenhuma mudança é feita no Hermes ou no career-ops atual.

## Comments

- `career_ops.cv_attachment.verify_cv_attachment()` compara o nome do PDF
  esperado **apenas com o CV selecionado** no formulário, com normalização de
  caminho, caixa e espaços. O adapter é obrigado a ler somente o selecionado,
  nunca a biblioteca inteira. Não existe fallback: CV errado ou ausente vira
  `WrongCvAttached` e o guard retorna `submitted=False` sem nunca chamar o
  clique de envio.
- `career_ops.renderer.RendererWatchdog` impõe um prazo rígido por operação
  (default 30s, configurável por `CAREER_OPS_RENDERER_TIMEOUT_SECONDS`) em uma
  thread daemon, então um `recv` pendurado não bloqueia o registro da falha. A
  configuração respeita a precedência real: ambiente > `config/career-ops.env`
  > default, usando `paths.load_environment()`. `CommandRecovery`/
  `cdp_unstick_recovery` executam o `cdp-unstick` copiado com timeout e probe
  opcional; `RecoverableBrowser` fecha o socket antigo e reconecta no mesmo
  target, inclusive quando o unstick falha.
- `career_ops.submission.SubmissionGuard` aplica a ordem segura: anexa o CV
  esperado sob deadline, relê só o CV selecionado, captura
  `cv_selection`/`review`, envia, captura `submit` e só considera enviado
  quando `verify()` confirma. Timeout antes do clique chama
  `SessionRecorder.fail()` (que cai para `grim` no CDP travado), recupera e
  tenta de novo (máximo duas tentativas). Timeout depois do clique e envio sem
  confirmação retornam `retryable=False`, porque o LinkedIn pode já ter
  registrado a candidatura e um retry poderia aplicar duas vezes.
- O teste de regressão de 19/10 congela o **upload** do CV, prova que a
  screenshot via `grim` fica em `screenshots/error.png`, que a sessão é
  recuperada e que o envio acontece uma única vez na segunda tentativa.
- Correções da revisão: removido `pdf_names_from_text` (sem uso e sujeito a
  falso positivo), contrato renomeado para `selected_cvs()`, dedupe
  normalizado, `SubmissionResult` com `submitted` como fonte única, fixtures de
  teste compartilhadas e `Status: done` documentado em
  `docs/agents/triage-labels.md`.
- `./scripts/check` (pytest, mypy e ruff, com Python travado via `uv`): 80
  testes passando, mypy sem erros e ruff sem erros.
- Nenhum arquivo do Hermes, de `~/.local/bin` ou do checkout upstream foi
  tocado. O núcleo fica pronto para o adaptador real do ticket #04.

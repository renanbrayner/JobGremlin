# 03: Anexo de CV confiável e recuperação de renderer travado

**What to build:** o fluxo de anexar CV deixa de ser uma bomba-relógio. Se o CV esperado não estiver anexado, a candidatura não é enviada. Se o renderer congelar, o sistema registra evidência e falha de forma recuperável.

**Blocked by:** 02 (Rastreamento visual e eventos de uma aplicação)

**Status:** ready-for-agent

- [ ] O sistema compara o CV anexado com o CV esperado antes de enviar.
- [ ] Se o CV estiver errado, a candidatura é abortada e marcada como falha, nunca como enviada.
- [ ] O sistema detecta timeout ou congelamento de renderer dentro de um limite configurável.
- [ ] Em congelamento, uma captura via `grim` é salva junto com o erro.
- [ ] A vaga pode ser tentada de novo sem corromper a sessão do navegador.
- [ ] O caso de 19/10 está coberto por teste de regressão.
- [ ] Testes simulam CV errado, timeout e retry seguro.
- [ ] Nenhuma mudança é feita no Hermes ou no career-ops atual.

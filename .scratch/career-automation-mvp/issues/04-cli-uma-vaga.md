# 04: CLI de uma vaga com adaptador de aplicação

**What to build:** `career-ops-run --job <id>` aplica uma vaga de ponta a ponta no workspace paralelo, usando um adaptador real ou fake, grava os artefatos da sessão, verifica o LinkedIn e devolve JSON.

**Blocked by:** 02 (Rastreamento visual e eventos de uma aplicação), 03 (Anexo de CV confiável e recuperação de renderer travado)

**Status:** ready-for-agent

- [ ] O comando aceita uma vaga explícita e executa o fluxo completo de uma candidatura.
- [ ] O adaptador de aplicação tem contrato estreito para abrir, aplicar, verificar e capturar tela.
- [ ] A implementação real embrulha os scripts existentes sem alterar o sistema atual.
- [ ] A implementação fake permite testar sucesso, falha, CV errado e timeout.
- [ ] O comando só retorna sucesso quando o LinkedIn confirma a candidatura.
- [ ] O JSON de saída informa status, vaga, resultado, artefatos e motivo de falha.
- [ ] O comando tem `--help` em texto humano.
- [ ] Testes de aceitação rodam contra o adaptador fake e um smoke test real é documentado.
- [ ] Nenhum arquivo do Hermes, do `~/.local/bin` ou do career-ops atual é modificado.

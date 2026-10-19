# 01: Base versionada e isolada

**What to build:** um workspace paralelo versionado, com cópia dos scripts necessários, dados e outputs próprios e harness de testes. O sistema atual não é movido, alterado ou desligado.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] O workspace paralelo está inicializado como repositório git.
- [ ] Os scripts necessários para rodar o fluxo atual foram copiados para o workspace novo, sem mover nem alterar os originais.
- [ ] O workspace novo tem diretórios próprios de configuração, dados e outputs.
- [ ] O workspace novo pode ler configuração e dados do career-ops atual, mas não escreve neles.
- [ ] `~/.local/bin`, `~/.hermes`, cron, allowlist e o checkout atual do career-ops permanecem intocados.
- [ ] A suíte de testes roda no workspace novo.
- [ ] Um smoke test prova que os comandos copiados executam a partir do workspace novo.
- [ ] O README documenta o isolamento e como rodar o sistema paralelo.

# 01: Base versionada e isolada

**What to build:** um workspace paralelo versionado, com cópia dos scripts necessários, dados e outputs próprios e harness de testes. O sistema atual não é movido, alterado ou desligado.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] O workspace paralelo está inicializado como repositório git.
- [x] Os scripts necessários para rodar o fluxo atual foram copiados para o workspace novo, sem mover nem alterar os originais.
- [x] O workspace novo tem diretórios próprios de configuração, dados e outputs.
- [x] O workspace novo pode ler configuração e dados do career-ops atual, mas não escreve neles.
- [x] `~/.local/bin`, `~/.hermes`, cron, allowlist e o checkout atual do career-ops permanecem intocados.
- [x] A suíte de testes roda no workspace novo.
- [x] Um smoke test prova que os comandos copiados executam a partir do workspace novo.
- [x] O README documenta o isolamento e como rodar o sistema paralelo.

## Comments

- Scripts copiados para `scripts/`, com caminhos reparametrizados por
  `scripts/lib/paths.{sh,mjs}` e `src/career_ops/paths.py`.
- Guardas recusam escrita dentro de `CAREER_OPS_UPSTREAM`; testes usam um
  upstream falso e um `$HOME` temporário para provar que nada é alterado.
- `python3 -m pytest`: 28 testes passando (paths, smoke, paridade dos três
  helpers e isolamento).

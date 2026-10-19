# 11: Ensaio paralelo e handoff

**What to build:** validar o sistema novo em paralelo, sem tocar no sistema atual, e entregar um pacote de handoff para que Renan faça a integração com o Hermes quando quiser.

**Blocked by:** 10 (Help e catálogo de comandos para o Hermes)

**Status:** ready-for-agent

- [ ] Uma rodada de 1 vaga é executada no workspace paralelo e produz artefatos completos.
- [ ] Uma rodada de 3 vagas é executada e o relatório mostra funil, decisões e resultados.
- [ ] Uma simulação de 20 vagas é executada com adaptador fake e termina exatamente em 20 verificadas.
- [ ] O handoff documenta comandos, help JSON, exit codes, schema de saída e caminhos dos artefatos.
- [ ] O handoff lista limitações conhecidas e o que ainda depende do Hermes.
- [ ] O relatório compara a rodada paralela com a linha de base de 19/10.
- [ ] Uma verificação final prova que `~/.hermes`, cron, allowlist, `~/.local/bin` e o career-ops atual não foram alterados.
- [ ] O sistema atual continua operando normalmente ao lado do novo.

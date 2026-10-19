# 10: Help e catálogo de comandos para o Hermes

**What to build:** uma CLI de descoberta que permita ao Hermes entender como usar o sistema sem engenharia reversa, com help humano e catálogo JSON de comandos, argumentos, exit codes, exemplos e contratos de saída.

**Blocked by:** 08 (Relatório, retenção e sessão), 09 (Formulário em espera e CLI de resposta)

**Status:** ready-for-agent

- [ ] `career-ops-help` mostra uma visão humana dos comandos disponíveis.
- [ ] `career-ops-help --json` retorna um catálogo legível por máquina.
- [ ] O catálogo inclui nome, descrição, argumentos, opções, exemplos, exit codes e schema de saída de cada comando.
- [ ] Todo comando individual aceita `--help` e mostra uso e exemplos.
- [ ] O catálogo é gerado a partir do registro de comandos, não de uma lista duplicada mantida à mão.
- [ ] Testes garantem que todos os comandos registrados aparecem no help e que o JSON é válido contra o schema.
- [ ] O help documenta explicitamente que o sistema é paralelo e não altera Hermes, cron ou career-ops atual.
- [ ] Nenhuma alteração é feita no Hermes ou no cron.

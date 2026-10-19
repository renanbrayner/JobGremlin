# 02: Rastreamento visual e eventos de uma aplicação

**What to build:** uma aplicação passa a produzir uma sessão observável, com screenshots nas transições principais e eventos estruturados, sem alterar o fluxo atual do Hermes.

**Blocked by:** 01 (Base versionada e isolada)

**Status:** ready-for-agent

- [ ] Uma execução de aplicação cria um diretório de sessão com metadados, eventos e screenshots.
- [ ] Há screenshot ao abrir a vaga, em cada página do formulário, na revisão, no envio e em erro.
- [ ] Cada screenshot tem nome estável e referência no evento correspondente.
- [ ] O log de eventos registra timestamp, vaga, etapa, status, duração e artefato.
- [ ] Timeout de CDP tenta uma captura do sistema com `grim` antes de marcar falha.
- [ ] A sessão continua inspecionável mesmo quando a aplicação falha.
- [ ] Testes cobrem a criação dos artefatos, o schema dos eventos e o fallback de captura.
- [ ] O sistema atual continua sem alterações.

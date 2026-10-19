# 06: Cache de CV e tailoring

**What to build:** cada vaga elegível usa um CV gerado por vaga ou reutiliza um CV com match alto. O cache é indexado por competências, idioma, família e senioridade, e só reutiliza quando não falta nenhuma competência obrigatória.

**Blocked by:** 05 (Fila, filtros e elegibilidade)

**Status:** ready-for-agent

- [ ] O perfil da vaga gera um fingerprint de competências.
- [ ] O cache tem índice consultável e metadados legíveis por CV.
- [ ] O reuso exige mesmo idioma, família compatível, senioridade compatível e zero must-have faltando.
- [ ] O reuso exige similaridade ponderada de pelo menos 0.90, configurável.
- [ ] Em cache hit, o CV existente é reutilizado e a vaga é registrada como origem adicional.
- [ ] Em cache miss, um CV novo é gerado e indexado.
- [ ] O CV não contém nome de empresa; a cover letter continua específica por vaga.
- [ ] O relatório registra cache hit/miss, score, CV usado e motivo da decisão.
- [ ] O `openai-tailor` é chamado apenas em cache miss.
- [ ] Testes cobrem hit exato, alta similaridade, idioma diferente, senioridade incompatível, must-have faltando e score abaixo do threshold.

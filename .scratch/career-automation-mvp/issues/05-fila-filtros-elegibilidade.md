# 05: Fila, filtros e elegibilidade

**What to build:** o sistema recebe uma lista de candidatos, deduplica, filtra título e localização, baixa somente a JD necessária, monta um perfil estruturado e aplica elegibilidade determinística. A primeira vaga elegível segue para aplicação.

**Blocked by:** 04 (CLI de uma vaga com adaptador de aplicação)

**Status:** ready-for-agent

- [ ] O sistema aceita uma lista de candidatos e mantém uma fila persistente.
- [ ] IDs já aplicados, fechados ou descartados não voltam para a fila sem motivo.
- [ ] O filtro de título rejeita QA, segurança, infraestrutura, liderança, estágio e júnior, com motivo registrado.
- [ ] O filtro de localização aceita remoto ou presencial na região de Recife e rejeita híbrido/presencial fora da região.
- [ ] A JD é baixada apenas para candidatos que passaram pelos filtros rápidos.
- [ ] O perfil da vaga registra idioma, família, senioridade, skills obrigatórias e skills preferidas.
- [ ] A elegibilidade produz uma decisão e um motivo auditável por vaga.
- [ ] A primeira vaga elegível é encaminhada ao fluxo de aplicação.
- [ ] Testes cobrem título, localização, dedupe, JD ausente, perfil estruturado e motivos de inelegibilidade.
- [ ] O sistema atual permanece intocado.

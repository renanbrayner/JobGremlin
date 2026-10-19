# 07: Loop diário até 20 verificadas

**What to build:** o sistema executa o loop diário completo, busca vagas sob demanda, processa uma por vez e para exatamente ao atingir 20 candidaturas verificadas, ao esgotar o tempo ou ao detectar limite do LinkedIn.

**Blocked by:** 05 (Fila, filtros e elegibilidade), 06 (Cache de CV e tailoring)

**Status:** ready-for-agent

- [ ] O loop busca novos candidatos apenas quando a fila está baixa.
- [ ] O loop processa uma candidatura por vez, sem paralelismo de aplicação.
- [ ] O contador só incrementa após confirmação do LinkedIn.
- [ ] O loop para exatamente em 20 envios verificados e não inicia uma 21ª tentativa.
- [ ] O loop respeita orçamento máximo de tempo.
- [ ] O loop interrompe e reporta ao detectar limite diário do LinkedIn.
- [ ] Cada vaga tem no máximo duas tentativas.
- [ ] A execução tem lock para impedir rodadas simultâneas.
- [ ] Uma rodada interrompida pode ser retomada sem reaplicar vagas confirmadas.
- [ ] Testes com adaptador fake provam 25 candidatos → exatamente 20 envios, retomada e parada por limite.

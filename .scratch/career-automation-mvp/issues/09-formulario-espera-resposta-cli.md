# 09: Formulário em espera e CLI de resposta

**What to build:** quando o formulário pedir uma resposta desconhecida, ele fica estacionado em uma aba, a vaga vira `waiting_input` e o loop continua na próxima vaga. A CLI expõe as perguntas e permite gravar respostas e retomar o formulário em uma única chamada.

**Blocked by:** 07 (Loop diário até 20 verificadas)

**Status:** ready-for-agent

- [ ] Exit 6 marca a vaga como `waiting_input` e mantém o formulário aberto.
- [ ] O loop continua na próxima vaga enquanto o formulário espera.
- [ ] No máximo um formulário fica estacionado por vez.
- [ ] As perguntas pendentes ficam disponíveis em JSON com vaga, empresa, opções e token de retomada.
- [ ] `career-ops-reply` valida as respostas, grava no arquivo de respostas do workspace paralelo e retoma o formulário correto.
- [ ] A retomada usa a aba e o target corretos, sem reabrir o formulário do zero quando a sessão continua viva.
- [ ] Se a aba foi perdida, a vaga é marcada como falha recuperável, nunca como enviada.
- [ ] O comando tem `--help` em texto humano.
- [ ] Testes cobrem exit 6, limite de um formulário, resposta válida, resposta inválida, retomada e aba perdida.
- [ ] O Hermes, o cron e a allowlist não são alterados; a CLI apenas expõe o contrato para integração futura.

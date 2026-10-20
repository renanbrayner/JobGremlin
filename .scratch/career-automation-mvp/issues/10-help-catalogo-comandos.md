# 10: Help e catálogo de comandos para o Hermes

**What to build:** uma CLI de descoberta que permita ao Hermes entender como usar o sistema sem engenharia reversa, com help humano e catálogo JSON de comandos, argumentos, exit codes, exemplos e contratos de saída.

**Blocked by:** 08 (Relatório, retenção e sessão), 09 (Formulário em espera e CLI de resposta)

**Status:** done

- [x] `career-ops-help` mostra uma visão humana dos comandos disponíveis.
- [x] `career-ops-help --json` retorna um catálogo legível por máquina.
- [x] O catálogo inclui nome, descrição, argumentos, opções, exemplos, exit codes e schema de saída de cada comando.
- [x] Todo comando individual aceita `--help` e mostra uso e exemplos.
- [x] O catálogo é gerado a partir do registro de comandos, não de uma lista duplicada mantida à mão.
- [x] Testes garantem que todos os comandos registrados aparecem no help e que o JSON é válido contra o schema.
- [x] O help documenta explicitamente que o sistema é paralelo e não altera Hermes, cron ou career-ops atual.
- [x] Nenhuma alteração é feita no Hermes ou no cron.

## Comments

Implementação: `career_ops.catalog.REGISTRY` é a única lista de comandos. Cada
módulo de comando expõe `SUMMARY`, `EXAMPLES`, `EXIT_CODES` e `OUTPUT_SCHEMA`, e
o parser argparse fornece uso, argumentos e opções; `career-ops-help` renderiza
a visão humana e o catálogo JSON a partir disso. `build_epilog` compartilha as
seções de exit codes/exemplos com o `--help` de run, reply e report.

O schema do catálogo vive em `docs/schema/help-catalog.schema.json`. A suíte
valida o JSON contra esse schema, confere que todo módulo do pacote com
`COMMAND` está registrado, e valida saídas reais de run, reply (erro e retomada
com sucesso), report (sucesso e erro) e help contra os schemas publicados. O
validador de teste rejeita qualquer keyword de schema que não implemente, para
não dar uma garantia falsa.

Verificação: `./scripts/check` verde com 260 testes.

Revisão (duas rodadas, eixos Standards e Spec): achados resolvidos — contrato
de saída do report nos erros, defaults de lista (`--answer`), campos opcionais
de erro, duplicação do texto de isolamento/glue de epilog, padrão de nomes para
posicionais e gate de keywords do validador. Permanecem aceitos, com motivo:

- `career-ops-status` ainda não existe; o ticket cobre todos os comandos
  **registrados** (run, reply, report, help) e o status fica para um ticket
  próprio. O README registra a limitação.
- A introspecção usa `parser._actions` e nomes de classes internas do argparse
  porque não há API pública para listar argumentos; o schema enumera as actions
  suportadas e o fallback não expõe nomes privados no JSON.
- O validador de schema é uma implementação local do subconjunto usado pelo
  schema versionado (sem dependência nova); keywords desconhecidas falham o
  teste em vez de passar em silêncio.
- `summary`/`jobs`/`retention` do report são opcionais no schema publicado
  porque o envelope de erro não os carrega; as chaves comuns a sucesso e erro
  permanecem obrigatórias.
- Erros de argparse continuam sem JSON no stdout, como nos demais comandos; o
  contrato JSON vale para os exit codes documentados do comando.

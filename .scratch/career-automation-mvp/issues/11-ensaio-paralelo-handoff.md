# 11: Ensaio paralelo e handoff

**What to build:** validar o sistema novo em paralelo, sem tocar no sistema atual, e entregar um pacote de handoff para que Renan faça a integração com o Hermes quando quiser.

**Blocked by:** 10 (Help e catálogo de comandos para o Hermes)

**Status:** done

- [x] Uma rodada de 1 vaga é executada no workspace paralelo e produz artefatos completos.
- [x] Uma rodada de 3 vagas é executada e o relatório mostra funil, decisões e resultados.
- [x] Uma simulação de 20 vagas é executada com adaptador fake e termina exatamente em 20 verificadas.
- [x] O handoff documenta comandos, help JSON, exit codes, schema de saída e caminhos dos artefatos.
- [x] O handoff lista limitações conhecidas e o que ainda depende do Hermes.
- [x] O relatório compara a rodada paralela com a linha de base de 19/10.
- [x] Uma verificação final prova que `~/.hermes`, cron, allowlist, `~/.local/bin` e o career-ops atual não foram alterados.
- [x] O sistema atual continua operando normalmente ao lado do novo.

## Comments

Implementação: `scripts/rehearsal` (wrapper fino) e `career_ops.rehearsal_cli`
executam as rodadas de 1, 3 e 20 vagas com o adaptador fake em um workspace
descartável, verificam que cada rodada produziu as sessões, screenshots e os
quatro artefatos de relatório, e gravam o pacote em `docs/rehearsals/<data>.md`
e `.json`. `career_ops.rehearsal` mantém a linha de base de 19/10 e renderiza a
comparação; `career_ops.isolation` faz o fingerprint antes/depois de `~/.hermes`,
allowlist, cron (incluindo `/etc/crontab`, `/etc/cron.d` e `/var/spool/cron`),
`~/.local/bin` e `CAREER_OPS_UPSTREAM`.

O handoff está em `docs/HANDOFF.md`, com comandos, exit codes, envelope de
saída, schema, caminhos dos artefatos, limitações e dependências do Hermes. O
snapshot de `career-ops-help --json` fica em `docs/handoff/help-catalog.json` e
um teste o compara com o catálogo gerado do registro.

Validação real em 20/10: rodada de 1 vaga com 1 verificada; rodada de 3 vagas
com 6 candidatos, 3 descartes (título, localização e família), 3 verificadas e
1 CV gerado + 2 reutilizados; rodada de 20 vagas com 25 candidatos, 20
verificadas, 1 CV gerado + 19 reutilizados, `target_reached` e nenhuma 21ª
tentativa. O relatório committed é `docs/rehearsals/2026-10-20.md`.

Isolamento: `~/.hermes` e `~/.local/bin` existiam e ficaram idênticos; cron foi
observado via fontes do sistema e ficou idêntico (o comando `crontab` não está
instalado); allowlist e `CAREER_OPS_UPSTREAM` não existem neste ambiente e
aparecem como “não observado”, nunca como prova positiva. A suíte repete a
prova com um `HOME` falso povoado, inclusive upstream e allowlist.

Revisão em dois eixos (Standards e Spec) executada em duas rodadas. Achados
resolvidos: subprocess de isolamento atrás de runner injetável; remoção de
`os.environ`/`Path.home` dos caminhos; guard de escrita do relatório; guard
recursivo do workspace descartável; fixtures compartilhadas; constantes de
motivo compartilhadas; resultados por vaga no relatório entregue; rótulo de
vagas únicas; e distinção entre “inalterado” e “não observado”. Permanecem
aceitos, com motivo:

- `career-ops-status` continua fora deste ticket; o ticket 10 já registrou que
  ele fica para um ticket próprio. O handoff documenta a limitação e aponta
  `data/runs/<run_id>.json`, `summary.json` e `career-ops-report --json` como
  substitutos até a existência do comando.
- O sistema antigo não está instalado neste ambiente, então não foi possível
  executá-lo para observar a coexistência; o que foi provado é que nenhum
  caminho dele foi escrito. O handoff registra isso explicitamente.
- `scripts/rehearsal` é ferramenta de desenvolvimento, não comando do Hermes; a
  chamada `subprocess.run` do orquestrador fica no próprio runner e é coberta
  pelo teste de integração da CLI. O catálogo público continua com os quatro
  comandos registrados.
- O teste do relatório entregue fixa `2026-10-20` de propósito: ele valida o
  pacote committed, não uma data futura. O runner aceita `--date` para gerar
  novos relatórios.

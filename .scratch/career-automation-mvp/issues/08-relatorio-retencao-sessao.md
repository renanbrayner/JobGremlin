# 08: Relatório, retenção e sessão

**What to build:** cada sessão diária produz um relatório legível e um resumo consumível por máquina, com funil completo, status por vaga, thumbnails e retenção das três últimas sessões. Vídeo é opcional.

**Blocked by:** 07 (Loop diário até 20 verificadas)

**Status:** done

- [x] Cada sessão tem um relatório Markdown e um relatório HTML.
- [x] O relatório mostra o funil: candidatos, descartes por motivo, elegíveis, CVs gerados/reutilizados, aplicadas, verificadas e falhas.
- [x] Cada vaga tem status, duração, CV usado, motivo de falha e links para screenshots.
- [x] O relatório HTML exibe thumbnails das evidências.
- [x] Um resumo em texto e JSON é gerado para consumo pelo Hermes, sem envio automático.
- [x] As três últimas sessões completas são mantidas; as anteriores são limpas.
- [x] Vídeo MP4 é opcional e desligado por padrão.
- [x] Testes cobrem schema do relatório, funil, retenção e geração do resumo.
- [x] Nenhum arquivo do Hermes é alterado.

## Comments

- Implementado `career_ops.report` + `career_ops.report_cli` + `scripts/career-ops-report`.
  Cada rodada diária grava `report.md`, `report.html`, `summary.txt` e
  `summary.json` em `output/sessions/<run_id>/`.
- O relatório é montado apenas de artefatos persistidos. O estado por vaga usa a
  janela de histórico da rodada (`started_at`–`updated_at`), com o run state
  tendo precedência, para que mudanças posteriores da fila não reescrevam um
  relatório antigo.
- Retenção remove apenas rodadas finalizadas (`verified`/`failed` com
  `stop_reason`), mantém as três mais recentes e ignora `run_id` corrompido
  antes de montar caminhos de exclusão. `--keep`/`CAREER_OPS_RETENTION_RUNS`
  ajustam a janela; `--no-prune` desliga a limpeza.
- Se a rodada pedida estiver fora da janela, `career-ops-report` grava o
  relatório antes da limpeza e depois a remove, junto com o estado.
- Vídeo é opcional (`--video`/`CAREER_OPS_VIDEO`), desligado por padrão e sua
  falha nunca altera o resultado da rodada. A gravação é finalizada antes de o
  relatório ser montado, inclusive no caminho de erro inesperado.
- Exceções inesperadas no loop finalizam o estado como
  `stop_reason=unexpected_error` e ainda geram relatório/resumo.
- `./scripts/check` passou: 234 testes, mypy e ruff limpos.
- Revisão em dois eixos executada; os achados de contrato, retenção e
  ordenamento do vídeo foram corrigidos antes de fechar o ticket.

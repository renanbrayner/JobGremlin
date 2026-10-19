# 08: Relatório, retenção e sessão

**What to build:** cada sessão diária produz um relatório legível e um resumo consumível por máquina, com funil completo, status por vaga, thumbnails e retenção das três últimas sessões. Vídeo é opcional.

**Blocked by:** 07 (Loop diário até 20 verificadas)

**Status:** ready-for-agent

- [ ] Cada sessão tem um relatório Markdown e um relatório HTML.
- [ ] O relatório mostra o funil: candidatos, descartes por motivo, elegíveis, CVs gerados/reutilizados, aplicadas, verificadas e falhas.
- [ ] Cada vaga tem status, duração, CV usado, motivo de falha e links para screenshots.
- [ ] O relatório HTML exibe thumbnails das evidências.
- [ ] Um resumo em texto e JSON é gerado para consumo pelo Hermes, sem envio automático.
- [ ] As três últimas sessões completas são mantidas; as anteriores são limpas.
- [ ] Vídeo MP4 é opcional e desligado por padrão.
- [ ] Testes cobrem schema do relatório, funil, retenção e geração do resumo.
- [ ] Nenhum arquivo do Hermes é alterado.

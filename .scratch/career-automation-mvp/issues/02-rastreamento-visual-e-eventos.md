# 02: Rastreamento visual e eventos de uma aplicação

**What to build:** uma aplicação passa a produzir uma sessão observável, com screenshots nas transições principais e eventos estruturados, sem alterar o fluxo atual do Hermes.

**Blocked by:** 01 (Base versionada e isolada)

**Status:** done

- [x] Uma execução de aplicação cria um diretório de sessão com metadados, eventos e screenshots.
- [x] Há screenshot ao abrir a vaga, em cada página do formulário, na revisão, no envio e em erro.
- [x] Cada screenshot tem nome estável e referência no evento correspondente.
- [x] O log de eventos registra timestamp, vaga, etapa, status, duração e artefato.
- [x] Timeout de CDP tenta uma captura do sistema com `grim` antes de marcar falha.
- [x] A sessão continua inspecionável mesmo quando a aplicação falha.
- [x] Testes cobrem a criação dos artefatos, o schema dos eventos e o fallback de captura.
- [x] O sistema atual continua sem alterações.

## Comments

- Implementado `career_ops.session.SessionRecorder` (`output/sessions/<run_id>/`)
  com `session.json`, `events.jsonl` append-only e `screenshots/` com nomes
  estáveis por etapa (`open.png`, `form-page-1.png`, `review.png`, `submit.png`,
  `waiting.png`, `error.png`; repetição bem-sucedida ganha sufixo `-2`).
- `career_ops.capture` isola CDP atrás de um callable injetável e cai
  automaticamente para `grim` em `CaptureTimeout`, inclusive quando o `cdp`
  termina com código != 0 e o stderr indica timeout. O fallback também é
  tentado quando o renderer não responde; a sessão nunca é mascarada por uma
  falha de captura.
- `SessionRecorder.fail()` e `__exit__` registram `error` com screenshot (ou
  captura de sistema) e fecham a sessão como `failed`, mantendo os artefatos
  inspecionáveis.
- `python3 -m pytest`: 48 testes passando; `mypy src tests` sem erros.
- Nenhum arquivo do Hermes, `~/.local/bin` ou do checkout upstream foi tocado.

# 00 - Overview

Projeto de robô de trading spot multipar com:
- Worker assíncrono (`bot.py` + `core/*`)
- API Flask (`api/server.py`)
- Dashboard web (`frontend/src`)
- Persistência SQLite (`core/state_store.py`)

Status geral de aderência ao briefing: **PARCIAL** (ver `../AUDITORIA_PROJETO.md`).

## Escopo funcional atual
- Multipar por configuração.
- Estratégia por spread com âncora local/ref.
- Modo PAPER e LIVE.
- Configuração operacional via API + DB com reload por `config_version`.
- Cofre de credenciais de exchange com criptografia AES-GCM.

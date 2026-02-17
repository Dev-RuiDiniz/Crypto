# 00 - Overview

O projeto implementa um robô de trading cripto multipar com backend Python, API HTTP, dashboard web e persistência em SQLite.

## Capacidades principais
- Execução simultânea de múltiplos pares configuráveis.
- Estratégia de spread com ajuste percentual e manutenção/cancelamento/reinserção de ordens.
- Estratégia de arbitragem simples entre exchanges em modo paper/live.
- Gestão de risco centralizada (`RiskPolicy`) com bloqueios auditáveis.
- Market data com WebSocket quando disponível e fallback automático para polling.
- Alertas operacionais por e-mail e webhook (WhatsApp via integração externa).

## Componentes
- Worker (`bot.py`, `core/*`, `exchanges/*`)
- API (`api/*`)
- Frontend (`frontend/src/*`)

# 06 - Market Data

- `MarketDataService` inicia streams por exchange/par.
- Quando a exchange suporta WS, usa provedor websocket.
- Ao detectar indisponibilidade/stale, alterna automaticamente para polling.
- Tenta reconexão WS após janela de recuperação.

Estados principais: `WS_ACTIVE`, `POLL_ACTIVE`, `RECOVERING_WS`.

# 02 - Architecture

## Módulos
- `core/`: monitor, estratégia, roteamento, risco, persistência.
- `exchanges/`: hub de exchanges, adapter MB v4, normalização.
- `api/`: endpoints de runtime/config/credenciais.
- `frontend/`: dashboard e telas de configuração.
- `security/`: criptografia e redaction.

## Fluxo
```text
config + DB -> bot.py -> MainMonitor
-> StrategySpread -> OrderRouter/OrderManager
-> ExchangeHub (CCXT/MBv4)
-> StateStore + shared_state
-> API Flask -> Dashboard
```

## Observabilidade
- Logs via `utils/logger.py`
- Health endpoints via `api/server.py`

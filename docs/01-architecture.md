# 01 - Architecture

```text
Frontend (Dashboard)
   -> API Flask (api/server.py)
      -> Shared state + serviços (credenciais/notificações)
         -> Worker assíncrono (bot.py + MainMonitor)
            -> Estratégias (Spread + Arbitragem)
            -> Roteamento/Ordens + RiskPolicy + Circuit Breaker
            -> Exchanges (CCXT/MB adapter)
            -> StateStore (SQLite) + logs
```

## Módulos
- `core/`: estratégia, risco, monitor, estado, mercado.
- `exchanges/`: clientes de exchange e abstrações.
- `api/`: endpoints runtime/configuração/operação.
- `frontend/`: UI para configuração e observabilidade.
- `security/`: criptografia e redaction de segredos.

# 10 - Troubleshooting

- Verificar `/api/health`, `/api/health/db`, `/api/health/worker`.
- Conferir `/api/config-status` para inconsistências de configuração.
- Checar logs do worker e API para falhas de exchange/rede.
- Se WS degradar, validar se fallback polling está ativo no status de market data.

## MEXC
- `TIMESTAMP_WINDOW`: verificar relogio do host, comparar com `GET /api/v3/time` e revisar logs `MEXC_DIAGNOSTIC` para `timeDifferenceMs`, `recvWindow` e bucket UTC.
- `PERMISSION_DENIED`: revisar permissoes da key para Spot privado e ordens.
- `ACCOUNT_MODE_MISMATCH`: confirmar que a key pertence a conta/escopo Spot e nao Futures.
- `IP_RESTRICTED`: validar whitelist de IP da API key.
- `WS_DEGRADED` com `WS_STALE` ou `WS_HEARTBEAT_FAILED`: verificar conectividade, heartbeat MEXC e fallback para polling.

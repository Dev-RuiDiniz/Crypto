# 10 - Troubleshooting

- Verificar `/api/health`, `/api/health/db`, `/api/health/worker`.
- Conferir `/api/config-status` para inconsistências de configuração.
- Checar logs do worker e API para falhas de exchange/rede.
- Se WS degradar, validar se fallback polling está ativo no status de market data.

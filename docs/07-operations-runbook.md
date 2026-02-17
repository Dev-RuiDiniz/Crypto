# 07 - Operations Runbook

## Startup
1. Configurar env (`EXCHANGE_CREDENTIALS_MASTER_KEY`).
2. Ajustar `config.txt`.
3. Subir `python run_arbit.py`.
4. Verificar `/api/health`, `/api/health/db`, `/api/health/worker`.

## Operação diária
- Acompanhar dashboard (`/api/mids`, `/api/orders`, `/api/events`).
- Revisar logs em `logs/`.
- Usar `/api/config-status` para conferir sync de configuração.

## Parada segura
- Acionar kill switch/config operacional e confirmar cancelamento de ordens conforme política.

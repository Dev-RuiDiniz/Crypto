# Troubleshooting

## Problemas comuns
1. Dashboard sem dados: worker não publica snapshot.
2. Métricas zeradas: ciclo ainda não executou ou snapshot vazio.
3. Circuit breaker abrindo repetidamente: falha persistente de exchange/rede.
4. Go-live checklist pendente: credenciais/alertas/limites não configurados.

## Diagnóstico rápido
- `GET /api/health`
- `GET /api/health/worker`
- `GET /api/config-status`
- `GET /api/tenants/default/metrics`
- `GET /api/tenants/default/go-live-checklist`

## Logs relevantes
- Eventos `EXCHANGE_AUTH_FAILED_PAUSED`
- Eventos de market data fallback
- Erros de criação/cancelamento de ordens

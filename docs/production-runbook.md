# Production Runbook

## Inicialização
1. Configurar `config.txt` e credenciais por tenant.
2. Subir API: `python -m api.server --host 0.0.0.0 --port 8000`
3. Subir worker: `python bot.py --config config.txt`
4. Abrir frontend via API (`/`).

## Variáveis de ambiente obrigatórias/relevantes
- `TRADINGBOT_TENANT_ID`
- `TRADINGBOT_LOG_DIR`
- `ENCRYPTION_KEY`
- `CB_FAILURE_THRESHOLD` (opcional via config GLOBAL)
- `CB_OPEN_BACKOFF_SEC` (opcional via config GLOBAL)

## Migrations
- As migrations SQLite são auto-aplicadas no bootstrap (`StateStore` e serviços associados).

## Paper mode
- `GLOBAL.MODE=PAPER` no `config.txt`.

## Rollback
- Restaurar último commit/tag estável.
- Reverter `config.txt` para parâmetros anteriores.
- Reiniciar API/worker.

## Logs
- API: `api.log`
- Worker: logs do processo + eventos estruturados.

## Resposta a incidentes
- **Auth failure**: revisar credenciais ativas; re-testar em `/settings/exchanges`.
- **Circuit breaker open**: aguardar backoff ou corrigir exchange/rede; observar `/api/tenants/{tenantId}/metrics`.
- **WS fallback**: verificar conectividade WS; fallback em polling mantém operação degradada.
- **Risk blocks**: revisar `risk_events` e limites em `Config do Bot`.

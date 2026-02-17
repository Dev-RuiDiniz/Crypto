# Auditoria Sprint 9 — Alertas Externos

## Mapeamento do que já existe

- **Order executed**: criação de ordens em `OrderManager._create_quantized`, com persistência em `StateStore.record_order_create`. Não havia notificação externa, apenas log técnico.  
- **Arbitragem executada**: eventos já estruturados via `state.log_event("ARBITRAGE_EXECUTION_SUCCESS", ...)` em `StrategyArbitrageSimple.run_cycle`.  
- **Auth fail pause**: ponto central em `ExchangeClientManager.mark_auth_failed_and_pause`, já com pausa/inativação de credencial e log `EXCHANGE_AUTH_FAILED_PAUSED`.  
- **WS fallback/degradação**: no circuito `MarketDataService._run_stream`, já existem logs `MARKETDATA_WS_STALE_DETECTED` e `MARKETDATA_FALLBACK_TO_POLL`.  
- **Kill switch**: bloqueio no `RiskPolicy.evaluate` via regra `KILL_SWITCH` com eventos `RISK_KILL_SWITCH_ACTIVE`.

## Infra reutilizável identificada

- **Eventos estruturados**: `StateStore.log_event` e `risk_events` já guardam payload JSON por evento.
- **Config por tenant**: base já multi-tenant com `tenants`, `exchange_credentials`, APIs com `tenantId` + RBAC (`api/auth.py`, `exchange_credentials_api.py`).
- **Criptografia existente**: `security.crypto.encrypt_secret/decrypt_secret` (AES-GCM) já usada para credenciais.
- **Redaction**: utilitário `security.redaction` disponível.

## Pontos ideais de integração do NotificationService

1. `OrderManager._create_quantized` → disparar `ORDER_EXECUTED`.
2. `StrategyArbitrageSimple.run_cycle` em sucesso → disparar `ARBITRAGE_EXECUTED`.
3. `ExchangeClientManager.mark_auth_failed_and_pause` → disparar `AUTH_FAILED`.
4. `MarketDataService._run_stream` no fallback para polling → disparar `WS_DEGRADED`.
5. `RiskPolicy._block` quando `rule_type=KILL_SWITCH` → disparar `KILL_SWITCH_ACTIVATED`.

## Estratégia de armazenamento das novas configurações

- Nova tabela `notification_settings` no mesmo `state.db`.
- Coluna sensível `webhook_url` armazenada criptografada com `security.crypto`.
- Endpoints tenant-scoped em `/api/tenants/{tenantId}/notifications/*` com RBAC igual ao padrão existente.

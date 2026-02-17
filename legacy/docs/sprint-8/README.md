# Sprint 8 — Gestão de Risco Fechada

## Arquitetura
- `RiskPolicy` centraliza todas as validações antes de envio de ordens.
- `OrderRouter`, `OrderManager` e `StrategyArbitrageSimple` chamam `RiskPolicy.evaluate(orderIntent)`.
- Toda decisão é persistida em `risk_events` e também em `event_log`.

## Ordem de validação
1. Kill switch global
2. Kill switch por par
3. Máximo % do saldo por operação (`max_percent_per_trade`)
4. Máximo absoluto por operação (`max_absolute_per_trade`)
5. Máximo de ordens abertas por símbolo (`max_open_orders_per_symbol`)
6. Máxima exposição por símbolo (`max_exposure_per_symbol`)

## Configuração de limites
Campos por par (`config_pairs` / `/api/bot-config`):
- `max_percent_per_trade`
- `max_absolute_per_trade`
- `max_open_orders_per_symbol`
- `max_exposure_per_symbol`
- `kill_switch_enabled`

## Bloqueios
- Endpoint: `GET /api/tenants/{tenantId}/risk/events?symbol=BTC/USDT`
- `rule_type`: `MAX_PERCENT`, `MAX_ABSOLUTE`, `MAX_OPEN_ORDERS`, `MAX_EXPOSURE`, `KILL_SWITCH`
- Eventos estruturados: `RISK_CHECK_PASSED`, `RISK_CHECK_BLOCKED`, `RISK_KILL_SWITCH_ACTIVE`, `RISK_EXPOSURE_EXCEEDED`, `RISK_MAX_PERCENT_EXCEEDED`

## Boas práticas
- Começar com limites conservadores (baixo %/trade e exposição).
- Ativar kill switch por par para manutenção operacional.
- Monitorar tabela de bloqueios e ajustar limites progressivamente.

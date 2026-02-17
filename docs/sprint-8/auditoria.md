# Sprint 8 — Auditoria de Gestão de Risco

## O que já existe
- Stake por par em `OrderRouter._stake_for` e sizing com `risk_percentage` em `OrderRouter._calc_position_size`. 
- Limite de ordens e exposição em `RiskManager` (`can_open_more_for`, `exposure_ok_for`).
- Kill switch global em `bot_global_config.kill_switch_enabled` aplicado no loop do monitor e na estratégia de arbitragem.
- Criação de ordens em múltiplos pontos:
  - `OrderRouter._create_limit_order_safe`
  - `OrderManager._create_quantized`
  - `StrategyArbitrageSimple._submit_leg`

## Duplicações e gaps
- Regras de risco espalhadas entre `RiskManager`, `StrategyArbitrageSimple`, `MainMonitor` e validações locais.
- Existia bypass: `StrategyArbitrageSimple` e `OrderManager` podiam enviar ordem sem uma política única obrigatória.
- Não havia persistência estruturada de eventos de bloqueio por regra financeira.

## Consolidação proposta (Sprint 8)
- Introduzir `core/risk_policy.py` com `RiskPolicy.evaluate(orderIntent)` como ponto único.
- Integrar `RiskPolicy` antes de qualquer `create_limit_order` nos 3 caminhos de criação.
- Persistir decisões em `risk_events` com `BLOCKED|ALLOWED`.
- Expandir `config_pairs` com limites financeiros padronizados.

## Enforcement obrigatório
Fluxo consolidado:

`Strategy/Router/OrderManager -> RiskPolicy.evaluate -> ExchangeHub.create_limit_order`

Sem aprovação da RiskPolicy, a ordem não é enviada.

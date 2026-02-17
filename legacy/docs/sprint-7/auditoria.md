# Sprint 7 — Auditoria Técnica

## O que já existe
- Estratégia principal ativa: `StrategySpread`, executada no `MainMonitor` por par (`config_pairs.strategy`).
- Multi-exchange já existe no `ExchangeHub` (market data/order routing/saldos).
- Risk policy centralizada em `RiskManager` com limites de exposição e ordens abertas.
- Idempotência da Sprint 5 já implementada via `StateStore.get_or_create_order_intent` + índice único (`tenant_id, exchange, client_order_id`) e integração no `OrderRouter`.
- Paper mode já integrado no `ExchangeHub.create_limit_order` (retorna ordens `paper_*`).
- MarketData Sprint 6 já integrada: `ExchangeHub.get_orderbook_meta/get_orderbook` usam `MarketDataService` (WS + fallback polling).

## Reaproveitamento planejado
- Reuso de market data: `ExchangeHub.get_orderbook_meta` para best bid/ask por exchange.
- Reuso de idempotência: mesma infraestrutura de `clientOrderId` determinístico e dedupe no `StateStore`.
- Reuso de risco: `RiskManager.can_open_more_for` e `RiskManager.exposure_ok_for`.
- Reuso de configuração por par: `config_pairs.strategy` continua selecionando executor por símbolo.

## O que será criado na Sprint 7
- `StrategyArbitrageSimple` dedicada para detecção + execução segura em duas pernas.
- Storage dedicado:
  - `arbitrage_config` (config por par/tenant)
  - `arbitrage_state` (status: oportunidade, execução, runtime_state)
- Endpoints API para configuração/status da arbitragem.
- UI no dashboard para configurar e visualizar arbitragem por par.
- Testes unitários e de integração mockada da estratégia de arbitragem.

## Riscos identificados
- **Partial execution** em live (1ª perna ok, 2ª falha): mitigado com estado `PARTIAL` + evento crítico.
- **Conflito entre strategies**: mitigado por lock `(tenant,symbol)` e seleção explícita por `config_pairs.strategy`.
- **Latência/obsolescência de book**: mitigado pelo uso de MarketData com `state/source/age` já existente e cooldown.
- **Retry duplicando ordens**: mitigado por idempotência obrigatória em cada perna.

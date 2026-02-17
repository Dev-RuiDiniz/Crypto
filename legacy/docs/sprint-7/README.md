# Sprint 7 — StrategyArbitrageSimple (MVP)

## Como funciona
A `StrategyArbitrageSimple` avalia duas exchanges por par e executa arbitragem quando:

`bestAsk(A) + fees < bestBid(B) - slippage - thresholds`

Ela avalia as duas direções (A→B e B→A), escolhe a melhor oportunidade válida e aplica:
- threshold absoluto
- threshold percentual
- validação de saldo
- validação de risco
- idempotência por perna
- cooldown por par

## Configuração
Use a seção de arbitragem no dashboard (por par):
- enabled
- exchange_a / exchange_b
- threshold_percent
- threshold_absolute
- max_trade_size
- cooldown_ms
- mode: `TWO_LEG | ONE_LEG`
- fee_percent
- slippage_percent

A configuração é persistida em `arbitrage_config`.

## Status
A strategy persiste em `arbitrage_state`:
- `runtime_state`: `IDLE | COOLDOWN | EXECUTING`
- `last_opportunity`
- `last_execution` (`SUCCESS | FAILED | PARTIAL`)
- `last_success_ts`

## Eventos
Eventos emitidos:
- `ARBITRAGE_OPPORTUNITY_DETECTED`
- `ARBITRAGE_EXECUTION_STARTED`
- `ARBITRAGE_EXECUTION_SUCCESS`
- `ARBITRAGE_EXECUTION_PARTIAL`
- `ARBITRAGE_EXECUTION_FAILED`
- `ARBITRAGE_COOLDOWN_ACTIVE`

Todos carregam contexto de `tenantId` e `symbol`.

## Paper vs Live
- **Paper**: ordens simuladas pelo `ExchangeHub` (`paper_*`), mas pipeline e estado completos.
- **Live**: envio real via exchange adapter/CCXT, com `clientOrderId` determinístico e dedupe de retries.

## Riscos
- Latência entre detecção e execução.
- Falha de segunda perna (estado parcial).
- Slippage maior que estimado em mercado volátil.

## Como testar
- Unit: `python -m unittest tests/test_sprint7_arbitrage.py`
- Regressão idempotência: `python -m unittest tests/test_sprint5_idempotency.py`

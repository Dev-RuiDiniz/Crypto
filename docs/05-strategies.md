# 05 - Strategies

## Estratégia atual
`core/strategy_spread.py`:
- Usa referência `MEDIAN`/`VWAP` entre exchanges
- Calcula buy/sell por spread configurado

## Roteamento
`core/order_router.py`:
- `ANCHOR_MODE=LOCAL|REF`
- Reprice com cooldown/banda
- Capacidade por saldo e mínimos

## Gap
- Não há estratégia dedicada de arbitragem simples com execução explícita de duas pernas.

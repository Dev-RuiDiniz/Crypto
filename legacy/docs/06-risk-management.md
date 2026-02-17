# 06 - Risk Management

## Controles existentes
- Limite de ordens abertas por par/exchange
- Limite de exposição bruta (USDT)
- Kill switch por drawdown
- Stake por par (`[STAKE]`)
- Mínimos de notional/quantidade por adapter

## Onde
- `core/risk_manager.py`
- `core/order_router.py`
- `core/order_manager.py`

## Gap para MVP robusto
- Idempotência forte (`clientOrderId` persistente)
- Limite máximo por operação formalizado fim-a-fim

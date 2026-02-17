# 04 - Exchanges

## Camada de integração
`exchanges/exchanges_client.py` centraliza:
- Descoberta de exchanges habilitadas (`[EXCHANGES.*]`)
- Market data por CCXT
- Privadas via CCXT e MB v4 adapter quando aplicável

## Exchanges observadas no config
- Mercado Bitcoin
- NovaDAX
- Gate
- MEXC

## Limitações atuais
- Order book em polling (`fetch_order_book`), sem websocket ativo no fluxo principal.

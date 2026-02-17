# Sprint 6 — Auditoria obrigatória (Order Book “real-time”)

## 1) Worker: estado atual antes da implementação

| Item | Status | Evidência | Observação |
|---|---|---|---|
| `fetch_order_book` no worker | **Existe** | `ExchangeHub.get_orderbook` chamava `ex.fetch_order_book(...)`. | Era polling puro por demanda de chamada. |
| Frequência de polling | **Parcial** | Sem loop dedicado de order book; apenas chamadas dentro do ciclo do monitor/router. | Frequência efetiva dependia de `GLOBAL.LOOP_INTERVAL_MS` e quantidade de pares/exchanges. |
| Consumo do book na strategy/monitor | **Existe** | `StrategySpread._approx_vwap_top` e `OrderRouter._best_ask_usdt/_best_bid_usdt` consumiam via `ex_hub.get_orderbook`. | Não havia metadados de idade/fonte para decisão de fail-safe. |

## 2) Integração de exchanges

| Item | Status | Evidência | Observação |
|---|---|---|---|
| Integração principal | **Existe** | Projeto usa `ccxt.async_support` no `ExchangeHub`. | Rotas privadas do Mercado Bitcoin usam adapter `MBV4Adapter` apenas para privadas. |
| WebSocket de market data | **Não existe** | Não havia provider WS para order book no fluxo do worker. | Apenas polling via CCXT estava ativo. |
| Adapter/camada reutilizável | **Parcial** | `ExchangeHub` já centraliza símbolo, retries e acesso público/privado. | Serviu como ponto de inserção para a nova camada `MarketDataService`. |

## 3) Cache/estado por par

| Item | Status | Evidência | Observação |
|---|---|---|---|
| Cache em memória por `(tenant, exchange, symbol)` | **Parcial** | Havia caches específicos (ex.: saldos no router), mas não cache dedicado de order book com metadata. | Novo `MarketDataService` passa a manter cache O(1) com metadados. |
| Persistência em DB | **Não existe** | Não havia tabela de book em SQLite. | Mantido em memória (intencional para latência). |

## 4) Frontend / API de status

| Item | Status | Evidência | Observação |
|---|---|---|---|
| Tela com pares/exchanges | **Existe** | Dashboard e telas de configuração/exchanges já existiam. | Dashboard passou a exibir status de order book. |
| Status do worker | **Existe** | Endpoints de health/config status e snapshot já disponíveis. | Reaproveitado modelo de snapshot para expor `orderbook_status`. |
| Endpoint específico de market data | **Não existe** | Não havia rota dedicada de status de order book por tenant. | Criado `/api/tenants/{tenantId}/marketdata/orderbook-status`. |

## 5) Pontos de inserção escolhidos

1. **`core/market_data.py`**: camada única de market data (cache + circuito WS/POLL + providers).
2. **`exchanges/exchanges_client.py`**: `get_orderbook` passou a usar cache do MarketData (fallback para polling cru).
3. **`bot.py`**: inicialização e ciclo de vida (`start/stop`) do MarketData.
4. **`core/order_router.py`**: bloqueio fail-safe quando book está stale (`MARKETDATA_STALE_BLOCK`).
5. **`core/monitors.py` + API/Frontend**: publicação e visualização de estado/fonte/idade.

## 6) Exchange WS habilitada na sprint

**Escolha obrigatória:** `mexc`.

Motivo: já está habilitada no config padrão do projeto e possui canal público WS de order book spot adequado para prova de aceite nesta sprint.

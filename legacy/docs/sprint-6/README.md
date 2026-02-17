# Sprint 6 — MarketData em tempo real (WS + fallback polling)

## Arquitetura

A sprint introduz a camada **`MarketDataService`** como fonte única de order book:

- cache em memória por chave `(tenantId, exchange, symbol)`
- leitura única para strategy/router via `ExchangeHub.get_orderbook` / `get_orderbook_meta`
- metadados por snapshot:
  - `timestamp`
  - `source` (`WS` ou `POLL`)
  - `state` (`OK`, `DEGRADED`, `DISCONNECTED`)
  - `seq`
  - `lastError`
  - `ageMs`

## Fallback e recovery

Circuito simples por stream:

1. Estado inicial: `WS_ACTIVE` quando exchange suporta WS (`mexc` nesta sprint), senão `POLL_ACTIVE`.
2. Falha/stale no WS:
   - log `MARKETDATA_WS_STALE_DETECTED`
   - troca para `POLL_ACTIVE`
   - log `MARKETDATA_FALLBACK_TO_POLL`
3. Em polling:
   - atualiza cache periodicamente
   - log `MARKETDATA_POLL_TICK`
4. Reconexão WS periódica:
   - log `MARKETDATA_WS_RECONNECT_ATTEMPT`
   - ao recuperar: `MARKETDATA_WS_RECOVERED`

## Configuração

No `config.txt` / `config.template.txt`:

```ini
[MARKETDATA]
ws_stale_ms = 3000
ws_reconnect_ms = 5000
poll_interval_ms = 2000
orderbook_limit = 20
```

Variáveis de ambiente (sobrescrevem INI):

- `MARKETDATA_WS_STALE_MS`
- `MARKETDATA_WS_RECONNECT_MS`
- `MARKETDATA_POLL_INTERVAL_MS`
- `ORDERBOOK_LIMIT`

## Segurança operacional (fail-safe)

No router, se `ageMs > WS_STALE_MS`, o ciclo bloqueia operação para aquele livro e registra `MARKETDATA_STALE_BLOCK`.

## API / UI

Endpoint novo:

- `GET /api/tenants/{tenantId}/marketdata/orderbook-status?exchange=&symbol=`

Resposta contém apenas estado e top-of-book (sem payload completo de bids/asks).

Dashboard exibe:

- Fonte (`WS`/`POLL`)
- Estado (`OK`/`DEGRADED`/`DISCONNECTED`)
- Idade do book
- Best Bid / Best Ask

## Como validar WS ativo

1. Iniciar worker + API.
2. Verificar logs estruturados:
   - `MARKETDATA_WS_CONNECTED`
   - `MARKETDATA_WS_MESSAGE`
3. Abrir Dashboard e validar coluna **Fonte=WS** com `ageMs` baixo.
4. Simular queda WS e validar mudança para **POLL/DEGRADED**.

## Limitações da sprint

- WS habilitado apenas para **1 exchange** nesta etapa: `mexc`.
- Outras exchanges seguem com polling até novos providers WS serem adicionados.

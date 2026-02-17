# Sprint 10 — Auditoria Final (pré-implementação obrigatória)

## Escopo auditado (Sprints 5 a 9)

1. **Idempotência (Sprint 5)**
   - `OrderRouter` e `StateStore` já possuem dedupe por `client_order_id`.
   - Persistência em `orders` com metadados de dedupe está operacional.
2. **MarketData WS + fallback (Sprint 6)**
   - `MarketDataService` já alterna entre `WS_ACTIVE` e `POLL_ACTIVE` com fallback e reconexão.
   - `MainMonitor` já publica `orderbook_status` no snapshot para API/UI.
3. **Arbitragem (Sprint 7)**
   - `StrategyArbitrageSimple` já usa `RiskPolicy` e estado em `arbitrage_state`.
4. **RiskPolicy (Sprint 8)**
   - Bloqueios centralizados via `RiskPolicy.evaluate` antes de envio de ordens.
5. **NotificationService (Sprint 9)**
   - Eventos críticos já possuem canal de notificação com severidade e configuração por tenant.

## Pontos de falha restantes (não totalmente protegidos)

1. **Falha repetida por exchange sem isolamento operacional**
   - Há pausa por `auth failure` em `ExchangeClientManager`, mas não há *circuit breaker* genérico para falhas de rede/exchange intermitentes no envio de ordem.
2. **Ausência de métrica operacional consolidada em endpoint único**
   - Existem dados espalhados (snapshot, logs, health), mas sem agregação mínima: latência de ciclo, ordens/min, taxa de erro por exchange, estado do circuit breaker e WS.
3. **Dashboard sem status operacional global consolidado**
   - Há painéis de ordens/saldos/market data, mas não há status único RUNNING/DEGRADED/PAUSED com motivo automático.
4. **Go-live checklist inexistente**
   - Não há página dedicada para pré-validação operacional com itens automáticos.

## Exchanges mais suscetíveis a erro (com base na arquitetura atual)

- **mercadobitcoin**: fluxo híbrido MB v4 + fallback CCXT, maior superfície de integração.
- **mexc**: depende de WS para melhor latência e pode entrar em fallback polling.
- **demais CCXT**: sujeitos a timeout/rate limit/intermitência de rede.

## Pontos de inserção recomendados

1. **Circuit breaker**
   - Inserir no ponto único de envio de ordens: `ExchangeHub.create_limit_order(...)`.
   - Escopo por `(tenantId, exchange)` para não interromper o loop completo.
2. **Métricas operacionais**
   - `MainMonitor.run`: registrar latência de ciclo.
   - `ExchangeHub.create_limit_order`: registrar ordens enviadas e erros por exchange.
   - `MainMonitor` + `MarketDataService` snapshot: registrar estado WS.
   - `ExchangeHub`: publicar estado do circuit breaker no snapshot.
3. **API/Frontend operacional**
   - Expor endpoint `/api/tenants/{tenantId}/metrics` via `handlers` lendo snapshot.
   - Computar status global no frontend a partir de métricas + config status.

## Plano de hardening (Sprint 10)

1. Criar `ExchangeCircuitBreaker` com estados `CLOSED|OPEN|HALF_OPEN` e backoff.
2. Integrar o breaker no envio de ordens sem parar o loop inteiro.
3. Criar `MetricsService` in-memory (janela circular), publicar no snapshot e expor API.
4. Criar teste de carga leve multi-par e relatório de estabilidade.
5. Adicionar no frontend:
   - Card de status operacional global.
   - Página de checklist de go-live consumindo API dedicada.
6. Consolidar documentação final de operação e troubleshooting.

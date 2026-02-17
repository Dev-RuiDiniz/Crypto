# Sprint 5 — Auditoria pré-implementação

## 1) Onde ordens são criadas/canceladas/recriadas hoje
- **Ponto principal de criação no fluxo atual**: `OrderRouter._create_limit_order_safe(...)`, chamado por `_reprice_one(...)` durante `reprice_pair(...)`. O envio efetivo acontece por `ExchangeHub.create_limit_order(...)` (ou fallback `ex.create_order`).
- **Cancelamento/recriação**: `_reprice_one(...)` chama `_cancel_side(...)` antes de nova criação quando necessário.
- **Outro caminho legado**: `core/order_manager.py` também chama `ex_hub.create_limit_order`, mas o fluxo ativo do monitor passa pelo `OrderRouter`.

## 2) Retry/backoff existente
- Retry exponencial com jitter está implementado em `ExchangeHub` via `tenacity` (`_get_retry_deco`).
- `create_limit_order`/`cancel_order` aplicam retry para caminhos CCXT.
- Há dedupe **somente em memória e por TTL curto** no router (`_recent_order_hashes` + `_is_duplicate_submit`), sem garantia de restart.

## 3) Conceito de ciclo existente
- Existe `cycle_id` em ordens **paper** (`_record_paper_execution`), com formato temporal.
- No fluxo live não havia `cycle_id` persistido nas ordens reais.
- O loop principal (`MainMonitor.run`) executa por ciclos; reprocessamento do mesmo ciclo não tinha identidade persistente para intents live.

## 4) Modelo/tabela de orders (SQLite) atual
- Tabela `orders` já existe em `StateStore` com colunas básicas (`id`, `ts`, `ex_name`, `pair`, `side`, `symbol_local`, `price_local`, `amount`, `status`).
- Não havia constraint idempotente baseada em `client_order_id`.
- Persistência atual (`record_order_create`) grava depois da criação na exchange, portanto crash entre envio e gravação pode gerar duplicata no retry/restart.

## 5) `clientOrderId` existente
- Há geração parcial em `OrderRouter._build_client_order_id`, porém:
  - usa bucket temporal curto (`time() // 5`),
  - não é persistida transacionalmente,
  - não é base única de dedupe no DB.

## 6) Por que hoje pode duplicar
- Dedupe em memória (TTL) se perde em restart.
- Retry/transiente pode reenviar `create_order` sem trava transacional persistida.
- Não existe `UNIQUE(tenant, exchange, client_order_id)` ativo no schema.
- Criação não faz “reserva de intent” em DB antes do envio para exchange.

## 7) Decisão de implementação (reaproveitamento)
- **Escolha: Opção A (reutilizar `orders`)** para menor impacto.
- Será feita migração evolutiva da tabela existente com:
  - novos campos de idempotência (`tenant_id`, `exchange`, `client_order_id`, `cycle_id`, `dedupe_state`, `exchange_order_id`, etc.),
  - índice/constraint única `UNIQUE(tenant_id, exchange, client_order_id)`.
- O `OrderRouter` será mantido como **ponto único** de criação, mas com fluxo transacional `get_or_create_order_intent` no `StateStore`.

## 8) Plano técnico resumido
1. Adicionar migração SQLite compatível para `orders` + índices/unique.
2. Criar API transacional no `StateStore` para `get_or_create_order_intent` e updates de status.
3. Tornar `clientOrderId` determinístico por intent/ciclo e persistente.
4. Garantir que retry/replay reusem o mesmo registro/ID.
5. Expor `clientOrderId` curto e `dedupe_state` no snapshot/UI.
6. Cobrir com testes de integração (retry, restart, concorrência).

# Sprint 5 — Idempotência real + dedupe transacional

## Objetivo
Eliminar ordens duplicadas em cenários de retry, restart e replay de ciclo usando:
- `clientOrderId` determinístico,
- persistência transacional em SQLite,
- constraint única por tenant/exchange/client_order_id,
- reaproveitamento do fluxo central no `OrderRouter`.

## Como o `clientOrderId` é calculado
No `OrderRouter`, o ID é derivado de hash SHA-256 curto de:
- tenant,
- exchange,
- pair,
- side,
- cycle_id,
- intent (símbolo/qty/preço).

Formato: `COID-<exchange>-<hash12>` (compatível com limites de tamanho).

## Constraints SQLite
A tabela `orders` foi evoluída com campos de idempotência e índices:
- `UNIQUE (tenant_id, exchange, client_order_id)` (índice único parcial),
- índice `(tenant_id, exchange, pair, status)`,
- índice `(tenant_id, exchange, cycle_id)`.

## Fluxo de dedupe
1. Router gera `clientOrderId` determinístico.
2. Chama `StateStore.get_or_create_order_intent(...)` em transação `BEGIN IMMEDIATE`.
3. Se já existe intent ativa (`pending/placed/open`): retorna `REUSED` e **não envia ordem**.
4. Se não existe: cria intent `pending` e envia para exchange.
5. Em sucesso: `mark_order_submitted(...)` atualiza mesmo registro.
6. Em falha: `mark_order_failed(...)` registra erro/retryable sem criar novo registro.

## Reprocessamento pós-restart
Em replay do mesmo ciclo (`cycle_id` igual), o mesmo intent gera o mesmo `clientOrderId`.
A transação encontra o registro existente e bloqueia novo envio (`REUSED`).

## Frontend / observabilidade
A lista de ordens no dashboard agora exibe:
- `ClientOrderId` curto,
- badge de dedupe (`NEW`, `REUSED`, `BLOCKED`).

## Como rodar os testes da sprint
```bash
python -m unittest tests/test_sprint5_idempotency.py
```

## Como verificar no log
Procure por mensagens do router contendo:
- `dedupe_state=REUSED skip create ... coid=<short>`
- `duplicate submit prevented ...`

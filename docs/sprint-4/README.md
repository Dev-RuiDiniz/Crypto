# Sprint 4 — Hot Reload de credenciais (Worker)

## Visão geral

A Sprint 4 adiciona rotação segura de client de exchange sem restart do worker, baseada em:

1. `CredentialProvider` para leitura de credencial ativa por `tenantId + exchange`.
2. Cache de client por chave `${tenantId}:${exchange}` com metadados de versão/estado.
3. Polling por ciclo no início do loop do monitor.
4. Rotação segura com mutex por exchange e lock curto de operação.
5. Classificação de erro de autenticação e pausa da exchange.

## Componentes

- `core/credential_provider.py`
  - Contrato interno para retornar `credentialId`, `version`, segredos, `status`, `updatedAt`.
- `core/exchange_client_manager.py`
  - `ExchangeClientFactory` (criação única de client)
  - `ExchangeClientManager` (cache + rotação + lock + pause flow)
  - `AuthErrorClassifier`
- `exchanges/exchanges_client.py`
  - Integra manager no fluxo de ordens/saldo/open orders.
- `core/monitors.py`
  - No início de cada ciclo, valida/atualiza client de cada exchange habilitada.
- `core/order_router.py`
  - Idempotência mínima com `clientOrderId` determinístico + hash de envio com TTL.

## Como funciona o monitoramento de version

1. Início do ciclo (`MainMonitor.run`): chama `ensure_client_ready` por exchange.
2. O manager lê credencial ativa atual.
3. Compara `version` da credencial vs cache.
4. Se mudou:
   - adquire mutex do par `(tenantId, exchange)`
   - revalida versão
   - marca `ROTATING`
   - cria novo client via factory
   - faz swap no cache
   - fecha client antigo
   - marca `READY`
   - gera logs estruturados de rotação

## Como validar hot reload (passo a passo)

1. Inicie API + worker com uma credencial ativa (ex.: `version=1`).
2. Verifique logs: `CLIENT_CACHE_HIT`/`MISS` e operação normal.
3. Atualize credencial via dashboard/API (rotação de segredo aumenta `version`).
4. Aguarde próximo ciclo do worker.
5. Verifique logs:
   - `EXCHANGE_CLIENT_ROTATION_DETECTED`
   - `EXCHANGE_CLIENT_ROTATED`
6. Confirme que não houve restart de processo e que ordens continuam fluindo.

## Fluxo de falha de autenticação

Quando uma chamada privada recebe erro classificado como autenticação:

1. `AuthErrorClassifier` marca como auth failure.
2. Worker marca a credencial como `INACTIVE` (fallback compatível com API atual).
3. Cache da exchange entra em estado de pausa/failed.
4. Log estruturado de alerta: `EXCHANGE_AUTH_FAILED_PAUSED` com tag `ALERT_AUTH_FAILED`.
5. Execução daquela exchange fica bloqueada até credencial válida voltar.

## Como identificar rotação nos logs

Eventos mínimos registrados:

- `CLIENT_CACHE_HIT`
- `CLIENT_CACHE_MISS`
- `EXCHANGE_CLIENT_ROTATION_DETECTED`
- `EXCHANGE_CLIENT_ROTATED`
- `EXCHANGE_CLIENT_ROTATION_FAILED`
- `EXCHANGE_AUTH_FAILED_PAUSED`
- `EXCHANGE_RESUMED`

## Limitações atuais

- Detecção por **polling no início do ciclo** (não event-driven).
- Sem integração direta com canal externo (Slack/email) para alertas; alerta é log estruturado.
- `status=INVALID` não existe no contrato atual da API; fallback aplicado para `INACTIVE`.

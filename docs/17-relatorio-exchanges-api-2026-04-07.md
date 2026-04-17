# Relatorio Tecnico de Exchanges e Fluxo de Dados

Data: 2026-04-07
Repositorio: https://github.com/Dev-RuiDiniz/Crypto
Escopo: como cada exchange funciona no sistema e como a API do projeto recebe e envia dados.

## 1) Visao geral do fluxo

1. Frontend chama API Flask (`api/server.py`).
2. API grava/le credenciais e status em SQLite via `ExchangeCredentialsService` (`core/credentials_service.py`).
3. Worker (`bot.py` + `core/monitors.py`) usa `ExchangeHub` (`exchanges/exchanges_client.py`) para operar nas exchanges.
4. Dados de mercado e ordens sao consolidados em snapshot (`api/shared_state.py` + `data/api_snapshot.json`).
5. API devolve snapshot para frontend em endpoints como `/api/mids`, `/api/orders`, `/api/balances`.

## 2) Exchanges suportadas no codigo

Suporte operacional principal (worker + roteamento):
- `mercadobitcoin`
- `novadax`
- `gateio` (alias: `gate`)
- `mexc` (alias: `mexc3`)

Suporte no fluxo de cadastro/teste de credenciais (API):
- `binance`
- `bybit`
- `okx`
- `kucoin`

Referencia de validacao: `api/exchange_credentials_api.py` (`ALLOWED_EXCHANGES`).

## 3) Como a API recebe e envia dados (interno do projeto)

### 3.1 Credenciais (entrada pela API)
Endpoints principais:
- `POST /api/tenants/<tenantId>/exchange-credentials`
- `PUT /api/tenants/<tenantId>/exchange-credentials/<id>`
- `POST /api/tenants/<tenantId>/exchange-credentials/<id>/test`
- `GET /api/tenants/<tenantId>/exchanges/status`

Recebe do cliente:
- `exchange`, `label`, `apiKey`, `apiSecret`, `passphrase`

Processamento:
- Valida exchange permitida.
- Criptografa segredos (`security/crypto.py`) e salva em `exchange_credentials`.
- Atualiza status em `exchange_status`.
- Teste de credencial executa probe real via CCXT:
  - `load_markets`
  - `fetch_balance` (ou `fetch_time`)
  - probe privado (`fetch_open_orders` ou `fetch_orders` ou `fetch_my_trades`)

Resposta para cliente:
- sucesso: `ok`, `latencyMs`, `probeMethod`, `probeSymbol`
- erro classificado: `AUTH_FAILED`, `PERMISSION_DENIED`, `TIMESTAMP_WINDOW`, `TIMEOUT`, etc.

### 3.2 Dados de mercado e ordens (saida para frontend)
Origem dos dados:
- worker publica snapshot em memoria com `set_snapshot(...)`.
- fallback em arquivo `data/api_snapshot.json`.

API entrega para frontend:
- `/api/mids`: mids por exchange/par
- `/api/orders`: ordens abertas/pendentes/fechadas (normalizado)
- `/api/balances`: saldos consolidados por exchange
- `/api/health/worker`: status de heartbeat do worker

## 4) Relatorio por exchange

## 4.1 Mercado Bitcoin (`mercadobitcoin`)
Como funciona no sistema:
- Publico (ticker/orderbook): via CCXT (como nas demais).
- Privado (saldo/ordens): preferencialmente via `MBV4Adapter` (API v4 nativa), com fallback para CCXT.

Como enviamos dados para a exchange:
- Autenticacao privada v4:
  - `POST /oauth2/token` com `grant_type=client_credentials`, `client_id` e `client_secret` (quando nao ha bearer valido).
- Descoberta de conta:
  - `GET /api/v4/accounts`
- Saldo:
  - `GET /api/v4/accounts/{accountId}/balances`
- Criacao de ordem limitada:
  - `POST /api/v4/accounts/{accountId}/{BASE-QUOTE}/orders`
  - body enviado: `qty`, `side`, `type=limit`, `limitPrice`
  - preco e arredondado para 2 casas (step 0.01 em BRL).
- Cancelamento:
  - `DELETE /api/v4/accounts/{accountId}/{BASE-QUOTE}/orders/{orderId}`
- Consulta de abertas:
  - `GET /api/v4/accounts/{accountId}/{symbol}/orders?status=working`
  - ou `GET /api/v4/accounts/{accountId}/orders?status=working`

Como recebemos dados da exchange:
- Saldos sao normalizados para formato padrao:
  - `{ "free": {ASSET: valor}, "used": {ASSET: valor} }`
- Ordens v4 sao normalizadas para formato semelhante a CCXT:
  - `id`, `symbol`, `side`, `price`, `amount`, `status`, `info`.

Observacao operacional:
- Se MB v4 falhar em operacoes privadas, sistema tenta fallback CCXT quando disponivel.

## 4.2 NovaDAX (`novadax`)
Como funciona no sistema:
- Integracao por CCXT (publico e privado).

Como enviamos dados para a exchange:
- Criacao de ordem: `create_order(symbol, "limit", side, amount, price, params)`
- Cancelamento: `cancel_order(order_id, symbol)` (com fallback sem symbol)
- Consulta abertas: `fetch_open_orders(symbol)` (ou global)
- Saldo: `fetch_balance()`

Como recebemos dados da exchange:
- Market data: `fetch_ticker`, `fetch_order_book`
- Saldos e ordens no formato CCXT, consumidos diretamente e normalizados no snapshot.

Mapeamento de simbolo:
- Pairs BRL sao comuns (ex.: `BTC/BRL`, `VISTA/BRL`).

## 4.3 Gate.io (`gateio` / alias `gate`)
Como funciona no sistema:
- Integracao por CCXT.
- Alias suportado nos dois sentidos para compatibilidade de naming.

Como enviamos dados para a exchange:
- Mesma trilha CCXT de ordens/saldo/cancelamento/abertas.

Como recebemos dados da exchange:
- `fetch_ticker`, `fetch_order_book`, `fetch_balance`, `fetch_open_orders`.

Mapeamento de simbolo:
- Normalmente pares em USDT (ex.: `BTC/USDT`, `VISTA/USDT`).

## 4.4 MEXC (`mexc` / alias `mexc3`)
Como funciona no sistema:
- Integracao por CCXT para privado e para fallback de market data.
- Integracao WS dedicada para orderbook em `core/market_data.py`.
- Hardening adicional documentado em `docs/19-mexc-hardening-2026-04-09.md`.

Como enviamos dados para a exchange:
- CCXT para ordens/saldo/cancelamento.
- Politica MEXC centralizada para reduzir erros de timestamp:
  - `recvWindow=60000`
  - referencia de horario em `GET /api/v3/time`
  - telemetria de `timeDifferenceMs`, horario UTC e bucket por hora
  - classificacao especifica para `TIMESTAMP_WINDOW`, `PERMISSION_DENIED`, `ACCOUNT_MODE_MISMATCH` e `IP_RESTRICTED`

Como recebemos dados da exchange:
- Preferencialmente WS:
  - `wss://wbs-api.mexc.com/ws`
  - canal `spot@public.limit.depth.v3.api.pb@<SYMBOL>@<DEPTH>`
  - mensagens binarias protobuf parseadas para `bids/asks`
  - heartbeat ativo com ping a cada 20s
- Se WS falhar/stale:
  - fallback automatico para polling via `fetch_order_book`
  - tentativa de reconexao WS apos janela configurada

## 4.5 Binance (`binance`)
Status no projeto:
- Presente no cadastro/teste de credenciais da API.
- Nao aparece habilitada no config padrao desta entrega para execucao do worker.

Teste de credencial:
- Probe CCXT igual as demais:
  - `load_markets` + `fetch_balance` + probe privado de ordens/trades.

## 4.6 Bybit (`bybit`)
Status no projeto:
- Presente no cadastro/teste de credenciais da API.
- Nao habilitada no fluxo operacional padrao desta entrega.

Teste de credencial:
- Mesmo fluxo CCXT de validacao tecnica.

## 4.7 OKX (`okx`)
Status no projeto:
- Presente no cadastro/teste de credenciais da API.
- Nao habilitada no fluxo operacional padrao desta entrega.

Teste de credencial:
- Mesmo fluxo CCXT de validacao tecnica.

## 4.8 KuCoin (`kucoin`)
Status no projeto:
- Presente no cadastro/teste de credenciais da API.
- Nao habilitada no fluxo operacional padrao desta entrega.

Teste de credencial:
- Mesmo fluxo CCXT de validacao tecnica.

## 5) Regras de resiliencia relevantes

- Circuit breaker por exchange em `ExchangeHub`.
- Retry com backoff exponencial nas chamadas de rede.
- Pausa automatica de credencial quando erro de autenticacao e detectado (`ExchangeClientManager.mark_auth_failed_and_pause`).
- Notificacao interna para eventos criticos (auth fail, ws degraded, circuit breaker).

## 6) Situacao atual de habilitacao (config local desta entrega)

Arquivo: `config.windows.local.txt`
- `novadax`: enabled=true
- `mercadobitcoin`: enabled=false
- `gate`: enabled=false
- `mexc`: enabled=false

Observacao:
- Mesmo com `enabled=false` na secao, uma exchange pode entrar no runtime se existir credencial `ACTIVE` com ultimo teste OK em `exchange_status`.

## 7) Arquivos de referencia

- `api/exchange_credentials_api.py`
- `core/credentials_service.py`
- `core/exchange_client_manager.py`
- `core/market_data.py`
- `core/monitors.py`
- `exchanges/exchanges_client.py`
- `exchanges/adapters.py`
- `api/shared_state.py`
- `api/handlers.py`

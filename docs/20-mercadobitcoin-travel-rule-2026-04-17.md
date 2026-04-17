# Mercado Bitcoin - Travel Rule e Wallet v4

Data: 2026-04-17

## Motivo da correcao

O Mercado Bitcoin informou que, a partir de 2026-05-01:

- saques de criptoativos sem `travel_rule` no endpoint `Withdraw Coin` serao rejeitados;
- depositos pendentes exigirao envio posterior dessas informacoes pelo endpoint `Release Pending Deposit`.

## O que foi ajustado no codigo

- O `MBV4Adapter` ganhou suporte explicito para:
  - `list_deposits(...)` com filtro `pending_travel_rule`;
  - `release_pending_deposit(...)` via `PATCH /accounts/{accountId}/wallet/{symbol}/deposits/{depositId}`;
  - `withdraw(...)` via `POST /accounts/{accountId}/wallet/{symbol}/withdraw`.
- Foi criada uma camada de normalizacao em `utils/mb_travel_rule.py` para:
  - normalizar `wallet/{symbol}` usando o ativo base;
  - validar `travel_rule` de saque;
  - validar `travel_rule` de deposito.
- O utilitario `MB.py` passou a expor os mesmos blocos conceituais para diagnostico local.
- O `swagger.yaml` do repositorio foi sincronizado com a referencia mais nova, incluindo:
  - `travel_rule` em `WithdrawCoinRequest`;
  - `TravelRuleWithdrawRequest`;
  - `TravelRuleDepositRequest`;
  - filtro `pending_travel_rule` em `List Deposits`;
  - endpoint `Release Pending Deposit`.

## Regras aplicadas

- Para `wallet/{symbol}`, o adapter usa o ativo puro:
  - `BTC/BRL` -> `BTC`
  - `BTC-BRL` -> `BTC`
  - `BRL` -> `BRL`
- Em saques de cripto:
  - se `travel_rule` existir, ele e normalizado;
  - se nao existir e a vigencia regulatoria ja estiver ativa, a chamada falha cedo com erro claro.
- Em depositos pendentes:
  - o payload de liberacao passa por validacao propria de deposito.

## Limites e observacoes

- O bot continua recomendado para chaves `trade-only`; operacoes de wallet devem ser habilitadas apenas quando houver processo operacional claro.
- A validacao local tenta ser segura sem impor regras alem do que a documentacao atual deixa claro.
- Campos condicionais mais especificos de Travel Rule ainda dependem do caso operacional concreto do cliente.

## Validacao

- Novo teste automatizado em `tests/test_mb_v4_adapter.py`.
- Cobertura principal:
  - normalizacao do simbolo de wallet;
  - filtro `pending_travel_rule` em depositos;
  - liberacao de deposito pendente;
  - exigencia de `travel_rule` em saque cripto;
  - montagem do payload de saque com `travel_rule`.

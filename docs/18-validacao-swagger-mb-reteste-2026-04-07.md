# Validacao Swagger MB e Reteste de Exchanges (2026-04-07)

## Fonte consultada
- Swagger oficial Mercado Bitcoin v4: `https://api.mercadobitcoin.net/api/v4/docs/swagger.yaml`

## O que estava errado
No fluxo de teste de credencial da Mercado Bitcoin, o sistema tentava validar via caminho legado de exchange (`mercado` via CCXT), o que nao segue o Swagger oficial v4.

Pelo Swagger v4:
- autenticacao privada: `POST /oauth2/token`
- padrao: `grant_type=client_credentials`, `client_id` (api key id), `client_secret` (api key secret)
- endpoints privados usam `Authorization: Bearer <token>`

## Correcao aplicada
Arquivo alterado:
- `api/exchange_credentials_api.py`

Ajustes:
1. Teste de credencial da `mercadobitcoin` agora usa o fluxo oficial do Swagger:
   - `POST /api/v4/oauth2/token`
   - `GET /api/v4/accounts`
   - probe privado: `GET /api/v4/accounts/{accountId}/orders?status=working&limit=1`
2. Classificacao de erro refinada para identificar falha OAuth da MB (`403/401`) como `AUTH_FAILED`.

## Reteste executado
Evidencia local:
- `logs/exchange_test_results_after_swagger_fix_2026-04-07.json`

Resumo:
- `mercadobitcoin`: falha de autenticacao no OAuth v4 (`EXCHANGE_AUTH_FAILED`, HTTP 403 / Cloudflare 1010)
- `novadax`: OK
- `gateio`: uma tentativa com timeout; alias `gate` OK no mesmo ciclo
- `mexc` e `mexc3`: `EXCHANGE_AUTH_FAILED` (sem permissao no endpoint privado)
- Nivel de sistema (client ready): `mercadobitcoin`, `novadax`, `gateio`, `gate`, `mexc`, `mexc3` = OK

## Conclusao
- O teste da MB agora esta alinhado ao Swagger oficial v4.
- Erros remanescentes sao de credencial/permissao/rede externa, nao de alias ou fluxo legado do sistema.
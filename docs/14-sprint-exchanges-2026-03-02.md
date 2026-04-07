# Sprint 14 - Integracao de Exchanges (2026-03-02)

## Objetivo
Atualizar o projeto para suportar e expor no fluxo de credenciais as exchanges:
- Gate.IO
- MEXC
- NovaDAX
- Mercado Bitcoin

## Escopo implementado
1. Backend/API:
- Lista de exchanges permitidas expandida em `api/exchange_credentials_api.py`.
- Suporte a aliases no teste de conexao de credenciais:
  - `gateio` <-> `gate`
  - `mexc` <-> `mexc3`
  - `mercadobitcoin` <-> `mercado`

2. Core de clientes de exchange:
- Resolvedor de candidatos CCXT atualizado em:
  - `core/exchange_client_manager.py`
  - `exchanges/exchanges_client.py`
- Compatibilidade aumentada para diferencas de naming entre versoes de ccxt.

3. Frontend:
- Seletor de exchanges atualizado em `frontend/src/components/ExchangesSettings.js`.
- Exchanges novas expostas para cadastro de credenciais:
  - `gateio`, `mexc`, `novadax`, `mercadobitcoin`.

4. Documentacao:
- Contrato OpenAPI atualizado em `docs/openapi.yaml` (enum de `exchange`).
- Guia de configuracao atualizado em `docs/03-configuration.md`.

## Validacao executada
### Check 1: compilacao de sintaxe Python
Comando:
```powershell
.\.venv-client\Scripts\python.exe -m py_compile `
  api\exchange_credentials_api.py `
  core\exchange_client_manager.py `
  exchanges\exchanges_client.py
```
Resultado: OK

### Check 2: smoke test de aliases/validacao
Comando:
```powershell
.\.venv-client\Scripts\python.exe -c "from api.exchange_credentials_api import ALLOWED_EXCHANGES; from core.exchange_client_manager import _ccxt_id_candidates as m; from exchanges.exchanges_client import _ccxt_id_candidates as h; print('novadax' in ALLOWED_EXCHANGES, 'gateio' in ALLOWED_EXCHANGES, 'mercadobitcoin' in ALLOWED_EXCHANGES); print(m('gateio')); print(m('gate')); print(h('gateio')); print(h('gate')); print(h('mexc3'));"
```
Resultado esperado/obtido:
- `ALLOWED_EXCHANGES` contem `gateio`, `mexc`, `novadax`, `mercadobitcoin`.
- candidatos para `gateio/gate` retornam `['gate', 'gateio']`.
- candidatos para `mexc3` retornam `['mexc', 'mexc3']`.

## Riscos e observacoes
- A validacao foi estrutural/funcional local. Nao houve envio de ordens live para exchanges reais.
- Para operacao real, e necessario cadastrar credenciais validas via tela/API e executar teste de conexao por exchange.

## Conclusao
Sprint concluida com suporte integrado e validado para Gate.IO, MEXC, NovaDAX e Mercado Bitcoin no fluxo de credenciais, resolucao de clientes e documentacao tecnica.

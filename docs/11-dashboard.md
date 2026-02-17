# 11 - Dashboard

## Estrutura
- `frontend/src/App.js` monta tabs e fluxo principal.
- Componentes: `Dashboard`, `Config`, `Orders`, `Balances`, `ExchangesSettings`.

## Capacidades
- Visualização de mids, ordens e saldos.
- Edição de configuração global/par/risco.
- Gestão de credenciais (metadados + rotação/revogação).

## Segurança
- Segredos não são exibidos; apenas `last4` e status.

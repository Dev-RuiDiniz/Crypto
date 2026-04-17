# ARBIT - Plataforma de Trading Cripto

ARBIT e um sistema de trading cripto com worker assincro, API Flask, dashboard web e suporte a operacao em `PAPER` e `LIVE`. O projeto foi estruturado para configurar credenciais, mapear pares por exchange, aplicar regras de spread/arbitragem e acompanhar a operacao por uma interface local.

## O que o sistema faz

- Opera multiplos pares com estrategia de spread parametrizada por par.
- Suporta arbitragem simples entre exchanges.
- Mantem regras centrais de risco, kill switch e circuit breaker por exchange.
- Consolida saldos, ordens, mids e status de mercado para a UI.
- Permite cadastro e teste de credenciais por tenant.
- Trabalha com market data via WebSocket quando disponivel, com fallback para polling.
- Persiste configuracao operacional e estado em SQLite local.

## Arquitetura resumida

```text
Frontend / Electron
        -> API Flask (api/server.py)
              -> handlers + servicos de credenciais/notificacoes
                    -> Worker assincro (bot.py)
                          -> MainMonitor
                          -> StrategySpread / StrategyArbitrageSimple
                          -> OrderRouter / OrderManager / Portfolio
                          -> RiskManager / circuit breaker
                          -> ExchangeHub + MarketDataService
                          -> SQLite + logs + snapshot
```

## Como o sistema funciona ponta a ponta

1. O operador sobe o sistema por `python run_arbit.py` ou pelo launcher de Windows.
2. O `run_arbit.py` inicia o worker (`bot.py`) em background e depois sobe a API Flask.
3. O frontend consome a API em `http://127.0.0.1:8000`.
4. A API le e grava configuracoes, credenciais, status, catalogos e snapshots.
5. O worker conecta nas exchanges habilitadas, inicia market data, aplica risco e executa a estrategia.
6. O frontend exibe saude, ordens, saldos, configuracoes por par e controles operacionais.

## Modos de operacao

- `PAPER`: simula a operacao e deve ser o modo padrao para validacao.
- `LIVE`: envia ordens reais para a exchange.

Importante: o repositorio ainda contem configuracoes legadas em arquivo INI. O fluxo recomendado hoje e usar a UI/API para credenciais, pares, regras e operacao, e deixar `LIVE` apenas depois de validar tudo em `PAPER`.

## Exchanges no codigo

Suporte operacional principal no worker:

- `mercadobitcoin`
- `novadax`
- `gateio` / `gate`
- `mexc`

Suporte no fluxo de cadastro e teste de credenciais:

- `binance`
- `bybit`
- `okx`
- `kucoin`

## Telas principais

As telas atuais do frontend ficam em `frontend/src/components` e estao organizadas em cinco areas principais:

### 1. Fluxo Rapido

Arquivo principal: `frontend/src/components/QuickStartFlow.js`

- Cadastro e teste de credencial.
- Definicao do par e mapeamento por exchange.
- Configuracao simples de spread, stake e risco.
- Botoes diretos para alternar entre `PAPER` e `LIVE`.
- Resumo rapido com health da API, worker, exchange e mid do par.

### 2. Estrategia por Par

Arquivo principal: `frontend/src/components/PairAutomationSettings.js`

- Cadastro de regras `BUY_PCT` e `SELL_PCT` por par.
- Ajuste de parametros de repricing do roteador.
- Listagem e remocao das regras existentes.

### 3. Moedas e Pares

Arquivo principal: `frontend/src/components/AssetsPairsSettings.js`

- Cadastro de moedas operacionais.
- Mapeamento do par global para simbolos locais por exchange.
- Ativacao/inativacao e remocao de mapeamentos.

### 4. Exchanges

Arquivos principais:

- `frontend/src/components/ExchangesSettings.js`
- `frontend/src/components/ExchangesStatus.js`

Permite:

- Criar, rotacionar, testar e revogar credenciais.
- Visualizar status, versao, ultimo teste e atualizacao por exchange.
- Aplicar regras de seguranca para chaves `trade-only`.

### 5. Operacao / Centro de Controle

Arquivos principais:

- `frontend/src/components/ControlCenter.js`
- `frontend/src/components/Dashboard.js`
- `frontend/src/components/MarketCatalog.js`

Permite:

- Ver saude da API, worker, banco e sincronismo de configuracao.
- Alternar modo, kill switch, loop e pares em operacao.
- Ver catalogo de mercados e adicionar pares ao bot.
- Acompanhar ordens, saldos, mids, market data e status operacional.

## Estado atual do repositorio

Leitura consolidada em 17/04/2026:

- Versao declarada da aplicacao: `0.1.0-sprint0` (`app/version.py`).
- O launcher `run_arbit.py` esta preparado para iniciar worker + API + abrir o navegador automaticamente.
- O frontend atual e uma UI simplificada em React sem build complexo obrigatorio para dev local, servida pela API Flask.
- A trilha documental em `docs/` cobre arquitetura, setup, risco, operacao, auditorias e relatorios de exchange.
- O projeto ainda carrega uma camada legada de configuracao por `config.txt`, mas a operacao mais nova passa pela API e pelo dashboard.

Observacoes relevantes de runtime/local:

- O snapshot versionado mais recente indicava ambiente em `PAPER`, sem ordens, saldos ou exchanges ativas no momento da captura.
- O preset local de Windows estava com exchanges desabilitadas, o que sugere estado seguro de bancada/local.
- O `config.txt` da raiz ainda representa um cenario legado/exemplo mais agressivo, incluindo `mode = REAL`; por isso nao deve ser tratado como configuracao pronta para producao.

## Estrutura do repositorio

```text
api/         API Flask e endpoints operacionais
app/         utilitarios de bootstrap, pathing e versao
core/        estrategia, risco, monitor, estado e servicos principais
exchanges/   integracoes e hub de exchanges
frontend/    interface web/Electron
security/    criptografia e tratamento de segredos
tests/       testes Python
docs/        documentacao funcional e tecnica
legacy/      materiais e referencias antigas
scripts/     automacoes de apoio
data/        runtime local (nao deve ser versionado)
logs/        logs locais (nao deve ser versionado)
```

## Como rodar

### Windows

```powershell
./EXECUTAR_TRADINGBOT.ps1
```

ou

```bat
EXECUTAR_TRADINGBOT.bat
```

### Manual

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_arbit.py
```

A API sobe em `http://127.0.0.1:8000`.

## Frontend

O frontend fica em `frontend/` e tambem possui empacotamento Electron. Para testes JS atuais:

```powershell
cd frontend
npm test
```

## Configuracao

Arquivos relevantes:

- `config.txt`: configuracao legada/base do worker.
- `config.template.txt`: template generico.
- `config.windows.local.example.txt`: exemplo de configuracao local para Windows.
- `config.windows.local.txt`: copia local do operador, mantida fora do Git.

Configuracoes sensiveis e operacionais modernas devem preferir:

- cadastro de credenciais pela API/UI
- pares e mapeamentos pela UI/API
- ajustes globais e por par pela UI/API

## Dados locais e organizacao adotada

Para manter o repositorio limpo, arquivos de ambiente local e runtime nao devem mais ser versionados:

- `config.windows.local.txt`
- `data/api_snapshot.json`
- `data/state.db`
- `logs/`

O repositorio agora preserva apenas exemplos e documentacao; estado operacional deve existir apenas na maquina/local de execucao.

## Seguranca e operacao

- Use apenas chaves com permissao de trade.
- Nunca habilite `withdraw`.
- Valide credenciais pela UI antes de habilitar operacao.
- Rode primeiro em `PAPER`.
- Revise `RiskManager`, kill switch e circuit breaker antes de qualquer uso real.

## Documentacao complementar

- `docs/00-overview.md`
- `docs/01-architecture.md`
- `docs/02-setup.md`
- `docs/03-configuration.md`
- `docs/04-strategies.md`
- `docs/05-risk.md`
- `docs/09-go-live.md`
- `docs/10-troubleshooting.md`
- `docs/17-relatorio-exchanges-api-2026-04-07.md`
- `docs/20-mercadobitcoin-travel-rule-2026-04-17.md`
- `docs/production-runbook.md`

## Resumo pratico

Hoje o projeto ja entrega a base completa de operacao local assistida: worker, API, UI, risco, credenciais e monitoramento. O principal cuidado para evolucao e uso real esta menos na estrutura do codigo e mais na disciplina operacional: separar configuracao local do repositorio, validar tudo em `PAPER` e manter a trilha de risco/credenciais sob controle.

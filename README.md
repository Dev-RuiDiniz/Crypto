# Robô de Trading Cripto (Spot) — Estado Atual do Projeto

Este repositório contém um bot de trading spot multipar com execução local, API Flask, dashboard web e persistência em SQLite.

> Status de aderência ao briefing: **PARCIAL**. Consulte `AUDITORIA_PROJETO.md`.

## O que o bot faz hoje
- Opera múltiplos pares configuráveis.
- Calcula alvos por spread (%) configurável por par.
- Mantém ordens (cancel/recreate) conforme variação do mercado.
- Executa em modo **PAPER** e **LIVE**.
- Exibe status em dashboard (mids, ordens, saldos, eventos).
- Permite configuração via API/DB sem restart (com `config_version`).
- Possui cofre de credenciais com criptografia AES-GCM no SQLite.

## O que ainda não está completo
- Streaming websocket de order book no loop principal (hoje: polling).
- Estratégia explícita de arbitragem simples (detector + execução de duas pernas).
- Idempotência forte de ordens com `clientOrderId` persistente.

---

## Arquitetura resumida
```text
config.txt + DB config -> bot.py/MainMonitor
-> strategy + router + order manager
-> ExchangeHub (CCXT + MB v4)
-> StateStore (SQLite/CSV/snapshot)
-> API Flask -> Dashboard
```

Documentação consolidada em `/docs`:
- [00-overview](docs/00-overview.md)
- [01-setup](docs/01-setup.md)
- [02-architecture](docs/02-architecture.md)
- [03-configuration](docs/03-configuration.md)
- [04-exchanges](docs/04-exchanges.md)
- [05-strategies](docs/05-strategies.md)
- [06-risk-management](docs/06-risk-management.md)
- [07-operations-runbook](docs/07-operations-runbook.md)
- [08-troubleshooting](docs/08-troubleshooting.md)
- [09-security](docs/09-security.md)
- [10-api](docs/10-api.md)
- [11-dashboard](docs/11-dashboard.md)
- [12-paper-vs-live](docs/12-paper-vs-live.md)

---

## Setup local

### Dependências
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Variáveis de ambiente
- `EXCHANGE_CREDENTIALS_MASTER_KEY` (obrigatória para decriptar/criptografar credenciais)
- `TRADINGBOT_TENANT_ID` (opcional, default `default`)

Veja `.env.example`.

### Configuração
- Copie/edite `config.txt` com base em `config.template.txt`.
- Configure pares e percentuais nas seções `[PAIRS]`, `[SPREAD]`, `[STAKE]`, `[RISK]`.

---

## Como rodar

### Worker + API (launcher)
```bash
python run_arbit.py
```

### Worker isolado
```bash
python bot.py --config config.txt
```

### API isolada
```bash
python -m api.server --config config.txt
```

Dashboard: `http://127.0.0.1:8000`

---

## Como configurar pares e percentuais

- Em arquivo INI:
  - `[PAIRS] LIST = SOL/USDT,DOGE/USDT`
  - `[SPREAD] SOL/USDT=0.04` (ou `SOL/USDT_BUY_PCT`/`SELL_PCT`)
  - `[RISK]` e `[STAKE]` para limites e tamanho de ordem.
- Em runtime:
  - via API `/api/bot-config` e `/api/bot-global-config`.
  - monitor recarrega mudanças via `config_version`.

## Como validar multipar
- Defina 2+ pares em `[PAIRS]` e ative `config_pairs` (via API/configuração).
- Verifique `/api/mids`, `/api/orders` e tabela `paper_orders` (em PAPER).

## Paper vs Live
- `MODE=PAPER`: simulação sem envio real de ordens.
- `MODE=REAL`: execução real nas exchanges habilitadas.

Recomendação: validar primeiro em PAPER (`docs/12-paper-vs-live.md`).

---

## Segurança
- Não coloque segredos reais em `config.txt`.
- Prefira cofre `exchange_credentials` (API de credenciais).
- Use API keys com permissão **trade-only** e **sem withdraw**.
- Logs aplicam redaction de campos sensíveis.

## Troubleshooting rápido
- `GET /api/health`, `/api/health/db`, `/api/health/worker`
- `GET /api/config-status`
- Confira `logs/` para erros de rede/auth/rate limit.

---

## Entregáveis desta consolidação
- `AUDITORIA_PROJETO.md` (raiz)
- README atualizado
- Estrutura de documentação padronizada em `/docs/00..12`

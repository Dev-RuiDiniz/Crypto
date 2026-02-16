# ARBIT — Bot de Trading/Arbitragem Spot (Status de Auditoria)

Projeto de bot spot com execução em múltiplas exchanges (via CCXT + adapter específico MB v4), com monitor em loop, persistência local (SQLite/CSV), API Flask e dashboard web simples para acompanhamento de saldos, ordens e mids.

## Arquitetura (atual)

- **Worker do bot** (`bot.py`): estratégia, risco, roteamento e monitor.
- **Camada de exchange** (`exchanges/`): `ExchangeHub` com CCXT async + `MBV4Adapter`.
- **Persistência local** (`core/state_store.py`): SQLite (`orders`, `fills`, `event_log`) e CSV opcional.
- **API Flask** (`api/server.py`, `api/handlers.py`): endpoints `/api/*` e servidor de frontend.
- **Frontend** (`frontend/src/`): dashboard React (sem build step) servido pela API.
- **Empacotamento desktop** (`frontend/electron/`): app Electron opcional.

---

## Como rodar local (dev)

### 1) Pré-requisitos

- Python 3.11+
- Node.js (somente se usar Electron)

### 2) Instalação Python

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 3) Configuração

- Copie/edite `config.txt` com pares, spread, stake e exchanges.
- **Importante:** não versionar segredos reais.

### 4) Subir API

```bash
python -m api.server
```

A API abre por padrão em `http://127.0.0.1:8000`.

### 5) Subir bot

Em outro terminal:

```bash
python bot.py config.txt
```

### 6) Dashboard

- Abrir no navegador: `http://127.0.0.1:8000`

### 7) Electron (opcional)

```bash
cd frontend/electron
npm install
npm run start
```

---

## Variáveis e parâmetros de ambiente/config

O projeto hoje usa principalmente `config.txt` (INI). Principais seções:

- `[GLOBAL]`: `MODE`, `USDT_BRL_RATE`, `LOOP_INTERVAL_MS`, `API_SNAPSHOT_PATH`, `SQLITE_PATH` etc.
- `[RISK]`: limites de ordens/exposição/kill switch.
- `[PAIRS]`, `[SPREAD]`, `[STAKE]`: estratégia e sizing por par.
- `[EXCHANGES.*]`: habilitação e credenciais.
- `[SYMBOLS]`: mapeamentos por exchange/par/lado.
- `[ROUTER]`: parâmetros de criação/reprice/cooldown.

> Recomendado para produção: migrar segredos para `.env`/secret manager e manter apenas template de configuração no repositório.

---

## Como testar

### Verificações rápidas

```bash
python test_server.py
```

### Checks básicos recomendados

```bash
python -m py_compile bot.py api/server.py api/handlers.py core/*.py exchanges/*.py
```

> Observação: ainda não há suíte de testes unitários/integração formal com `pytest` neste repositório.

---

## Status por módulo (auditoria)

### Entrega A — Núcleo do Bot
- 🟨 Market Data Ingestion
- 🟨 Strategy Engine
- 🟨 Risk Manager
- 🟨 Execution Engine
- 🟨 Portfolio & PnL

### Entrega B — Dashboard Web
- 🟨 Status ON/OFF operacional
- ✅ Config por par (básico)
- 🟨 Visualização execuções/ordens/PnL/erros
- 🟨 Ações administrativas (pausar/retomar/cancelar/fechar)

### Entrega C — Notificações
- ❌ Telegram/WhatsApp
- 🟨 Alertas estruturados

### Entrega D — Observabilidade
- ❌ Logs JSON + correlationId
- ❌ Métricas (Prometheus/Grafana)
- ❌ Tracing (OpenTelemetry)
- 🟨 Runbook operacional

### Sistemas obrigatórios de arquitetura
- ❌ Auth JWT + RBAC
- 🟨 Worker separado (manual)
- ❌ Fila/Scheduler (Redis + Celery/RQ)
- 🟨 Banco (há SQLite; falta Postgres/migrações)
- ❌ Cache/locks Redis
- ❌ Observabilidade completa
- ✅ Adapter unificado de exchange (básico)

---

## Próximos passos (MVP) — prioridades

### P0
- [ ] Remover segredos do repositório e rotacionar chaves.
- [ ] Implementar JWT + RBAC na API.
- [ ] Adicionar Docker Compose (api + worker + postgres + redis).
- [ ] Migrar SQLite para Postgres com migrações.
- [ ] Criar notificações críticas (Telegram).
- [ ] Criar testes unitários mínimos (risco/estratégia/execução).

### P1
- [ ] Fila/scheduler para reconciliação e comandos.
- [ ] Logging JSON com correlationId.
- [ ] Métricas e dashboard operacional.
- [ ] Ações de controle no dashboard (pause/resume/cancel all/flatten).
- [ ] Runbook de incidentes.

### P2
- [ ] PnL completo (realizado/não-realizado) por par/exchange.
- [ ] Estratégias plugáveis com horários/filtros.
- [ ] Tracing opcional (OpenTelemetry).

---

## Documentação complementar

- `AUDITORIA_PROPOSTA_TECNICA.md` — matriz completa da proposta técnica vs implementação atual.
- `README_run.txt` — instruções operacionais legadas para execução local.

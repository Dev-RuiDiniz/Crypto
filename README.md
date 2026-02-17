# ARBIT — Bot de Trading Spot (Paper + Live)

## 1) Visão geral

O **ARBIT** é um bot de trading spot com:
- execução em múltiplas exchanges (via `ExchangeHub`),
- monitoramento contínuo por ciclo,
- persistência local em SQLite/CSV,
- API Flask + dashboard web para observabilidade e configuração.

### Modos suportados
- **PAPER**: simula execução e grava em `paper_orders`.
- **REAL/LIVE**: envia ordens reais para as exchanges habilitadas.

### Suporte atual do cliente
- **Multi-pair simultâneo**: suportado (loop por par no mesmo ciclo).
- **Config operacional 100% via DB**: suportado via Dashboard e endpoints `/api/bot-config` + `/api/bot-global-config`.
- **Alteração sem restart**: `risk_percentage`, `mode`, `loop_interval_ms` e `kill_switch_enabled` são recarregados no worker em tempo de execução.
- **`/api/config` e `config.txt`**: fluxo legado/dev (não recomendado para operação).

---

## 2) Arquitetura

### Componentes
- **Worker/Execution Engine**: `bot.py` + `core/monitors.py` + `core/order_router.py`
- **Strategy**: `core/strategy_spread.py`
- **Risco**: `core/risk_manager.py`
- **Estado/Persistência**: `core/state_store.py` (SQLite + CSV)
- **API/Dashboard**: `api/server.py` + `api/handlers.py` + `frontend/src/*`
- **Integração com exchange**: `exchanges/exchanges_client.py` + adapters

### Diagrama simples

```text
Dashboard (frontend)
      |
      v
API Flask (api/server.py + handlers)
      |
      | (config/read/write)
      v
SQLite (data/state.db)
      ^
      |
Worker (bot.py -> MainMonitor -> Strategy -> Risk -> OrderRouter)
      |
      v
ExchangeHub -> Exchanges (Paper/Live)
```

### Fluxo principal do ciclo
1. `MainMonitor` atualiza lista de pares a partir de `config_pairs` (DB).
2. Para cada par:
   - recarrega `bot_config` (enabled, strategy, risk_percentage, max_daily_loss),
   - coleta mids por exchange,
   - calcula referência e alvos,
   - envia para `OrderRouter.reprice_pair(...)`.
3. `OrderRouter` calcula sizing (incluindo `risk_percentage`) e cria/cancela ordens.
4. Worker publica snapshot para API/dashboard.

---

## 3) Configuração

## 3) Configuração operacional (fonte única: SQLite)

### 3.1 Config por par (`config_pairs`)

Use o Dashboard (aba **Config do Bot (DB)**) ou a API `/api/bot-config`.

### 3.2 Config global (`bot_global_config`)

Use o Dashboard (aba **Config do Bot (DB)**) ou a API `/api/bot-global-config`.

Campos globais:
- `mode` (`PAPER` ou `LIVE`)
- `loop_interval_ms`
- `kill_switch_enabled`
- `max_positions`
- `max_daily_loss`

### 3.3 Endpoints operacionais

- `GET/POST /api/bot-config`
- `GET/POST /api/bot-global-config`

### 3.4 Legacy

- `GET/POST /api/config` permanece para debug/compatibilidade.
- `config.txt` deve ser tratado como legado/dev e não como fonte operacional principal.

## 3.1 `bot_config` por par (tabela `config_pairs`)

Campos relevantes:
- `pair` (`symbol` na tabela)
- `strategy`
- `risk_percentage`
- `max_daily_loss`
- `enabled`
- `updated_at`

### Exemplo SQL (SQLite)

```sql
INSERT INTO config_pairs(symbol, enabled, strategy, risk_percentage, max_daily_loss, updated_at)
VALUES ('SOL/USDT', 1, 'StrategySpread', 1.5, 100, strftime('%s','now'))
ON CONFLICT(symbol) DO UPDATE SET
  enabled=excluded.enabled,
  strategy=excluded.strategy,
  risk_percentage=excluded.risk_percentage,
  max_daily_loss=excluded.max_daily_loss,
  updated_at=excluded.updated_at;
```

### Exemplo cURL (novo endpoint)

```bash
# listar configs por par
curl -s http://127.0.0.1:8000/api/bot-config | jq .

# criar/atualizar par
curl -s -X POST http://127.0.0.1:8000/api/bot-config \
  -H 'Content-Type: application/json' \
  -d '{
    "pair": "SOL/USDT",
    "strategy": "StrategySpread",
    "risk_percentage": 2.0,
    "max_daily_loss": 80,
    "enabled": true
  }' | jq .

# desabilitar par
curl -s -X POST http://127.0.0.1:8000/api/bot-config \
  -H 'Content-Type: application/json' \
  -d '{"pair":"SOL/USDT","enabled":false}' | jq .
```

## 3.2 INI (`config.txt`)

Pontos principais:
- `[GLOBAL]`: `MODE`, `LOOP_INTERVAL_MS`, `SQLITE_PATH`, `BOT_CONFIG_CACHE_TTL_SEC`
- `[PAIRS]`: `LIST` (pares base do worker)
- `[SPREAD]`: spread por par
- `[STAKE]`: sizing base por par
- `[ROUTER]`: mínima de notional, modo de âncora etc.

> Observação: pares podem vir de `[PAIRS].LIST` e também de `config_pairs` (DB).

---

## 4) Como rodar local

### Executável Local (Sprint 0)

Novo bootstrap unificado:

```bash
python -m app.launcher --port 8000 --config config.txt
```

Esse comando inicia API + worker com o mesmo `--db-path` absoluto em `%LOCALAPPDATA%/TradingBot/data/state.db` (ou fallback `~/.local/share/TradingBot/data/state.db` em dev não-Windows), aguarda `/api/health` e abre o dashboard automaticamente.

Health endpoints:
- `GET /api/health`
- `GET /api/health/db`
- `GET /api/health/worker`

Veja o guia completo em `docs/local-executable-dev.md`.

### Modo legado (manual)
### Pré-requisitos
- Python 3.11+
- Dependências de `requirements.txt`

### Passos

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Subir API:

```bash
python -m api.server
```

Subir worker (outro terminal):

```bash
python bot.py config.txt
```

Dashboard:
- `http://127.0.0.1:8000`

---

## 5) Como usar (cenários do cliente)

## 5.1 Rodar 2 pares simultaneamente

1. Garanta os pares habilitados no DB:
   - `SOL/USDT`, `BTC/USDT` com `enabled=true`.
2. Inicie API + worker.
3. Valide nos logs do worker se ambos os pares são percorridos no ciclo (`[ExecutionEngine] Symbol: ...`).

## 5.2 Alterar `%` em tempo real (sem restart)

1. Com worker rodando, atualize `risk_percentage` via `POST /api/bot-config`.
2. Aguarde 1–2 ciclos (respeitando `BOT_CONFIG_CACHE_TTL_SEC`).
3. Verifique logs:
   - `[config_reload] ... risk_percentage=...`
   - `[position_sizing] pair=... risk_percentage=... balance_used_usdt=... qty=... notional_usdt=...`

---

## 6) Testes

Executar suíte focada em multi-pair + risk dinâmico:

```bash
python -m pytest tests/test_paper_multipair.py -q
```

Checks básicos de sintaxe:

```bash
python -m py_compile bot.py api/server.py api/handlers.py core/*.py exchanges/*.py
```

Critérios validados na suíte:
- execução por múltiplos pares no modo paper,
- persistência de `risk_percentage` por execução,
- atualização de `risk_percentage` refletida no próximo ciclo.

---

## 7) Troubleshooting

### Problema: "bot só roda 1 par"
- Verifique `config_pairs.enabled` para os pares desejados.
- Verifique `[PAIRS].LIST` e se o par está normalizado (`BASE/QUOTE`).
- Confira logs de `MainMonitor` para estratégia incompatível por par.

### Problema: "alterei % e não refletiu"
- Confirmar persistência no SQLite (`config_pairs.risk_percentage` e `updated_at`).
- Aguardar o TTL de cache (`GLOBAL.BOT_CONFIG_CACHE_TTL_SEC`).
- Conferir logs `[config_reload]` e `[position_sizing]`.

### Cache/config
- Não há Redis/cache distribuído; cache é em memória do worker por TTL curto.
- Se API e worker usam arquivos diferentes, conferir `GLOBAL.SQLITE_PATH`.

### Hardcode de símbolo
- Execução usa `pair` dinâmico e resolve símbolo local por exchange.
- Se uma exchange não tem mapeamento, revisar `[SYMBOLS]` no `config.txt`.

---

## 8) Onde editar/configurar pares e estratégias

- **Por API (recomendado):** `POST /api/bot-config`.
- **Direto no banco:** tabela `config_pairs` em `data/state.db`.
- **Config base/legado (via dashboard atual):** `config.txt` (`[PAIRS]`, `[SPREAD]`, `[STAKE]`, `[ROUTER]`) através de `GET/POST /api/config`.

---

## 9) Limitações atuais e como validar

- **Dashboard x `config_pairs`:** o frontend atual não possui CRUD visual de `config_pairs`; use `GET/POST /api/bot-config` (curl/Postman/cliente HTTP).
- **Isolamento por par:** o loop é multi-pair, porém o tratamento de erro do ciclo ainda é amplo; falha não tratada em um par pode interromper os demais no ciclo corrente.
- **Propagação de `risk_percentage`:** alterações refletem sem restart, mas após o TTL (`GLOBAL.BOT_CONFIG_CACHE_TTL_SEC`) e o próximo ciclo do worker.
- **Consistência de SQLite:** garanta que API e worker apontem para o mesmo `GLOBAL.SQLITE_PATH` absoluto para evitar escrita/leitura em bancos distintos.

### Como validar rapidamente

1. Atualize `risk_percentage` via `POST /api/bot-config`.
2. Consulte `GET /api/bot-config` e confirme o `sqlite_path` retornado.
3. Verifique no log do worker as linhas `[config_reload]` e `[position_sizing]` para o par alterado.

---

## 10) Documentação complementar

- `docs/auditoria-solicitacao-cliente.md` — auditoria completa da solicitação do cliente.
- `docs/tests-paper-multipair.md` — referência dos testes paper multi-pair.
- `docs/reload-config.md` — detalhes de recarga de configuração.

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
- **Config por par (`risk_percentage`) sem restart**: suportado no worker com recarga periódica de `config_pairs`.

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
1. `MainMonitor` atualiza lista de pares (INI + `config_pairs`).
2. Para cada par:
   - recarrega `bot_config` (enabled, strategy, risk_percentage, max_daily_loss),
   - coleta mids por exchange,
   - calcula referência e alvos,
   - envia para `OrderRouter.reprice_pair(...)`.
3. `OrderRouter` calcula sizing (incluindo `risk_percentage`) e cria/cancela ordens.
4. Worker publica snapshot para API/dashboard.

---

## 3) Configuração

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
- **Config base/legado:** `config.txt` (`[PAIRS]`, `[SPREAD]`, `[STAKE]`, `[ROUTER]`).

---

## 9) Documentação complementar

- `docs/auditoria-solicitacao-cliente.md` — auditoria completa da solicitação do cliente.
- `docs/tests-paper-multipair.md` — referência dos testes paper multi-pair.
- `docs/reload-config.md` — detalhes de recarga de configuração.

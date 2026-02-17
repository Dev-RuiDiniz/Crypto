# AUDITORIA PÓS-SPRINTS (0–4)

## 1) Resumo executivo

**Status geral:** o repositório entrega o objetivo de **Executável Local Windows** com bootstrap unificado (launcher), build de `.exe` e instalador, persistência em `%LOCALAPPDATA%`, health endpoints e fluxo de configuração operacional via DB com versionamento/aplicação no worker.

### O que está OK
- Build de executável com PyInstaller (`TradingBot.exe`) e script de build dedicado.
- Instalador Inno Setup com saída `TradingBotSetup.exe`.
- Diretórios de runtime e DB em `%LOCALAPPDATA%\TradingBot\...` via resolução centralizada.
- Launcher inicia API+worker com **mesmo `--db-path` absoluto**.
- Dashboard abre automaticamente após healthcheck da API.
- Endpoints de health implementados (`/api/health`, `/api/health/db`, `/api/health/worker`).
- Config operacional por DB (`/api/bot-config`, `/api/bot-global-config`) com `config_version` e aplicação pelo worker.
- Loop multi-pair com `try/except` por par e `continue` (isolamento por iteração).

### Pontos parciais / risco
- `/api/config` (legado) ainda existe e continua disponível. Isso não bloqueia a operação por DB (UI principal usa endpoints DB), mas pode gerar uso indevido em operação se não houver governança.
- O check de `/api/health/db` faz escrita em `runtime_status` para validar DB; funcional, mas interfere no mesmo registro usado por heartbeat do worker (potencial de ruído de observabilidade).

---

## 2) Tabela — Feature x Status x Evidência

| Feature | Status | Evidência no código | Conclusão |
|---|---|---|---|
| Executável local `TradingBot.exe` | **Implementado** | `build/windows/build_exe.ps1` chama `PyInstaller build/windows/tradingbot.spec` e loga saída `dist/TradingBot/TradingBot.exe`. `build/windows/tradingbot.spec` define `name="TradingBot"` no `EXE`/`COLLECT`. | Atende.
| Instalador `TradingBotSetup.exe` | **Implementado** | `build/windows/installer.iss` define `OutputBaseFilename=TradingBotSetup` e `OutputDir=dist`. | Atende.
| Runtime em `%LOCALAPPDATA%` | **Implementado** | `app/paths.py` resolve raiz por `LOCALAPPDATA` e monta `TradingBot/data/state.db` e `TradingBot/logs`. | Atende.
| Dashboard auto-open | **Implementado** | `app/launcher.py` aguarda `/api/health` e chama `webbrowser.open(f"{base_url}/")` quando não usa `--no-browser`. | Atende.
| DB path único API/worker | **Implementado** | `app/launcher.py` monta `api_cmd` e `worker_cmd` com o mesmo `--db-path` (`paths.db_path`). `api/server.py` passa `db_path` para `handlers.set_db_path_override`. | Atende.
| Multi-pair com isolamento real | **Implementado** | `core/monitors.py`: loop `for pair in self.pairs` com `try/except` interno e `continue` em erro do par. | Atende.
| Config 100% via DB (UI usa bot-config/global) | **Implementado (com legado ativo)** | `frontend/src/components/BotConfigPanel.js` usa `api.getBotConfig`, `getBotGlobalConfig`, `getConfigStatus`; `frontend/src/App.js` só expõe Dashboard + Config do Bot (DB). `/api/config` ainda existe em `api/server.py`. | Operação DB está implementada; legado permanece.
| `bot_global_config` | **Implementado** | Tabela criada em `core/state_store.py` e também gerida em `api/handlers.py::get_bot_global_config/upsert_bot_global_config`. | Atende.
| `config_version` + bump em POST | **Implementado** | `api/handlers.py::_bump_config_version` é chamado em `upsert_bot_config` e `upsert_bot_global_config`. | Atende.
| Worker aplica sem TTL (por versão) | **Implementado** | `core/monitors.py::_reload_configs_if_needed` compara versão atual vs `last_seen_config_version` e recarrega imediatamente quando muda. | Atende.
| Runtime status de aplicação (`last_applied_*`) | **Implementado** | `core/monitors.py` chama `self.state.update_runtime_applied_config(...)`; schema existe em `core/state_store.py` e leitura no health/config status em `api/handlers.py`. | Atende.
| UI mostra “Aplicado às …” | **Implementado** | `frontend/src/components/BotConfigPanel.js` renderiza texto com `Aplicado às ${fmtTime(configStatus.worker_last_applied_config_at)}`. | Atende.
| `/api/health` | **Implementado** | `api/server.py::api_health` retorna status, version, db_path, pid. | Atende.
| `/api/health/db` | **Implementado** | `api/server.py::api_health_db` usa `handlers.get_db_health()` que testa conexão+escrita. | Atende.
| `/api/health/worker` | **Implementado** | `api/server.py::api_health_worker` usa `handlers.get_worker_health()` com heartbeat e classificação `ok/stale/down`. | Atende.

---

## 3) Arquitetura atual (ASCII)

```text
[TradingBot.exe / app.launcher]
        |
        | inicia subprocessos com mesmo --db-path absoluto
        +------------------------+
        |                        |
 [API Flask - api/server.py]   [Worker - bot.py -> MainMonitor]
        |                        |
        | GET/POST config        | lê config_version e aplica em runtime
        | health endpoints       | heartbeat/runtime_status
        +-----------+------------+
                    |
               [SQLite state.db]
                    |
            config_pairs / bot_global_config /
            config_version / runtime_status
                    |
               [Dashboard frontend]
```

---

## 4) Fluxos principais

### 4.1 Boot do launcher/exe
1. Launcher resolve paths de runtime e cria diretórios (`base/data/logs`).
2. Seta envs de log (`TRADINGBOT_LOG_DIR`, `TRADINGBOT_WORKER_LOG_FILE`).
3. Sobe API e worker com mesmo `--db-path` absoluto.
4. Faz healthcheck em `/api/health`.
5. Abre navegador automaticamente no dashboard.

### 4.2 Dashboard config → DB → config_version → worker aplica
1. UI salva em `/api/bot-config` ou `/api/bot-global-config`.
2. Handler faz upsert no SQLite.
3. Handler chama `_bump_config_version(...)`.
4. Worker, em cada ciclo, chama `_reload_configs_if_needed()` e compara versão.
5. Ao detectar mudança: recarrega configs, registra `[CONFIG_APPLIED]`, grava `last_applied_config_*` em `runtime_status`.
6. UI consulta `/api/config-status` e exibe “Aplicado às …”.

### 4.3 Multi-pair com isolamento
1. Worker monta lista de pares habilitados (`config_pairs` + seed opcional).
2. Itera `for pair in self.pairs`.
3. Cada par roda em `try/except` interno.
4. Em erro de um par: loga erro e `continue`, sem abortar os demais.

---

## 5) Endpoints (payload/resposta exemplo)

## Health
- `GET /api/health`
```json
{
  "status": "ok",
  "app": "trading-bot",
  "version": "1.0.0",
  "time": "2026-01-01T10:00:00Z",
  "db_path": "C:\\Users\\<user>\\AppData\\Local\\TradingBot\\data\\state.db",
  "pid": 1234
}
```

- `GET /api/health/db`
```json
{
  "status": "ok",
  "db_path": "...state.db",
  "writable": true,
  "checks": { "connect": true, "write": true }
}
```

- `GET /api/health/worker`
```json
{
  "status": "ok",
  "worker_pid": 5678,
  "last_heartbeat_at": "2026-01-01T10:00:10Z",
  "db_path": "...state.db",
  "version": "1.0.0",
  "started_at": "2026-01-01T09:58:00Z",
  "last_applied_config_version": 42,
  "last_applied_config_at": "2026-01-01T10:00:05Z",
  "last_applied_config_reason": "bot_global_config updated"
}
```

## Configuração operacional (DB)
- `GET /api/bot-config`
```json
{
  "items": [
    {
      "pair": "BTC/USDT",
      "strategy": "StrategySpread",
      "risk_percentage": 1.5,
      "max_daily_loss": 100.0,
      "enabled": true,
      "updated_at": 1760000000.0
    }
  ],
  "sqlite_path": "...state.db"
}
```

- `POST /api/bot-config`
```json
{
  "pair": "BTC/USDT",
  "enabled": true,
  "strategy": "StrategySpread",
  "risk_percentage": 2.0,
  "max_daily_loss": 80
}
```
Resposta:
```json
{ "ok": true, "message": "bot_config salvo para BTC/USDT. config_version=43" }
```

- `GET /api/bot-global-config`
```json
{
  "mode": "PAPER",
  "loop_interval_ms": 2000,
  "kill_switch_enabled": false,
  "max_positions": 1,
  "max_daily_loss": 0,
  "updated_at": "2026-01-01T10:00:00Z",
  "sqlite_path": "...state.db"
}
```

- `POST /api/bot-global-config`
```json
{
  "mode": "LIVE",
  "loop_interval_ms": 1200,
  "kill_switch_enabled": false,
  "max_positions": 2,
  "max_daily_loss": 150
}
```
Resposta:
```json
{ "ok": true, "message": "bot_global_config atualizado com sucesso. config_version=44" }
```

- `GET /api/config-status`
```json
{
  "db_config_version": 44,
  "db_config_updated_at": "2026-01-01T10:00:12Z",
  "worker_last_applied_config_version": 44,
  "worker_last_applied_config_at": "2026-01-01T10:00:13Z",
  "worker_last_applied_config_reason": "bot_global_config updated",
  "in_sync": true,
  "worker_status": "ok",
  "db_path": "...state.db"
}
```

---

## 6) Paths/pastas geradas (AppData)

Base (Windows):
- `%LOCALAPPDATA%\TradingBot\`

Estrutura principal:
- `%LOCALAPPDATA%\TradingBot\data\state.db`
- `%LOCALAPPDATA%\TradingBot\data\orders.csv` (se CSV habilitado)
- `%LOCALAPPDATA%\TradingBot\data\fills.csv` (se CSV habilitado)
- `%LOCALAPPDATA%\TradingBot\logs\app.log`
- `%LOCALAPPDATA%\TradingBot\logs\api.log`
- `%LOCALAPPDATA%\TradingBot\logs\worker.log`

Instalação do app (Inno Setup):
- `{localappdata}\Programs\TradingBot\` (binários)

---

## 7) Divergências vs plano das sprints + ações recomendadas

### D1) `/api/config` legado ainda ativo
- **Status:** Parcial (operação DB está pronta, mas endpoint legado existe).
- **Evidência:** rota `/api/config` permanece em `api/server.py`; client mantém `getConfigLegacy` em `frontend/src/utils/api.js`.
- **Risco:** operador usar canal legado e esperar comportamento operacional.
- **Ação recomendada:**
  1. Marcar `/api/config` como deprecated com warning explícito em resposta.
  2. Restringir uso em produção (feature flag/env).
  3. Planejar remoção na próxima sprint maior.

### D2) Check de `/api/health/db` altera `runtime_status`
- **Status:** Parcial.
- **Evidência:** `get_db_health()` faz `DELETE`/`INSERT` em `runtime_status` para teste de escrita.
- **Risco:** ruído em telemetria de worker health.
- **Ação recomendada:** testar escrita em tabela de healthcheck isolada (ex.: `health_probe`) para não tocar estado de runtime.

---

## 8) Conclusão

A baseline pós-sprints está **funcional para operação local Windows** com instalador, persistência correta em AppData, dashboard auto-open, health endpoints e ciclo de configuração imediata via `config_version` + `runtime_status`. As divergências encontradas são tratáveis e não bloqueiam o uso principal.

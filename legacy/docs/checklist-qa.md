# Checklist QA Pós-Build (Windows)

## 1) Health endpoints

- [ ] `GET /api/health` retorna `status=ok`, `version`, `db_path`.
- [ ] `GET /api/health/db` retorna `writable=true`.
- [ ] `GET /api/health/worker` retorna `status=ok` (ou `stale` se parado).

## 2) DB único (API e worker)

- [ ] `db_path` de `/api/health` é o mesmo de `/api/health/worker`.
- [ ] O arquivo físico existe em `%LOCALAPPDATA%\TradingBot\data\state.db`.

## 3) config_version + aplicação imediata

- [ ] Salvar algo em `/api/bot-config` incrementa `config_version`.
- [ ] Salvar algo em `/api/bot-global-config` incrementa `config_version`.
- [ ] `/api/config-status` mostra `worker_last_applied_config_version` acompanhando DB.
- [ ] UI exibe “Aplicado às …”.

## 4) Multi-pair com isolamento

- [ ] Habilitar 2+ pares no dashboard.
- [ ] Confirmar logs por par em `worker.log`.
- [ ] Simular falha em 1 par e verificar continuação dos demais (`continue` por iteração).

## 5) Logs em AppData

- [ ] `%LOCALAPPDATA%\TradingBot\logs\app.log` criado.
- [ ] `%LOCALAPPDATA%\TradingBot\logs\api.log` criado.
- [ ] `%LOCALAPPDATA%\TradingBot\logs\worker.log` criado.

## 6) Dashboard auto-open

- [ ] Ao iniciar app, navegador abre automaticamente no dashboard.
- [ ] Em caso de porta ocupada, launcher escolhe porta alternativa (5000-5100) e registra no log.


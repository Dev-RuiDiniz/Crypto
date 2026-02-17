# Sprint 2 — Verificação (Dashboard 100% via DB)

## 1) Subir aplicação

```bash
python -m app.launcher --port 8000 --config config.txt
```

## 2) Verificar API de config por par

```bash
curl -s http://127.0.0.1:8000/api/bot-config
```

```bash
curl -s -X POST http://127.0.0.1:8000/api/bot-config \
  -H 'Content-Type: application/json' \
  -d '{"pair":"BTC/USDT","risk_percentage":1.5,"enabled":true,"strategy":"StrategySpread"}'
```

## 3) Verificar API de config global

```bash
curl -s http://127.0.0.1:8000/api/bot-global-config
```

```bash
curl -s -X POST http://127.0.0.1:8000/api/bot-global-config \
  -H 'Content-Type: application/json' \
  -d '{"mode":"PAPER","loop_interval_ms":2000,"kill_switch_enabled":true,"max_positions":3,"max_daily_loss":25.0}'
```

## 4) Verificação no Dashboard

1. Abrir `http://127.0.0.1:8000`.
2. Ir para aba **Config do Bot (DB)**.
3. Em **Config por Par**, criar/editar `BTC/USDT` com `risk_percentage=1.5` e `enabled=true`.
4. Em **Config Global**, alterar `kill_switch_enabled` e `mode`.
5. Recarregar o browser e confirmar persistência (dados continuam iguais).

## 5) Verificação no worker (logs)

Confirmar logs:
- recarga de config global com `updated_at`:
  - `[global_config] updated_at=... mode=... kill_switch_enabled=...`
- lista de pares vindos do DB:
  - `[config_reload] ... pair=BTC/USDT ...`
- kill switch bloqueando execução:
  - `[global_config] kill_switch_enabled=true: ciclo sem envio de ordens.`

## 6) Resultado esperado

- Operação de pares e risco via DB (`config_pairs`).
- Operação global via DB (`bot_global_config`).
- Dashboard sem dependência operacional de `/api/config`.

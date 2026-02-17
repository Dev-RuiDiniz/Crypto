# Sprint 3 — Verificação manual (config_version + apply imediato)

## Pré-requisitos
- API em execução (`python -m api.server --host 127.0.0.1 --port 8000`)
- Worker em execução (`python bot.py`)
- Dashboard aberto na aba **Config do Bot (DB)**

## 1) Alterar `risk_percentage` por par e validar aplicação
1. No Dashboard, altere `risk_percentage` de um par e clique em **Salvar**.
2. Verifique no status da UI:
   - aparece **Aplicando...**
   - depois muda para **Aplicado às HH:MM:SS**
3. Verifique endpoint:
   ```bash
   curl -s http://127.0.0.1:8000/api/config-status
   ```
   Esperado:
   - `db_config_version` incrementado
   - `worker_last_applied_config_version` igual ao `db_config_version`
   - `in_sync=true`
4. Verifique log do worker:
   - procurar por `[CONFIG_APPLIED] version=... applied_at=...`

## 2) Alterar Config Global (kill switch) e validar aplicação
1. No Dashboard, altere `kill_switch_enabled` e clique em **Salvar**.
2. Verifique novamente `GET /api/config-status`:
   - versão incrementa novamente
   - worker aplica a nova versão no próximo ciclo
3. Confirmar em `/api/health/worker` campos:
   - `last_applied_config_version`
   - `last_applied_config_at`

## 3) Verificação de sincronismo
- Enquanto worker está aplicando, UI exibe **Aplicando...** (`db_config_version != worker_last_applied_config_version`).
- Após próximo ciclo do worker, UI exibe **Aplicado às ...** (`in_sync=true`).

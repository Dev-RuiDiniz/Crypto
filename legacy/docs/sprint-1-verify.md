# Sprint 1 (P0) — Verificação Manual

## 1) API com `--db-path` absoluto

```bash
python -m api.server --host 127.0.0.1 --port 8000 --db-path /tmp/tradingbot/state.db
```

Validar:

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/health/db
```

Esperado:
- `db_path` absoluto em ambos endpoints.
- `/api/health/db` com `writable=true`, `checks.connect=true` e `checks.write=true`.

## 2) Worker com o mesmo `--db-path`

```bash
python -m bot config.txt --db-path /tmp/tradingbot/state.db
```

Com API já rodando, validar:

```bash
curl -s http://127.0.0.1:8000/api/health/worker
```

Esperado:
- `status=ok` quando heartbeat recente.
- `db_path` igual ao usado na API.
- `last_heartbeat_at` preenchido em ISO-8601.

## 3) Isolamento por par no ciclo

Para simular falha controlada, force exceção em um par (exemplo: mock/adapter de exchange para um símbolo específico).

Validar no log:
- existe registro estruturado `[pair_loop] pair=<PAR> error_type=<...> message=<...>` com traceback.
- no mesmo ciclo, os demais pares continuam processando.

## 4) Verificação pelo launcher (modo executável local)

```bash
python -m app.launcher --host 127.0.0.1 --port 8000 --no-browser
```

Esperado no log do launcher:
- `[BOOT] DB_PATH=<absoluto>`
- API e Worker iniciados com o mesmo `--db-path`.

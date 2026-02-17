# Executável Local (Sprint 0) — Guia de Desenvolvimento

## Rodar launcher em dev

```bash
python -m app.launcher --port 8000 --config config.txt
```

O launcher faz bootstrap de:
- API/dashboard (`python -m api.server --db-path ...`)
- Worker (`python -m bot config.txt --db-path ...`)

## Diretórios gerados

Base (Windows):
- `%LOCALAPPDATA%/TradingBot/`

Subpastas:
- `data/state.db` (SQLite único)
- `logs/app.log` (launcher)
- `logs/api.log` (API)
- `logs/worker.log` (worker)

Fallback em Linux/macOS dev: `~/.local/share/TradingBot/`.

## Health checks

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/health/db
curl -s http://127.0.0.1:8000/api/health/worker
```

Validação de DB único:
- Compare `db_path` no `/api/health` com o `[BOOT] DB_PATH=...` do worker.
- Ambos devem apontar para o mesmo arquivo absoluto.

## Reset/Limpeza

Para resetar estado local:
1. Encerrar launcher.
2. Apagar `%LOCALAPPDATA%/TradingBot/data`.
3. Reiniciar `python -m app.launcher`.

## Portas e URL

- Porta padrão: `8000`
- URL dashboard: `http://127.0.0.1:8000/`

## Troubleshooting

- **Porta ocupada**: rode com `--port 8001`.
- **DB locked**: finalize processos duplicados; mantenha apenas um launcher por vez.
- **Dashboard não abre**: usar `--no-browser` e abrir URL manualmente.
- **Worker stale em `/api/health/worker`**: verificar `logs/worker.log` e heartbeat na tabela `runtime_status`.

## Teste manual mínimo (Sprint 0)

1. Iniciar launcher.
2. Confirmar abertura do dashboard.
3. Chamar endpoints `/api/health*`.
4. Confirmar logs em `%LOCALAPPDATA%/TradingBot/logs`.
5. Confirmar DB único entre API e worker.

## PyInstaller (one-folder primeiro)

```bash
pyinstaller --clean --noconfirm build/pyinstaller.spec
```

Saída esperada: `dist/TradingBot/TradingBot.exe` (Windows).

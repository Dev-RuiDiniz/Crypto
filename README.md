# TradingBot — Executável Local (Windows)

Bot de trading com execução local (sem cloud obrigatória), dashboard web, configuração operacional via SQLite e pacote para instalação no Windows.

## Visão geral

- **Formato de entrega:** `TradingBot.exe` + instalador `TradingBotSetup.exe`.
- **Execução local:** launcher sobe API + worker e abre dashboard automaticamente.
- **Persistência:** dados e logs em `%LOCALAPPDATA%\TradingBot\...`.
- **Config operacional:** via DB (`/api/bot-config`, `/api/bot-global-config`) com aplicação imediata controlada por `config_version`.

## Requisitos (usuário final)

- Windows 10/11.
- Permissão de execução para aplicativo instalado em perfil do usuário.

## Instalação (usuário final)

1. Execute `TradingBotSetup.exe`.
2. Conclua o assistente.
3. (Opcional) marque atalho na Área de Trabalho.
4. Ao final, clique em **Executar TradingBot**.

Guia completo: **[`docs/como-usar.md`](docs/como-usar.md)**.

## Primeiro uso

1. Abra o app (Menu Iniciar ou atalho).
2. Aguarde abrir o dashboard no navegador.
3. Em **Config do Bot (DB)**:
   - ajuste **Config Global** (mode, loop, kill switch, limites),
   - ajuste **Config por Par** (`enabled`, `risk%`, `strategy`).
4. Confira o status **“Aplicado às …”**.

## Onde ficam dados e logs

Base:
- `%LOCALAPPDATA%\TradingBot\`

Principais arquivos:
- `data\state.db`
- `logs\app.log`
- `logs\api.log`
- `logs\worker.log`

## Health endpoints

- `GET /api/health`
- `GET /api/health/db`
- `GET /api/health/worker`
- `GET /api/config-status` (sync DB x worker)

## Troubleshooting rápido

- **Dashboard não abre:** acesse manualmente `http://127.0.0.1:8000` (ou porta alternativa logada no `app.log`).
- **Worker “down/stale”:** verifique `%LOCALAPPDATA%\TradingBot\logs\worker.log`.
- **Config não aplicada:** consulte `/api/config-status` e confirme `in_sync=true`.
- **Sem escrita no banco:** valide permissões em `%LOCALAPPDATA%\TradingBot\data`.

## Como gerar executáveis (dev/build)

Resumo:
1. `build\windows\build_exe.bat` (gera `dist\TradingBot\TradingBot.exe`).
2. Compile `build\windows\installer.iss` no Inno Setup (gera `dist\TradingBotSetup.exe`).

Documentação detalhada: **[`docs/build-windows.md`](docs/build-windows.md)**.

## Documentação complementar

- Auditoria pós-sprints: [`AUDITORIA_POS_SPRINTS.md`](AUDITORIA_POS_SPRINTS.md)
- Runbook usuário final: [`docs/como-usar.md`](docs/como-usar.md)
- Build para Windows: [`docs/build-windows.md`](docs/build-windows.md)
- QA pós-build: [`docs/checklist-qa.md`](docs/checklist-qa.md)

# Sprint 4 — Verificação de Empacotamento Windows

## Build
1. Rodar `build\windows\build_exe.bat`.
2. Confirmar que `dist\TradingBot\TradingBot.exe` existe.

## Runtime
3. Executar `TradingBot.exe`.
4. Confirmar:
   - Browser abre automaticamente no dashboard.
   - `GET http://127.0.0.1:<PORT>/api/health` retorna `status=ok`.
   - Logs em `%LOCALAPPDATA%\TradingBot\logs` (`app.log`, `api.log`, `worker.log`).
   - Banco em `%LOCALAPPDATA%\TradingBot\data\state.db`.
   - UI carrega assets sem 404 (`/static/*`, index dashboard).

## Installer
5. Compilar `build\windows\installer.iss` no Inno Setup.
6. Instalar e validar atalhos (Menu Iniciar obrigatório, Desktop opcional).
7. Marcar “Executar TradingBot” no final e validar abertura do dashboard.
8. Desinstalar e confirmar:
   - arquivos de `{app}` removidos;
   - `%LOCALAPPDATA%\TradingBot\` permanece (dados do usuário preservados).

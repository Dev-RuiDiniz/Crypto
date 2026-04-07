@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0EXECUTAR_TRADINGBOT.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [TRADINGBOT] A execucao falhou. Corrija o erro e tente novamente.
  pause
)

endlocal & exit /b %EXIT_CODE%

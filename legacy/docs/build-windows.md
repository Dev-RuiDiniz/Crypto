# Build Windows (Dev) — Executável + Instalador

## 1) Pré-requisitos

- Windows 10/11.
- Python do projeto (usar ambiente virtual local).
- Dependências em `requirements.txt`.
- **PyInstaller**.
- **Inno Setup** instalado (para compilar `.iss`).

## 2) Preparar ambiente

### PowerShell
```powershell
cd <repo>
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller
```

## 3) Build do executável (PyInstaller)

## Spec oficial
- `build/windows/tradingbot.spec`

Esse spec já inclui assets em `datas=` quando existirem:
- `frontend/src`
- `frontend/build`
- `templates`
- `static`
- `config.txt`
- `bitt.ico`

## Comando recomendado
### PowerShell
```powershell
build\windows\build_exe.ps1
```

### CMD
```cmd
build\windows\build_exe.bat
```

Saída esperada:
- `dist\TradingBot\TradingBot.exe`

## Observações de runtime em build frozen
- O servidor resolve assets considerando ambiente empacotado:
  - detecta `sys.frozen`
  - usa `sys._MEIPASS` para localizar bundle quando necessário.
- Isso evita quebra de frontend estático no executável.

## 4) Build do instalador (Inno Setup)

1. Garanta que `dist\TradingBot\` exista (build PyInstaller concluído).
2. Abra `build\windows\installer.iss` no Inno Setup.
3. Clique em **Compile**.

Saída esperada:
- `dist\TradingBotSetup.exe`

Configuração relevante no `.iss`:
- `DefaultDirName={localappdata}\Programs\TradingBot`
- `PrivilegesRequired=lowest`
- `OutputBaseFilename=TradingBotSetup`

## 5) Checklist rápido em máquina limpa

1. Instalar `TradingBotSetup.exe` sem privilégios de admin.
2. Abrir app e validar auto-open do dashboard.
3. Validar criação de:
   - `%LOCALAPPDATA%\TradingBot\data\state.db`
   - `%LOCALAPPDATA%\TradingBot\logs\*.log`
4. Validar endpoints:
   - `/api/health`
   - `/api/health/db`
   - `/api/health/worker`
5. Alterar config no dashboard e confirmar aplicação via `/api/config-status`.


# Setup Local Windows

Este guia descreve setup e start local no Windows para validacao tecnica.

## 0. Execucao 1-clique (recomendado para cliente)
No diretorio do projeto (`Crypto-main/Crypto-main`), execute:

- `EXECUTAR_TRADINGBOT.bat`

O executor faz automaticamente:
- deteccao de Python 3.11+
- criacao de `.venv-client`
- instalacao de dependencias de `requirements.txt`
- start do sistema local (`app.launcher`)

## 1. Pre-requisitos
- Python 3.12+ instalado e no `PATH`.
- PowerShell.
- Internet para instalar dependencias.

## 2. Criar ambiente virtual
No diretorio do projeto (`Crypto-main/Crypto-main`):

```powershell
py -3.12 -m venv .venv-win312
.\.venv-win312\Scripts\python -m pip install --upgrade pip
.\.venv-win312\Scripts\python -m pip install -r requirements.txt pytest
```

## 3. Configuracao local recomendada
Foi adicionado o arquivo `config.windows.local.txt` para modo local seguro:
- `mode = PAPER`
- exchanges desabilitadas (`enabled = false`)
- sem credenciais reais em arquivo

Use este arquivo no launcher:

```powershell
$env:EXCHANGE_CREDENTIALS_MASTER_KEY = "0123456789abcdef0123456789abcdef"
$env:PYTHONUTF8 = "1"
.\.venv-win312\Scripts\python -m app.launcher --config config.windows.local.txt --no-browser
```

Observacao:
- O `EXCHANGE_CREDENTIALS_MASTER_KEY` e obrigatorio para recursos de cofre.
- `PYTHONUTF8=1` evita problemas de encoding no terminal Windows.

## 4. Validacao de healthcheck
Com a aplicacao em execucao, valide:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/api/health
Invoke-WebRequest http://127.0.0.1:8000/api/health/worker
```

Resultado esperado:
- `status = ok` em ambos endpoints.

## 5. Encerramento
- No terminal do launcher: `Ctrl + C`.

Se houver processos filhos persistentes:

```powershell
$target = "C:\Users\Rui Francisco\Desktop\Crypto-main\Crypto-main"
Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
  Where-Object { $_.CommandLine -like "*$target*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

## 6. Observacoes de operacao
- O arquivo `config.txt` atual possui chaves em texto plano e nao deve ser usado em ambiente real sem saneamento.
- Para PAPER/LIVE com exchanges habilitadas, cadastre credenciais ativas via API de `exchange_credentials` antes de subir o worker.

## 7. Gerar instalador para cliente

Com Inno Setup instalado:

```powershell
build\windows\build_installer.ps1
```

Atalho CMD:

```cmd
build\windows\build_installer.bat
```

Artefato final:
- `dist\TradingBotSetup.exe`

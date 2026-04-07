param(
  [switch]$SkipDependencies = $false,
  [switch]$NoLaunch = $false
)

$ErrorActionPreference = "Stop"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "[TRADINGBOT] $Message" -ForegroundColor Cyan
}

function Test-PythonCandidate {
  param(
    [string]$Exe,
    [string[]]$PrefixArgs
  )
  try {
    & $Exe @PrefixArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
    return ($LASTEXITCODE -eq 0)
  }
  catch {
    return $false
  }
}

function Resolve-ProjectRoot {
  param([string]$ScriptDir)

  $candidateList = New-Object System.Collections.Generic.List[string]
  $parentDir = Split-Path -Parent $ScriptDir

  if ($ScriptDir) { $candidateList.Add($ScriptDir) }
  if ($parentDir) { $candidateList.Add($parentDir) }
  if ($ScriptDir) { $candidateList.Add((Join-Path $ScriptDir "Crypto-main")) }
  if ($ScriptDir) { $candidateList.Add((Join-Path $ScriptDir "TradingBot_LocalExecutor")) }

  $subdirs = Get-ChildItem -Path $ScriptDir -Directory -ErrorAction SilentlyContinue
  foreach ($sub in $subdirs) {
    $candidateList.Add($sub.FullName)
  }

  $seen = @{}
  foreach ($candidate in $candidateList) {
    if (-not $candidate) { continue }
    $full = [System.IO.Path]::GetFullPath($candidate)
    if ($seen.ContainsKey($full)) { continue }
    $seen[$full] = $true

    $req = Join-Path $full "requirements.txt"
    $launcher = Join-Path $full "app\launcher.py"
    if ((Test-Path $req) -and (Test-Path $launcher)) {
      return $full
    }
  }

  $tried = ($seen.Keys | Sort-Object) -join "`n - "
  throw "Nao foi possivel localizar a pasta do projeto (requirements.txt + app\\launcher.py). Caminhos verificados:`n - $tried`nExtraia o ZIP completo e execute novamente."
}

function Resolve-PythonCommand {
  $pyCmd = Get-Command py -ErrorAction SilentlyContinue
  if ($pyCmd) {
    foreach ($versionFlag in @("-3.13", "-3.12", "-3.11", "-3")) {
      if (Test-PythonCandidate -Exe "py" -PrefixArgs @($versionFlag)) {
        return @{ Exe = "py"; PrefixArgs = @($versionFlag); Display = "py $versionFlag" }
      }
    }
  }

  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd) {
    if (Test-PythonCandidate -Exe "python" -PrefixArgs @()) {
      return @{ Exe = "python"; PrefixArgs = @(); Display = "python" }
    }
  }

  $python3Cmd = Get-Command python3 -ErrorAction SilentlyContinue
  if ($python3Cmd) {
    if (Test-PythonCandidate -Exe "python3" -PrefixArgs @()) {
      return @{ Exe = "python3"; PrefixArgs = @(); Display = "python3" }
    }
  }

  throw "Python 3.11+ nao encontrado. Instale Python (marcando Add to PATH) e tente novamente."
}

function Test-VenvPython {
  param([string]$VenvPythonPath)

  if (-not (Test-Path $VenvPythonPath)) {
    return $false
  }

  try {
    & $VenvPythonPath -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
    return ($LASTEXITCODE -eq 0)
  }
  catch {
    return $false
  }
}

function Stop-StaleTradingBotProcesses {
  param([string]$ProjectRoot)

  try {
    $normalizedRoot = [System.IO.Path]::GetFullPath($ProjectRoot).ToLowerInvariant()
    $targets = Get-CimInstance Win32_Process -Filter "name='python.exe'" | Where-Object {
      $cmd = [string]$_.CommandLine
      if ([string]::IsNullOrWhiteSpace($cmd)) { return $false }
      $cmdLower = $cmd.ToLowerInvariant()
      $belongsToProject = $cmdLower.Contains($normalizedRoot)
      $hasTradingBotMarkers = (
        $cmdLower.Contains("config.windows.local.txt") -or
        $cmdLower.Contains("tradingbot") -or
        $cmdLower.Contains("state.db")
      )
      if ((-not $belongsToProject) -and (-not $hasTradingBotMarkers)) { return $false }
      return (
        ($cmdLower -match "-m\\s+app\\.launcher") -or
        ($cmdLower -match "-m\\s+api\\.server") -or
        ($cmdLower -match "-m\\s+bot(\\s|$)") -or
        ($cmdLower -match "--run-api") -or
        ($cmdLower -match "--run-worker")
      )
    }

    if (-not $targets) { return }

    Write-Step "Encerrando instancias antigas do TradingBot..."
    foreach ($proc in $targets) {
      try {
        Stop-Process -Id ([int]$proc.ProcessId) -Force -ErrorAction Stop
        Write-Host "[TRADINGBOT] Processo encerrado: PID $($proc.ProcessId)" -ForegroundColor DarkYellow
      }
      catch {
        Write-Host "[TRADINGBOT] Aviso: nao foi possivel encerrar PID $($proc.ProcessId): $($_.Exception.Message)" -ForegroundColor Yellow
      }
    }
    Start-Sleep -Milliseconds 600
  }
  catch {
    Write-Host "[TRADINGBOT] Aviso: falha ao varrer processos antigos: $($_.Exception.Message)" -ForegroundColor Yellow
  }
}

try {
  $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
  $RepoRoot = Resolve-ProjectRoot -ScriptDir $ScriptDir
  Set-Location $RepoRoot

  $requirementsPath = Join-Path $RepoRoot "requirements.txt"
  $configPath = Join-Path $RepoRoot "config.windows.local.txt"
  if (-not (Test-Path $configPath)) {
    $configPath = Join-Path $RepoRoot "config.txt"
  }
  if (-not (Test-Path $configPath)) {
    throw "Arquivo de configuracao nao encontrado (config.windows.local.txt ou config.txt)."
  }

  $venvName = ".venv-client"
  $venvPython = Join-Path $RepoRoot "$venvName\Scripts\python.exe"
  $venvPath = Join-Path $RepoRoot $venvName

  Write-Host "[TRADINGBOT] Pasta do projeto: $RepoRoot"
  if (Test-VenvPython -VenvPythonPath $venvPython) {
    Write-Step "Ambiente virtual existente encontrado em $venvName."
    Write-Host "[TRADINGBOT] Python selecionado: $venvPython"
  } else {
    if (Test-Path $venvPath) {
      Write-Step "Ambiente virtual existente invalido. Recriando $venvName..."
      Remove-Item -Path $venvPath -Recurse -Force
    }

    Write-Step "Detectando Python..."
    $python = Resolve-PythonCommand
    Write-Host "[TRADINGBOT] Python selecionado: $($python.Display)"
    Write-Step "Criando ambiente virtual ($venvName)..."
    & $python.Exe @($python.PrefixArgs) -m venv $venvName
    if ($LASTEXITCODE -ne 0) {
      throw "Falha ao criar ambiente virtual."
    }
  }

  if (-not (Test-VenvPython -VenvPythonPath $venvPython)) {
    throw "Python do ambiente virtual nao encontrado: $venvPython"
  }

  if (-not $SkipDependencies) {
    if (-not (Test-Path $requirementsPath)) {
      throw "requirements.txt nao encontrado em: $requirementsPath"
    }

    Write-Step "Atualizando pip..."
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
      throw "Falha ao atualizar pip."
    }

    Write-Step "Instalando dependencias (requirements.txt)..."
    & $venvPython -m pip install -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
      throw "Falha ao instalar dependencias."
    }
  } else {
    Write-Step "SkipDependencies ativo: pulando instalacao de dependencias."
  }

  $env:PYTHONUTF8 = "1"

  if ($NoLaunch) {
    Write-Step "NoLaunch ativo: encerrando sem iniciar app.launcher."
    exit 0
  }

  Stop-StaleTradingBotProcesses -ProjectRoot $RepoRoot

  Write-Step "Iniciando TradingBot local..."
  Write-Host "[TRADINGBOT] Painel: porta automatica (preferencia 8000; fallback 5000-5100)"
  Write-Host "[TRADINGBOT] Para encerrar: Ctrl + C"

  & $venvPython -m app.launcher --config $configPath
  exit $LASTEXITCODE
}
catch {
  Write-Host ""
  Write-Host "[TRADINGBOT] ERRO: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host "[TRADINGBOT] Verifique internet, permissao de antivirus e instalacao do Python 3.11+." -ForegroundColor Yellow
  exit 1
}

Param(
  [switch]$SkipVenv = $false
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $RepoRoot

if (-not $SkipVenv) {
  if (-not (Test-Path '.venv')) {
    py -3 -m venv .venv
  }
  $Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
  & $Python -m pip install --upgrade pip
  & $Python -m pip install -r requirements.txt
  & $Python -m pip install pyinstaller
} else {
  $Python = 'python'
}

& $Python -m PyInstaller build/windows/tradingbot.spec --noconfirm --clean

Write-Host "Build concluído: dist/TradingBot/TradingBot.exe"

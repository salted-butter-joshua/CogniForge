# Learn Loop 本地环境初始化（Windows + Conda）
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Conda = "D:\software\anaconda\Scripts\conda.exe"
$EnvName = "learn-loop"

if (-not (Test-Path $Conda)) {
    Write-Host "conda not found at $Conda"
    Write-Host "Use any Python 3.9+ and run:"
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\Activate.ps1"
    Write-Host "  python scripts/check-python.py"
    Write-Host "  pip install -r requirements.txt"
    exit 1
}

Write-Host "==> Creating conda env '$EnvName' with Python 3.11 ..."
& $Conda create -n $EnvName python=3.11 -y

Write-Host ""
Write-Host "==> Next steps:"
Write-Host "  conda activate $EnvName"
Write-Host "  cd $Root"
Write-Host "  Copy-Item .env.local.example .env   # edit MINIMAX_API_KEY"
Write-Host "  pip install -r requirements.txt"
Write-Host "  `$env:PYTHONPATH='.'"
Write-Host "  python scripts/check-redis.py"
Write-Host "  python -m src.main --urls https://example.com --task-id demo-001"

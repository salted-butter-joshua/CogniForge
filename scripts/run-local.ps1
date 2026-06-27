# Local dev runner (Windows PowerShell)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Test-Path ".env")) {
    Write-Error "Missing .env — run: Copy-Item .env.local.example .env"
}

$env:PYTHONPATH = $Root

python scripts/check-python.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Test-Path ".venv")) {
    Write-Error @"
.venv was created with Python 3.8 which is too old.
Recreate with Python 3.9+:
  Remove-Item -Recurse -Force .venv
  conda create -n learn-loop python=3.11 -y
  conda activate learn-loop
Or run: .\scripts\setup-local.ps1
"@
}

& .\.venv\Scripts\Activate.ps1

pip install -q -r requirements.txt

Write-Host "==> Checking Redis..."
python scripts/check-redis.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Starting Learn Loop..."
python -m src.main @args

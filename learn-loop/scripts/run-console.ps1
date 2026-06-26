# CogniForge Console — API + Web UI (local dev)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$ApiPort = if ($env:CONSOLE_PORT) { [int]$env:CONSOLE_PORT } else { 8080 }
$UiPort = 5173
$env:PYTHONPATH = "."
$env:CONSOLE_PORT = "$ApiPort"

# Prefer active conda env python when available
$Python = "python"
if ($env:CONDA_PREFIX) {
    $condaPy = Join-Path $env:CONDA_PREFIX "python.exe"
    if (Test-Path $condaPy) { $Python = $condaPy }
}

function Test-ApiUp([int]$Port) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 2
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-PortListening([int]$Port) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $null -ne $conn
}

if (-not (Test-Path "web\node_modules")) {
    Write-Host "==> npm install (web/)"
    Push-Location web
    npm install
    Pop-Location
}

Write-Host "==> CogniForge Console"
Write-Host "    API  http://127.0.0.1:$ApiPort/api/health"
Write-Host "    UI   http://127.0.0.1:$UiPort  (dev)  |  http://127.0.0.1:$ApiPort  (after npm run build)"

if (Test-ApiUp $ApiPort) {
    Write-Host "==> API already running on port $ApiPort — skipping second API process"
} elseif (Test-PortListening $ApiPort) {
    Write-Host "ERROR: Port $ApiPort is in use but /api/health did not respond." -ForegroundColor Red
    Write-Host "       Stop the other process or set CONSOLE_PORT to a free port, e.g.:"
    Write-Host "       `$env:CONSOLE_PORT=8082; .\scripts\run-console.ps1"
    exit 1
} else {
    Write-Host "==> Starting API in a new window..."
    $apiCmd = "cd '$PWD'; `$env:PYTHONPATH='.'; `$env:CONSOLE_PORT='$ApiPort'; & '$Python' -m src.api.server"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $apiCmd
    Start-Sleep -Seconds 2
    if (-not (Test-ApiUp $ApiPort)) {
        Write-Host "ERROR: API failed to start on port $ApiPort. Check the API window for errors." -ForegroundColor Red
        exit 1
    }
}

if (Test-PortListening $UiPort) {
    Write-Host "WARN: Port $UiPort already in use. Open http://127.0.0.1:$UiPort if Vite is already running," -ForegroundColor Yellow
    Write-Host "      or stop that process and re-run this script."
    exit 0
}

Write-Host "==> Starting Vite dev server (Ctrl+C to stop UI only; API keeps running in other window)"
Push-Location web
npm run dev

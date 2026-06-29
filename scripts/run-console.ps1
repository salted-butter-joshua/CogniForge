# CogniForge Console — API + Web UI (local dev)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$ApiPort = if ($env:CONSOLE_PORT) { [int]$env:CONSOLE_PORT } else { 8080 }
$UiPort = 5173
$env:PYTHONPATH = "."
$env:CONSOLE_PORT = "$ApiPort"

function Test-PythonUsable([string]$Exe) {
    if (-not (Test-Path $Exe)) { return $false }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe scripts/check-python.py *> $null
        if ($LASTEXITCODE -ne 0) { return $false }
        & $Exe -c "import langgraph" *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Resolve-CogniForgePython {
    if ($env:COGNIFORGE_PYTHON -and (Test-PythonUsable $env:COGNIFORGE_PYTHON)) {
        return $env:COGNIFORGE_PYTHON
    }
    if ($env:CONDA_PREFIX) {
        $condaPy = Join-Path $env:CONDA_PREFIX "python.exe"
        if (Test-PythonUsable $condaPy) { return $condaPy }
    }
    $roots = @()
    if ($env:CONDA_EXE) { $roots += (Split-Path (Split-Path $env:CONDA_EXE)) }
    if ($env:CONDA_PREFIX) { $roots += (Split-Path $env:CONDA_PREFIX) }
    $roots += "D:\software\anaconda", "$env:USERPROFILE\miniconda3", "$env:USERPROFILE\anaconda3"
    foreach ($root in ($roots | Select-Object -Unique)) {
        if (-not $root) { continue }
        $candidate = Join-Path $root "envs\learn-loop\python.exe"
        if (Test-PythonUsable $candidate) { return $candidate }
    }
    if (Test-PythonUsable "python") { return "python" }
    return $null
}

$Python = Resolve-CogniForgePython
if (-not $Python) {
    Write-Host "ERROR: No usable Python found (need >= 3.9 with langgraph installed)." -ForegroundColor Red
    Write-Host "Fix:"
    Write-Host "  conda activate learn-loop"
    Write-Host "  pip install -r requirements.txt"
    Write-Host "  .\scripts\run-console.ps1"
    Write-Host "Or set COGNIFORGE_PYTHON to your env python.exe"
    exit 1
}

Write-Host "==> Using Python: $Python"

function Test-ApiUp([int]$Port) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 3
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-ApiUp([int]$Port, [int]$TimeoutSec = 25) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-ApiUp $Port) { return $true }
        Start-Sleep -Milliseconds 750
    }
    return $false
}

function Test-ViteUp([int]$Port = 5173) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 3
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
    Write-Host "==> API already running on port $ApiPort"
} elseif (Test-PortListening $ApiPort) {
    Write-Host "ERROR: Port $ApiPort is in use but /api/health did not respond." -ForegroundColor Red
    Write-Host "       Stop the blocking process or use another port:"
    Write-Host "       `$env:CONSOLE_PORT=8082; .\scripts\run-console.ps1"
    exit 1
} else {
    Write-Host "==> Starting API in a new window..."
    $apiCmd = @"
Set-Location '$PWD'
`$env:PYTHONPATH='.'
`$env:CONSOLE_PORT='$ApiPort'
& '$Python' -m src.api.server
"@
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $apiCmd
    if (-not (Wait-ApiUp $ApiPort 25)) {
        Write-Host "ERROR: API did not become healthy on port $ApiPort within 25s." -ForegroundColor Red
        Write-Host "       Check the API PowerShell window. Common causes:"
        Write-Host "       - Used base Python without langgraph (need conda env learn-loop)"
        Write-Host "       - Missing pip install -r requirements.txt"
        exit 1
    }
    Write-Host "==> API is up on http://127.0.0.1:$ApiPort"
}

if (Test-ViteUp $UiPort) {
    Write-Host "==> Vite already serving http://127.0.0.1:$UiPort — open in browser"
} elseif (Test-PortListening $UiPort) {
    Write-Host "ERROR: Port $UiPort is in use but dev server is not responding." -ForegroundColor Red
    Write-Host "       End the stale node.exe process, then re-run this script."
    exit 1
} else {
    $env:VITE_API_PROXY = "http://127.0.0.1:$ApiPort"
    Write-Host "==> Starting Vite (Ctrl+C stops UI only; API keeps running)"
    Push-Location web
    npm run dev
}

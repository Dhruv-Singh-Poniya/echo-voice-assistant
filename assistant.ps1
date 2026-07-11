param(
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "status",
    [switch]$Open
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$StateDir = Join-Path $Root ".assistant"
$LogDir = Join-Path $StateDir "logs"
$BackendPidFile = Join-Path $StateDir "backend.pid"
$FrontendPidFile = Join-Path $StateDir "frontend.pid"
$BackendPort = 8000
$FrontendPort = 5173

function New-StateDirs {
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
}

function Quote-PSLiteral([string]$Value) {
    return "'" + ($Value -replace "'", "''") + "'"
}

function Get-PortPids([int]$Port) {
    @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

function Test-Port([int]$Port) {
    return @(Get-PortPids $Port).Count -gt 0
}

function Stop-ProcessTree([int]$ProcessId) {
    if ($ProcessId -le 0 -or $ProcessId -eq $PID) {
        return
    }

    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        Stop-ProcessTree ([int]$child.ProcessId)
    }

    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-PidFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $savedPid = Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($savedPid -match "^\d+$") {
        Stop-ProcessTree ([int]$savedPid)
    }
    Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
}

function Stop-Port([int]$Port) {
    foreach ($portPid in (Get-PortPids $Port)) {
        Stop-ProcessTree ([int]$portPid)
    }
}

function Wait-Port([int]$Port, [string]$Name) {
    for ($i = 0; $i -lt 45; $i++) {
        if (Test-Port $Port) {
            Write-Host "$Name is running on port $Port" -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 1
    }
    Write-Host "$Name did not answer on port $Port yet. Check logs in $LogDir." -ForegroundColor Yellow
}

function Start-Backend {
    if (Test-Port $BackendPort) {
        Write-Host "Backend already running on http://127.0.0.1:$BackendPort" -ForegroundColor Yellow
        return
    }

    $backendDir = Join-Path $Root "backend"
    $backendLog = Join-Path $LogDir "backend.log"
    $backendErr = Join-Path $LogDir "backend.err.log"
    $quotedBackendDir = Quote-PSLiteral $backendDir
    $command = @"
`$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $quotedBackendDir
if (-not (Test-Path '.venv')) {
    python -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path '.env')) {
    Write-Host 'WARNING: backend/.env not found. Copy .env.example to .env and add your keys.'
}
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port $BackendPort
"@

    $proc = Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $command) `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendLog `
        -RedirectStandardError $backendErr `
        -PassThru
    Set-Content -LiteralPath $BackendPidFile -Value $proc.Id
    Write-Host "Starting backend..." -ForegroundColor Cyan
}

function Start-Frontend {
    if (Test-Port $FrontendPort) {
        Write-Host "Frontend already running on http://localhost:$FrontendPort" -ForegroundColor Yellow
        return
    }

    $frontendDir = Join-Path $Root "frontend"
    $frontendLog = Join-Path $LogDir "frontend.log"
    $frontendErr = Join-Path $LogDir "frontend.err.log"
    $quotedFrontendDir = Quote-PSLiteral $frontendDir
    $command = @"
`$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $quotedFrontendDir
if (-not (Test-Path 'node_modules')) {
    npm install
}
npm run dev -- --host 127.0.0.1 --port $FrontendPort
"@

    $proc = Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $command) `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendLog `
        -RedirectStandardError $frontendErr `
        -PassThru
    Set-Content -LiteralPath $FrontendPidFile -Value $proc.Id
    Write-Host "Starting frontend..." -ForegroundColor Cyan
}

function Start-Assistant {
    New-StateDirs
    Start-Backend
    Start-Frontend
    Wait-Port $BackendPort "Backend"
    Wait-Port $FrontendPort "Frontend"
    Write-Host "Open http://localhost:$FrontendPort" -ForegroundColor Cyan
    if ($Open) {
        Start-Process "http://localhost:$FrontendPort"
    }
}

function Stop-Assistant {
    New-StateDirs
    Stop-PidFile $FrontendPidFile
    Stop-PidFile $BackendPidFile
    Stop-Port $FrontendPort
    Stop-Port $BackendPort
    Write-Host "Assistant stopped." -ForegroundColor Green
}

function Show-Status {
    $backendState = if (Test-Port $BackendPort) { "running" } else { "stopped" }
    $frontendState = if (Test-Port $FrontendPort) { "running" } else { "stopped" }
    Write-Host "Backend : $backendState  http://127.0.0.1:$BackendPort"
    Write-Host "Frontend: $frontendState http://localhost:$FrontendPort"
    Write-Host "Logs    : $LogDir"
}

switch ($Action) {
    "start" {
        Start-Assistant
    }
    "stop" {
        Stop-Assistant
    }
    "restart" {
        Stop-Assistant
        Start-Assistant
    }
    "status" {
        Show-Status
    }
}

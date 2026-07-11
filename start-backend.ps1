# Starts the FastAPI backend on http://127.0.0.1:8000
# Usage:  right-click > Run with PowerShell,  or:  ./start-backend.ps1
Set-Location "$PSScriptRoot/backend"
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}
Write-Host "Ensuring backend dependencies..." -ForegroundColor Cyan
./.venv/Scripts/python.exe -m pip install -r requirements.txt
if (-not (Test-Path ".env")) {
    Write-Host "WARNING: backend/.env not found. Copy .env.example to .env and add your keys." -ForegroundColor Yellow
}
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000

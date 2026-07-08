# Starts the React (Vite) dev server on http://localhost:5173
# Usage:  right-click > Run with PowerShell,  or:  ./start-frontend.ps1
Set-Location "$PSScriptRoot/frontend"
if (-not (Test-Path "node_modules")) {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
    npm install
}
npm run dev

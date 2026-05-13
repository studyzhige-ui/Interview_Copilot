<#
.SYNOPSIS
    Interview Copilot — Frontend-only Vite dev server
.DESCRIPTION
    独立启动前端，不依赖后端。后端 API 出问题或者根本没起来，前端仍能编译热重载；
    页面上对应的接口会失败，但路由切换、组件改样式都不受影响。
.EXAMPLE
    pwsh scripts/dev-frontend.ps1
    pwsh scripts/dev-frontend.ps1 -Port 5180 -OpenBrowser
#>
[CmdletBinding()]
param(
    [int]$Port = 5173,
    [switch]$OpenBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$frontendDir = Join-Path $projectRoot 'frontend'

function Write-Status {
    param([string]$Component, [string]$Message, [ConsoleColor]$Color = 'Cyan')
    $ts = Get-Date -Format 'HH:mm:ss'
    Write-Host "[$ts] " -NoNewline -ForegroundColor DarkGray
    Write-Host "[$Component] " -NoNewline -ForegroundColor $Color
    Write-Host $Message
}

# ─── Prerequisites ───────────────────────────────────────────────────────
if (-not (Get-Command 'npm' -ErrorAction SilentlyContinue)) {
    Write-Error 'npm is not available. Install Node.js first.'
}

if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
    Write-Status 'npm' 'frontend/node_modules missing — running npm install (first run only)...' Yellow
    Push-Location $frontendDir
    try {
        npm install 2>&1 | ForEach-Object { Write-Status 'npm-install' $_ DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Write-Error 'npm install failed.'
        }
    } finally { Pop-Location }
}

# ─── Port probing ────────────────────────────────────────────────────────
function Test-PortFree([int]$p) {
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $p)
        $listener.Start(); $listener.Stop()
        return $true
    } catch { return $false }
}

$chosenPort = $Port
if (-not (Test-PortFree $chosenPort)) {
    Write-Status 'Vite' "Port $Port already in use — probing next..." DarkYellow
    for ($p = $Port + 1; $p -lt $Port + 20; $p++) {
        if (Test-PortFree $p) { $chosenPort = $p; break }
    }
    if ($chosenPort -eq $Port) {
        Write-Error "Could not find a free port near $Port. Pass -Port <other>."
    }
    Write-Status 'Vite' "Falling back to port $chosenPort." DarkYellow
}

# ─── Launch Vite ─────────────────────────────────────────────────────────
Write-Status 'Vite' "Starting frontend dev server on port $chosenPort..." Cyan
Write-Host ''
Write-Status 'Ready' "Frontend: http://localhost:$chosenPort" Green
Write-Status 'Ready' '  /mock    新模拟面试（含 style + voice 选择）' Green
Write-Status 'Ready' '  /review  复盘页（mock + upload 共用）' Green
Write-Status 'Ready' 'Press Ctrl+C to stop the frontend (backend untouched).' White
Write-Host ''

if ($OpenBrowser) {
    Start-Job -ScriptBlock {
        param($port)
        Start-Sleep -Seconds 3
        Start-Process "http://localhost:$port"
    } -ArgumentList $chosenPort | Out-Null
}

# Run vite in the foreground so Ctrl+C stops only this script.
Push-Location $frontendDir
try {
    & npm run dev -- --port $chosenPort
} finally {
    Pop-Location
    Write-Host ''
    Write-Status 'Shutdown' 'Frontend stopped.' Red
}

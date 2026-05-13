<#
.SYNOPSIS
    Interview Copilot — 一键开发环境启动脚本（前后端解耦）
.DESCRIPTION
    本脚本是一个薄壳，在两个独立的 PowerShell 窗口里分别启动：
      - 后端窗口：Docker + alembic + uvicorn + Celery → scripts/dev-backend.ps1
      - 前端窗口：vite                                → scripts/dev-frontend.ps1
    两个窗口各自独立，互不影响：
      - 后端迁移失败或 uvicorn 崩了 → 前端窗口仍然能正常热重载页面样式
      - 前端窗口想重启 → 不动后端，关掉前端窗口重开就行
      - Ctrl+C 只关闭当前窗口
    如果你想在同一个窗口里看混合日志，直接跑 scripts/dev-backend.ps1 / dev-frontend.ps1 之一。
.PARAMETER ApiPort
    Backend uvicorn 端口（默认 8080）
.PARAMETER FrontendPort
    Frontend vite 端口（默认 5173，被占用会自动找下一个空闲端口）
.PARAMETER SkipDocker
    后端跳过 docker compose up
.PARAMETER SkipMigration
    后端跳过 alembic upgrade head
.PARAMETER SkipFrontend
    只起后端，不开前端窗口
.PARAMETER SkipBackend
    只起前端，不开后端窗口
.PARAMETER ValidateMigration
    后端先用沙盒 SQLite 演练 0007/0008 迁移
.PARAMETER OpenBrowser
    前端起好后自动打开浏览器
.EXAMPLE
    pwsh scripts/dev.ps1                                # 两窗口都开
    pwsh scripts/dev.ps1 -OpenBrowser                   # 同上 + 自动开浏览器
    pwsh scripts/dev.ps1 -SkipFrontend                  # 只开后端窗口
    pwsh scripts/dev.ps1 -SkipBackend -OpenBrowser      # 只开前端窗口
    pwsh scripts/dev.ps1 -ValidateMigration             # 后端先演练迁移再跑
#>
[CmdletBinding()]
param(
    [int]$ApiPort = 8080,
    [int]$FrontendPort = 5173,
    [switch]$SkipDocker,
    [switch]$SkipMigration,
    [switch]$SkipFrontend,
    [switch]$SkipBackend,
    [switch]$ValidateMigration,
    [switch]$OpenBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backendScript = Join-Path $PSScriptRoot 'dev-backend.ps1'
$frontendScript = Join-Path $PSScriptRoot 'dev-frontend.ps1'

if (-not (Test-Path $backendScript)) { Write-Error "Missing $backendScript" }
if (-not (Test-Path $frontendScript)) { Write-Error "Missing $frontendScript" }

function Write-Banner {
    param([string]$Message, [ConsoleColor]$Color = 'Cyan')
    Write-Host "[Launcher] " -NoNewline -ForegroundColor $Color
    Write-Host $Message
}

# ─── Spawn backend window ────────────────────────────────────────────────
if (-not $SkipBackend) {
    $backendArgs = @(
        '-NoExit',
        '-NoProfile',
        '-File', $backendScript,
        '-ApiPort', $ApiPort
    )
    if ($SkipDocker) { $backendArgs += '-SkipDocker' }
    if ($SkipMigration) { $backendArgs += '-SkipMigration' }
    if ($ValidateMigration) { $backendArgs += '-ValidateMigration' }

    Write-Banner "Spawning backend window (api on $ApiPort)..." Green
    Start-Process pwsh -ArgumentList $backendArgs -WorkingDirectory $projectRoot
}
else {
    Write-Banner 'Backend skipped (-SkipBackend).' DarkYellow
}

# ─── Spawn frontend window ───────────────────────────────────────────────
if (-not $SkipFrontend) {
    $frontendArgs = @(
        '-NoExit',
        '-NoProfile',
        '-File', $frontendScript,
        '-Port', $FrontendPort
    )
    if ($OpenBrowser) { $frontendArgs += '-OpenBrowser' }

    # Stagger by ~1s so the two windows don't fight for stdout focus.
    Start-Sleep -Milliseconds 800
    Write-Banner "Spawning frontend window (vite on $FrontendPort)..." Cyan
    Start-Process pwsh -ArgumentList $frontendArgs -WorkingDirectory $projectRoot
}
else {
    Write-Banner 'Frontend skipped (-SkipFrontend).' DarkYellow
}

Write-Host ''
Write-Banner 'Both windows launched. This launcher is done — you can close it.' Green
Write-Banner 'Backend log:  watch the new PowerShell window titled "dev-backend".' DarkGray
Write-Banner 'Frontend log: watch the new PowerShell window titled "dev-frontend".' DarkGray
Write-Banner 'To stop a service, Ctrl+C in its window. The other keeps running.' DarkGray

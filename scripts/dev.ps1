<#
.SYNOPSIS
    Interview Copilot — 一键开发环境启动脚本
.DESCRIPTION
    单条命令完成：
      Docker 基础设施 → 数据库迁移（含 0007/0008 unified schema 演练）→
      Backend API → Celery Worker → Frontend Vite dev server
    按 Ctrl+C 统一关停所有服务。
.PARAMETER ApiPort
    Backend uvicorn 端口（默认 8080）
.PARAMETER FrontendPort
    Frontend vite 端口（默认 5173）
.PARAMETER SkipDocker
    跳过 docker compose up（已经在跑就用这个）
.PARAMETER SkipMigration
    跳过 alembic upgrade head（已经迁移过用这个）
.PARAMETER SkipFrontend
    不启动前端（只跑后端 + worker 时用）
.PARAMETER ValidateMigration
    跑前先用沙盒 SQLite 演练 0007/0008 迁移，验证脚本没问题再动真库
.PARAMETER OpenBrowser
    所有服务起好后自动打开浏览器到 http://localhost:<FrontendPort>
.EXAMPLE
    pwsh scripts/dev.ps1
    pwsh scripts/dev.ps1 -ValidateMigration -OpenBrowser
    pwsh scripts/dev.ps1 -SkipFrontend     # 只跑后端
#>
[CmdletBinding()]
param(
    [int]$ApiPort = 8080,
    [int]$FrontendPort = 5173,
    [switch]$SkipDocker,
    [switch]$SkipMigration,
    [switch]$SkipFrontend,
    [switch]$ValidateMigration,
    [switch]$OpenBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ─── Conda environment ───────────────────────────────────────────────────
$condaEnv = 'Interview_Copilot'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backendDir = Join-Path $projectRoot 'backend'
$frontendDir = Join-Path $projectRoot 'frontend'

function Write-Status {
    param([string]$Component, [string]$Message, [ConsoleColor]$Color = 'Cyan')
    $ts = Get-Date -Format 'HH:mm:ss'
    Write-Host "[$ts] " -NoNewline -ForegroundColor DarkGray
    Write-Host "[$Component] " -NoNewline -ForegroundColor $Color
    Write-Host $Message
}

# ─── Verify prerequisites ────────────────────────────────────────────────
Write-Status 'Init' 'Verifying prerequisites...' Yellow

if (-not (Get-Command 'conda' -ErrorAction SilentlyContinue)) {
    Write-Error 'conda is not available. Please install Anaconda/Miniconda first.'
}
if (-not $SkipDocker -and -not (Get-Command 'docker' -ErrorAction SilentlyContinue)) {
    Write-Error 'docker is not available. Install Docker Desktop or use -SkipDocker.'
}
if (-not $SkipFrontend) {
    if (-not (Get-Command 'npm' -ErrorAction SilentlyContinue)) {
        Write-Error 'npm is not available. Install Node.js or use -SkipFrontend.'
    }
    if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
        Write-Status 'Init' 'frontend/node_modules missing — running npm install (first run only)...' Yellow
        Push-Location $frontendDir
        try {
            npm install 2>&1 | ForEach-Object { Write-Status 'npm-install' $_ DarkGray }
            if ($LASTEXITCODE -ne 0) {
                Write-Error 'npm install failed; cannot start frontend.'
            }
        }
        finally {
            Pop-Location
        }
    }
}

# Activate conda environment
Write-Status 'Init' "Activating conda environment: $condaEnv" Yellow
$condaBase = (conda info --base 2>$null).Trim()
$condaHook = Join-Path $condaBase 'shell\condabin\conda-hook.ps1'
if (Test-Path $condaHook) {
    . $condaHook
}
conda activate $condaEnv 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to activate conda environment '$condaEnv'. Does it exist?"
}
Write-Status 'Init' "Conda environment '$condaEnv' activated." Green

# ─── Docker infrastructure ───────────────────────────────────────────────
if (-not $SkipDocker) {
    Write-Status 'Docker' 'Starting infrastructure containers...' Magenta
    Push-Location $projectRoot
    try {
        docker compose up -d 2>&1 | ForEach-Object { Write-Status 'Docker' $_ DarkGray }
    }
    finally {
        Pop-Location
    }

    Write-Status 'Docker' 'Waiting for PostgreSQL to accept connections...' Magenta
    $maxWait = 30
    for ($i = 0; $i -lt $maxWait; $i++) {
        docker exec interview_copilot_db pg_isready -U postgres 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 1
    }
    if ($i -eq $maxWait) {
        Write-Warning 'PostgreSQL did not become ready in time. Continuing anyway...'
    }
    else {
        Write-Status 'Docker' 'PostgreSQL is ready.' Green
    }

    Write-Status 'Docker' 'Waiting for Redis...' Magenta
    for ($i = 0; $i -lt 15; $i++) {
        $pong = docker exec interview_copilot_redis redis-cli ping 2>$null
        if ($pong -eq 'PONG') { break }
        Start-Sleep -Seconds 1
    }
    Write-Status 'Docker' 'Redis is ready.' Green
}
else {
    Write-Status 'Docker' 'Skipped (--SkipDocker).' DarkYellow
}

# ─── Optional: dry-run migration on a sandbox SQLite first ───────────────
# Runs 0006 → 0007 → 0008 against a temp DB with fixture data; aborts the
# whole script if migration assertions fail. Use this when you've just
# pulled new migrations and want a safety net before touching the real DB.
if ($ValidateMigration) {
    Write-Status 'Alembic' 'Validating 0007 + 0008 on sandbox SQLite first...' Blue
    Push-Location $backendDir
    try {
        $env:PYTHONIOENCODING = 'utf-8'
        & python scripts/validate_migration.py 2>&1 | ForEach-Object { Write-Status 'Validate' $_ DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Write-Error 'Migration validation failed — aborting startup. See output above.'
        }
        Write-Status 'Validate' 'Sandbox migration assertions passed.' Green
    }
    finally {
        Pop-Location
    }
}

# ─── Database migration ──────────────────────────────────────────────────
if (-not $SkipMigration) {
    Write-Status 'Alembic' 'Running database migrations on live DB...' Blue
    Push-Location $projectRoot
    try {
        alembic upgrade head 2>&1 | ForEach-Object { Write-Status 'Alembic' $_ DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'Alembic migration returned non-zero exit code.'
        }
        else {
            Write-Status 'Alembic' 'Migrations applied successfully.' Green
        }
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Status 'Alembic' 'Skipped (--SkipMigration).' DarkYellow
}

# ─── Start backend services ──────────────────────────────────────────────
Write-Status 'API' "Starting uvicorn on port $ApiPort..." Green
$uvicornJob = Start-Job -Name 'uvicorn' -ScriptBlock {
    param($dir, $port, $condaBase, $condaEnv)
    Set-Location $dir
    $hook = Join-Path $condaBase 'shell\condabin\conda-hook.ps1'
    if (Test-Path $hook) { . $hook }
    conda activate $condaEnv 2>$null
    & uvicorn app.main:app --reload --port $port 2>&1
} -ArgumentList $backendDir, $ApiPort, $condaBase, $condaEnv

Write-Status 'Celery' 'Starting Celery worker...' Yellow
$celeryJob = Start-Job -Name 'celery' -ScriptBlock {
    param($dir, $condaBase, $condaEnv)
    Set-Location $dir
    $hook = Join-Path $condaBase 'shell\condabin\conda-hook.ps1'
    if (Test-Path $hook) { . $hook }
    conda activate $condaEnv 2>$null
    & celery -A app.worker.celery_app.celery_app worker --loglevel=info --pool=solo 2>&1
} -ArgumentList $backendDir, $condaBase, $condaEnv

# ─── Frontend (Vite dev server) ──────────────────────────────────────────
$frontendJob = $null
if (-not $SkipFrontend) {
    Write-Status 'Vite' "Starting frontend dev server on port $FrontendPort..." Cyan
    $frontendJob = Start-Job -Name 'vite' -ScriptBlock {
        param($dir, $port)
        Set-Location $dir
        $env:PORT = $port
        # --strictPort so we fail loudly instead of silently picking a different
        # port if 5173 is taken; the user can pass -FrontendPort to retry.
        & npm run dev -- --port $port --strictPort 2>&1
    } -ArgumentList $frontendDir, $FrontendPort
}
else {
    Write-Status 'Vite' 'Skipped (--SkipFrontend).' DarkYellow
}

# ─── Log streaming + graceful shutdown ────────────────────────────────────
$logDir = Join-Path $projectRoot 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ("dev-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

Write-Host ''
Write-Status 'Ready' '=== All services started ===' Green
Write-Status 'Ready' "API:       http://localhost:$ApiPort" Green
Write-Status 'Ready' "API docs:  http://localhost:$ApiPort/docs" Green
if (-not $SkipFrontend) {
    Write-Status 'Ready' "Frontend:  http://localhost:$FrontendPort" Green
    Write-Status 'Ready' "  /mock    新模拟面试（含 style + voice 选择）" Green
    Write-Status 'Ready' "  /review  复盘页（mock + upload 共用）" Green
}
Write-Status 'Ready' "Log:       $logFile" Green
Write-Status 'Ready' 'Press Ctrl+C to stop all services.' White
Write-Host ''

if ($OpenBrowser -and -not $SkipFrontend) {
    # Vite needs ~2-4s to bind; give it a moment so the first hit doesn't 404.
    Start-Sleep -Seconds 4
    Start-Process "http://localhost:$FrontendPort"
}

$jobs = @($uvicornJob, $celeryJob)
$colors = @{ 'uvicorn' = 'Green'; 'celery' = 'Yellow'; 'vite' = 'Cyan' }
if ($frontendJob) {
    $jobs += $frontendJob
}

# Patterns we silently drop from the live console (still written to the log
# file so nothing is lost). Reduces the noise the user complained about.
$dropPatterns = @(
    'TF32',
    'TensorFloat-32',
    'pyannote.audio.utils.reproducibility',
    'pyannote/audio/utils/reproducibility',
    'reproducibility.py',
    'It can be re-enabled by calling',
    '>>> import torch',
    '>>> torch.backends',
    'See https://github.com/pyannote/pyannote-audio/issues/1370',
    'warnings.warn',
    'UserWarning: std',
    'pyannote/audio/models/blocks/pooling',
    'pooling.py:',
    'std = sequences.std',
    'Lightning automatically upgraded',
    'lightning.pytorch.utilities.upgrade_checkpoint',
    'ReproducibilityWarning'
)

function Test-ShouldDrop {
    param([string]$Line)
    if ([string]::IsNullOrWhiteSpace($Line)) { return $true }   # collapse blank lines
    foreach ($p in $dropPatterns) {
        if ($Line -match [regex]::Escape($p)) { return $true }
    }
    return $false
}

function Format-LogLine {
    param([string]$Line)
    # Strip the leading "YYYY-MM-DD HH:MM:SS,fff: " timestamp that loguru/std
    # logging adds — dev.ps1 already prepends its own [HH:mm:ss] timestamp so
    # the duplicate is wasted horizontal space.
    return ($Line -replace '^\[?\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[,.]\d+\]?\s*', '' `
                  -replace '^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+', '')
}

try {
    while ($true) {
        foreach ($job in $jobs) {
            $output = Receive-Job -Job $job -ErrorAction SilentlyContinue
            if ($output) {
                $color = $colors[$job.Name]
                foreach ($line in $output) {
                    $text = [string]$line
                    # Always persist the raw line to the log file.
                    Add-Content -LiteralPath $logFile -Value ("[{0}] [{1}] {2}" -f (Get-Date -Format 'HH:mm:ss'), $job.Name, $text)
                    if (Test-ShouldDrop $text) { continue }
                    Write-Status $job.Name (Format-LogLine $text) $color
                }
            }
            if ($job.State -eq 'Completed' -or $job.State -eq 'Failed') {
                Write-Status $job.Name "Process exited unexpectedly (state: $($job.State))" Red
                $remaining = Receive-Job -Job $job -ErrorAction SilentlyContinue
                if ($remaining) {
                    foreach ($line in $remaining) {
                        Write-Status $job.Name "$line" Red
                    }
                }
            }
        }
        Start-Sleep -Milliseconds 500
    }
}
finally {
    Write-Host ''
    Write-Status 'Shutdown' 'Stopping services...' Red

    foreach ($job in $jobs) {
        Write-Status 'Shutdown' "Stopping $($job.Name)..." Red
        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }

    Write-Status 'Shutdown' "All services stopped. Full log: $logFile" Red
}

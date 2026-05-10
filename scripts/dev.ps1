<#
.SYNOPSIS
    Interview Copilot — 一键开发环境启动脚本
.DESCRIPTION
    单条命令完成：Docker 基础设施 → 数据库迁移 → Backend API → Celery Worker
    按 Ctrl+C 统一关停所有服务。
.EXAMPLE
    pwsh scripts/dev.ps1
#>
[CmdletBinding()]
param(
    [int]$ApiPort = 8080,
    [switch]$SkipDocker,
    [switch]$SkipMigration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ─── Conda environment ───────────────────────────────────────────────────
$condaEnv = 'Interview_Copilot'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backendDir = Join-Path $projectRoot 'backend'

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

# ─── Database migration ──────────────────────────────────────────────────
if (-not $SkipMigration) {
    Write-Status 'Alembic' 'Running database migrations...' Blue
    Push-Location $backendDir
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

# ─── Log streaming + graceful shutdown ────────────────────────────────────
Write-Host ''
Write-Status 'Ready' '=== All services started ===' Green
Write-Status 'Ready' "API:    http://localhost:$ApiPort" Green
Write-Status 'Ready' "Docs:   http://localhost:$ApiPort/docs" Green
Write-Status 'Ready' 'Press Ctrl+C to stop all services.' White
Write-Host ''

$jobs = @($uvicornJob, $celeryJob)
$colors = @{ 'uvicorn' = 'Green'; 'celery' = 'Yellow' }

try {
    while ($true) {
        foreach ($job in $jobs) {
            $output = Receive-Job -Job $job -ErrorAction SilentlyContinue
            if ($output) {
                $color = $colors[$job.Name]
                foreach ($line in $output) {
                    Write-Status $job.Name "$line" $color
                }
            }
            # Check if job unexpectedly stopped
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

    Write-Status 'Shutdown' 'All services stopped.' Red
}

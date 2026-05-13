<#
.SYNOPSIS
    Interview Copilot — Backend-only 启动脚本
.DESCRIPTION
    Docker 基础设施 → 可选迁移演练 → alembic upgrade head → uvicorn + Celery
    Ctrl+C 关停后端两个服务（前端不受影响）。
.EXAMPLE
    pwsh scripts/dev-backend.ps1
    pwsh scripts/dev-backend.ps1 -ValidateMigration
    pwsh scripts/dev-backend.ps1 -SkipDocker -SkipMigration
#>
[CmdletBinding()]
param(
    [int]$ApiPort = 8080,
    [switch]$SkipDocker,
    [switch]$SkipMigration,
    [switch]$ValidateMigration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Force UTF-8 so Chinese / emoji from python output render correctly. This was
# the source of `⚠️` and "鈿狅笍" garbage in previous logs.
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = 'utf-8'
$OutputEncoding = [System.Text.UTF8Encoding]::new()

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

# ─── Prerequisites ───────────────────────────────────────────────────────
Write-Status 'Init' 'Verifying prerequisites...' Yellow
if (-not (Get-Command 'conda' -ErrorAction SilentlyContinue)) {
    Write-Error 'conda is not available. Install Anaconda/Miniconda first.'
}
if (-not $SkipDocker -and -not (Get-Command 'docker' -ErrorAction SilentlyContinue)) {
    Write-Error 'docker is not available. Install Docker Desktop or use -SkipDocker.'
}

Write-Status 'Init' "Activating conda environment: $condaEnv" Yellow
$condaBase = (conda info --base 2>$null).Trim()
$condaHook = Join-Path $condaBase 'shell\condabin\conda-hook.ps1'
if (Test-Path $condaHook) { . $condaHook }
conda activate $condaEnv 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to activate conda environment '$condaEnv'."
}
Write-Status 'Init' "Conda environment '$condaEnv' activated." Green

# ─── Docker ──────────────────────────────────────────────────────────────
if (-not $SkipDocker) {
    Write-Status 'Docker' 'Starting infrastructure containers...' Magenta
    Push-Location $projectRoot
    try {
        docker compose up -d 2>&1 | ForEach-Object { Write-Status 'Docker' $_ DarkGray }
    } finally { Pop-Location }

    Write-Status 'Docker' 'Waiting for PostgreSQL...' Magenta
    for ($i = 0; $i -lt 30; $i++) {
        docker exec interview_copilot_db pg_isready -U postgres 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 1
    }
    Write-Status 'Docker' 'PostgreSQL is ready.' Green

    Write-Status 'Docker' 'Waiting for Redis...' Magenta
    for ($i = 0; $i -lt 15; $i++) {
        $pong = docker exec interview_copilot_redis redis-cli ping 2>$null
        if ($pong -eq 'PONG') { break }
        Start-Sleep -Seconds 1
    }
    Write-Status 'Docker' 'Redis is ready.' Green
} else {
    Write-Status 'Docker' 'Skipped (-SkipDocker).' DarkYellow
}

# ─── Migration validation (optional, sandbox) ────────────────────────────
if ($ValidateMigration) {
    Write-Status 'Alembic' 'Validating 0007 + 0008 on sandbox SQLite first...' Blue
    Push-Location $backendDir
    try {
        & python scripts/validate_migration.py 2>&1 | ForEach-Object { Write-Status 'Validate' $_ DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Write-Error 'Migration validation failed — aborting startup.'
        }
        Write-Status 'Validate' 'Sandbox migration assertions passed.' Green
    } finally { Pop-Location }
}

# ─── Live migration ──────────────────────────────────────────────────────
if (-not $SkipMigration) {
    Write-Status 'Alembic' 'Running database migrations on live DB...' Blue
    Push-Location $projectRoot
    try {
        alembic upgrade head 2>&1 | ForEach-Object { Write-Status 'Alembic' $_ DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'Alembic migration returned non-zero exit code. uvicorn will refuse to start until this is fixed.'
        } else {
            Write-Status 'Alembic' 'Migrations applied successfully.' Green
        }
    } finally { Pop-Location }
} else {
    Write-Status 'Alembic' 'Skipped (-SkipMigration).' DarkYellow
}

# ─── Backend services ────────────────────────────────────────────────────
Write-Status 'API' "Starting uvicorn on port $ApiPort..." Green
$uvicornJob = Start-Job -Name 'uvicorn' -ScriptBlock {
    param($dir, $port, $condaBase, $condaEnv)
    Set-Location $dir
    $hook = Join-Path $condaBase 'shell\condabin\conda-hook.ps1'
    if (Test-Path $hook) { . $hook }
    conda activate $condaEnv 2>$null
    $env:PYTHONIOENCODING = 'utf-8'
    & uvicorn app.main:app --reload --port $port 2>&1
} -ArgumentList $backendDir, $ApiPort, $condaBase, $condaEnv

Write-Status 'Celery' 'Starting Celery worker...' Yellow
$celeryJob = Start-Job -Name 'celery' -ScriptBlock {
    param($dir, $condaBase, $condaEnv)
    Set-Location $dir
    $hook = Join-Path $condaBase 'shell\condabin\conda-hook.ps1'
    if (Test-Path $hook) { . $hook }
    conda activate $condaEnv 2>$null
    $env:PYTHONIOENCODING = 'utf-8'
    & celery -A app.worker.celery_app.celery_app worker --loglevel=info --pool=solo 2>&1
} -ArgumentList $backendDir, $condaBase, $condaEnv

# ─── Log streaming ───────────────────────────────────────────────────────
$logDir = Join-Path $projectRoot 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ("backend-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

Write-Host ''
Write-Status 'Ready' '=== Backend services started ===' Green
Write-Status 'Ready' "API:      http://localhost:$ApiPort" Green
Write-Status 'Ready' "API docs: http://localhost:$ApiPort/docs" Green
Write-Status 'Ready' "Log:      $logFile" Green
Write-Status 'Ready' 'Press Ctrl+C to stop backend (frontend untouched).' White
Write-Host ''

$jobs = @($uvicornJob, $celeryJob)
$colors = @{ 'uvicorn' = 'Green'; 'celery' = 'Yellow' }

$dropPatterns = @(
    'TF32', 'TensorFloat-32',
    'pyannote.audio.utils.reproducibility', 'pyannote/audio/utils/reproducibility',
    'reproducibility.py', 'It can be re-enabled by calling',
    '>>> import torch', '>>> torch.backends',
    'See https://github.com/pyannote/pyannote-audio/issues/1370',
    'warnings.warn', 'UserWarning: std',
    'pyannote/audio/models/blocks/pooling', 'pooling.py:',
    'std = sequences.std',
    'Lightning automatically upgraded', 'lightning.pytorch.utilities.upgrade_checkpoint',
    'ReproducibilityWarning'
)

function Test-ShouldDrop {
    param([string]$Line)
    if ([string]::IsNullOrWhiteSpace($Line)) { return $true }
    foreach ($p in $dropPatterns) {
        if ($Line -match [regex]::Escape($p)) { return $true }
    }
    return $false
}

function Format-LogLine {
    param([string]$Line)
    return ($Line -replace '^\[?\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[,.]\d+\]?\s*', '' `
                  -replace '^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+', '')
}

$reportedDead = @{}
try {
    while ($true) {
        foreach ($job in $jobs) {
            $output = Receive-Job -Job $job -ErrorAction SilentlyContinue
            if ($output) {
                $color = $colors[$job.Name]
                foreach ($line in $output) {
                    $text = [string]$line
                    Add-Content -LiteralPath $logFile -Value ("[{0}] [{1}] {2}" -f (Get-Date -Format 'HH:mm:ss'), $job.Name, $text)
                    if (Test-ShouldDrop $text) { continue }
                    Write-Status $job.Name (Format-LogLine $text) $color
                }
            }
            if (($job.State -eq 'Completed' -or $job.State -eq 'Failed') -and -not $reportedDead[$job.Name]) {
                Write-Status $job.Name "Process exited (state: $($job.State)). Other services keep running; Ctrl+C to stop them too." Red
                $reportedDead[$job.Name] = $true
            }
        }
        Start-Sleep -Milliseconds 500
    }
}
finally {
    Write-Host ''
    Write-Status 'Shutdown' 'Stopping backend services...' Red
    foreach ($job in $jobs) {
        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
    Write-Status 'Shutdown' "All backend services stopped. Full log: $logFile" Red
}

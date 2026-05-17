<#
.SYNOPSIS
    Interview Copilot — daily development startup (Windows / PowerShell 7+).
.DESCRIPTION
    Idempotent. Brings everything up in the current console window:
      1. docker compose up -d           (no-op if already running)
      2. alembic upgrade head           (no-op if already at head)
      3. uvicorn (backend, --reload)    -> background job
      4. celery worker                  -> background job
      5. vite dev server (frontend)     -> background job

    All three job streams are merged into this one console with
    color-coded prefixes. Ctrl+C stops everything cleanly.

    Run scripts/setup.ps1 once before the first time you call this.

.PARAMETER ApiPort
    Backend port (default 8080).
.PARAMETER FrontendPort
    Frontend port (default 5173; auto-bumps if taken).
.PARAMETER SkipBackend
    Only start the frontend.
.PARAMETER SkipFrontend
    Only start the backend (uvicorn + celery).

.EXAMPLE
    pwsh scripts/start.ps1
    pwsh scripts/start.ps1 -SkipFrontend
#>
[CmdletBinding()]
param(
    [int]$ApiPort = 8080,
    [int]$FrontendPort = 5173,
    [switch]$SkipBackend,
    [switch]$SkipFrontend
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

try { chcp 65001 > $null } catch { }
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8       = '1'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backendDir  = Join-Path $projectRoot 'backend'
$frontendDir = Join-Path $projectRoot 'frontend'

function Log {
    param([string]$Tag, [string]$Message, [ConsoleColor]$Color = 'Cyan')
    Write-Host ("[{0}] " -f (Get-Date -Format 'HH:mm:ss')) -NoNewline -ForegroundColor DarkGray
    Write-Host ("[{0}] " -f $Tag) -NoNewline -ForegroundColor $Color
    Write-Host $Message
}

function Find-FreePort([int]$start) {
    for ($p = $start; $p -lt $start + 20; $p++) {
        try {
            $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $p)
            $l.Start(); $l.Stop(); return $p
        } catch { continue }
    }
    throw "No free port near $start."
}

# -----------------------------------------------------------------------------
# 1. Sanity checks (light — setup.ps1 already did the heavy lifting)
# -----------------------------------------------------------------------------
if (-not $SkipBackend) {
    if (-not (Get-Command 'python' -ErrorAction SilentlyContinue)) {
        Log 'Init' 'python not found. Activate your env, or run scripts/setup.ps1 first.' Red
        exit 1
    }

    # Windows + conda + `pwsh script.ps1` gotcha: launching the script via a
    # new pwsh process re-runs the user's profile, whose conda init hook may
    # reset PATH back to base — losing the parent shell's `conda activate`.
    # If the parent had a non-base env active but our python is base, try to
    # re-activate it inside this subshell.
    if ($env:CONDA_DEFAULT_ENV -and $env:CONDA_DEFAULT_ENV -ne 'base') {
        $wantEnv = $env:CONDA_DEFAULT_ENV
        $pyDir   = Split-Path ((& python -c 'import sys; print(sys.executable)') 2>&1).Trim() -Parent
        if ($pyDir -notlike "*\envs\$wantEnv*") {
            Log 'Init' "Subshell lost conda activation; re-activating '$wantEnv'..." Yellow
            $condaBase = (& conda info --base 2>$null)
            if ($condaBase) {
                $hookPath = Join-Path $condaBase.Trim() 'shell\condabin\conda-hook.ps1'
                if (Test-Path $hookPath) { . $hookPath }
            }
            conda activate $wantEnv 2>$null
        }
    }

    & python -c "import fastapi, alembic, uvicorn, celery" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Log 'Init' 'Backend dependencies are missing. Run scripts/setup.ps1.' Red
        Log 'Init' "Or launch without 'pwsh' prefix: .\scripts\start.ps1" DarkYellow
        exit 1
    }
}

# -----------------------------------------------------------------------------
# 2. Docker infrastructure (idempotent)
# -----------------------------------------------------------------------------
if (-not $SkipBackend) {
    Log 'Docker' 'docker compose up -d ...' Magenta
    Push-Location $projectRoot
    try {
        docker compose up -d 2>&1 | ForEach-Object { Log 'Docker' $_ DarkGray }
    } finally { Pop-Location }

    Log 'Docker' 'Waiting for postgres...' Magenta
    for ($i = 0; $i -lt 30; $i++) {
        docker exec interview_copilot_db pg_isready -U postgres 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { Log 'Docker' 'postgres ready' Green; break }
        Start-Sleep -Seconds 1
    }
}

# -----------------------------------------------------------------------------
# 3. Alembic (idempotent)
# -----------------------------------------------------------------------------
if (-not $SkipBackend) {
    Log 'Alembic' 'upgrade head ...' Blue
    Push-Location $projectRoot
    try {
        & python -c "from alembic.config import CommandLine; CommandLine().main(['upgrade','head'])" 2>&1 |
            ForEach-Object { Log 'Alembic' $_ DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Log 'Alembic' 'Migration failed. Backend will refuse to start until fixed.' Red
            exit 1
        }
    } finally { Pop-Location }
}

# -----------------------------------------------------------------------------
# 4. Background jobs
# -----------------------------------------------------------------------------
$jobs   = @()
$colors = @{}

if (-not $SkipBackend) {
    Log 'API' "uvicorn -> http://localhost:$ApiPort" Green
    $j = Start-Job -Name 'uvicorn' -ScriptBlock {
        param($dir, $port)
        Set-Location $dir
        $env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUTF8 = '1'
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
        & python -m uvicorn app.main:app --reload --port $port 2>&1
    } -ArgumentList $backendDir, $ApiPort
    $jobs += $j; $colors[$j.Name] = 'Green'

    Log 'Celery' 'worker -> --pool=solo' Yellow
    $j = Start-Job -Name 'celery' -ScriptBlock {
        param($dir)
        Set-Location $dir
        $env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUTF8 = '1'
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
        & python -m celery -A app.worker.celery_app.celery_app worker --loglevel=info --pool=solo 2>&1
    } -ArgumentList $backendDir
    $jobs += $j; $colors[$j.Name] = 'Yellow'
}

if (-not $SkipFrontend) {
    if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
        Log 'npm' 'node_modules missing — running npm install (one-time)' Yellow
        Push-Location $frontendDir
        try { npm install | Out-Host } finally { Pop-Location }
    }
    $port = Find-FreePort $FrontendPort
    if ($port -ne $FrontendPort) { Log 'Vite' "Port $FrontendPort taken; using $port" DarkYellow }
    Log 'Vite' "vite -> http://localhost:$port" Cyan
    $j = Start-Job -Name 'vite' -ScriptBlock {
        param($dir, $p)
        Set-Location $dir
        # vite (node) outputs UTF-8 (➜ arrow + Chinese plugin names). Without
        # chcp 65001 the parent PowerShell decodes it as GBK on Windows
        # → "鈿狅笍" / "鈻 " garbage. Set both the codepage and the .NET
        # encoding object so the Receive-Job side sees clean bytes.
        try { chcp 65001 > $null } catch { }
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
        $env:FORCE_COLOR = '1'
        & npm run dev -- --port $p 2>&1
    } -ArgumentList $frontendDir, $port
    $jobs += $j; $colors[$j.Name] = 'Cyan'
}

if ($jobs.Count -eq 0) {
    Log 'Done' 'Nothing to start (-SkipBackend and -SkipFrontend both set).' DarkYellow
    return
}

# -----------------------------------------------------------------------------
# 5. Log streaming
# -----------------------------------------------------------------------------
# Name the log file after which mode is running so two parallel tabs (backend +
# frontend) write to clearly-distinct files: backend-YYYYMMDD-HHMMSS.log /
# frontend-YYYYMMDD-HHMMSS.log / both-... (when nothing is skipped).
$logDir = Join-Path $projectRoot 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logRole = if ($SkipFrontend) { 'backend' }
           elseif ($SkipBackend) { 'frontend' }
           else { 'both' }
$logFile = Join-Path $logDir ("{0}-{1}.log" -f $logRole, (Get-Date -Format 'yyyyMMdd-HHmmss'))

Write-Host ''
Log 'Ready' '====== Services started — Ctrl+C to stop all ======' Green
Log 'Ready' "Log file: $logFile" Green
Write-Host ''

# Drop noisy lines that pyannote / lightning emit on every cold start.
$dropPatterns = @(
    'TF32', 'TensorFloat-32',
    'pyannote.audio.utils.reproducibility', 'pyannote/audio/utils/reproducibility',
    'reproducibility.py', 'It can be re-enabled by calling',
    '>>> import torch', '>>> torch.backends',
    'See https://github.com/pyannote/pyannote-audio/issues/1370',
    'warnings.warn', 'UserWarning: std',
    'pyannote/audio/models/blocks/pooling', 'pooling.py:',
    'Lightning automatically upgraded',
    'lightning.pytorch.utilities.upgrade_checkpoint',
    'ReproducibilityWarning'
)
function ShouldDrop([string]$line) {
    if ([string]::IsNullOrWhiteSpace($line)) { return $true }
    foreach ($p in $dropPatterns) { if ($line -match [regex]::Escape($p)) { return $true } }
    return $false
}
function Trim-Timestamp([string]$line) {
    return ($line -replace '^\[?\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[,.]\d+\]?\s*', '' `
                  -replace '^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+', '')
}

$reportedDead = @{}
try {
    while ($true) {
        foreach ($job in $jobs) {
            $output = Receive-Job -Job $job -ErrorAction SilentlyContinue
            foreach ($line in $output) {
                $text = [string]$line
                Add-Content -LiteralPath $logFile -Value ("[{0}] [{1}] {2}" -f (Get-Date -Format 'HH:mm:ss'), $job.Name, $text)
                if (ShouldDrop $text) { continue }
                Log $job.Name (Trim-Timestamp $text) $colors[$job.Name]
            }
            if (($job.State -eq 'Completed' -or $job.State -eq 'Failed') -and -not $reportedDead[$job.Name]) {
                Log $job.Name "exited (state: $($job.State))" Red
                $reportedDead[$job.Name] = $true
            }
        }
        Start-Sleep -Milliseconds 500
    }
} finally {
    Write-Host ''
    Log 'Shutdown' 'Stopping jobs...' Red
    foreach ($job in $jobs) {
        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
    Log 'Shutdown' "Done. Full log: $logFile" Red
}

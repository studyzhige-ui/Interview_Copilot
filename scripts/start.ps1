<#
.SYNOPSIS
    Interview Copilot — daily development startup (Windows / PowerShell 7+).
.DESCRIPTION
    Idempotent. Brings everything up in the current console window:
      1. docker compose up -d --wait    (no-op if already running)
      2. alembic upgrade head           (no-op if already at head)
      3. uvicorn (backend, --reload)    -> background job
      4. celery worker + beat           -> background jobs
      5. vite dev server (frontend)     -> background job

    The console shows a concise, color-coded status view. Complete job streams
    are written to data/logs. Ctrl+C stops everything cleanly.

    Run scripts/setup.ps1 once before the first time you call this.

.PARAMETER ApiPort
    Backend port (default 8080).
.PARAMETER FrontendPort
    Frontend port (default 5173; auto-bumps if taken).
.PARAMETER SkipBackend
    Only start the frontend.
.PARAMETER SkipFrontend
    Only start the backend (uvicorn + celery).
.PARAMETER VerboseLogs
    Stream detailed Docker and service logs to the console. Full logs are
    always written under data/logs even when this switch is omitted.

.EXAMPLE
    pwsh scripts/start.ps1
    pwsh scripts/start.ps1 -SkipFrontend
#>
[CmdletBinding()]
param(
    [int]$ApiPort = 8080,
    [int]$FrontendPort = 5173,
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$VerboseLogs
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
$runtimeTemp = Join-Path $projectRoot 'data/tmp'
$pycacheDir  = Join-Path $projectRoot 'data/cache/pycache'
New-Item -ItemType Directory -Force -Path $runtimeTemp, $pycacheDir | Out-Null
$env:TEMP = $runtimeTemp
$env:TMP = $runtimeTemp
$env:PYTHONPYCACHEPREFIX = $pycacheDir

$logDir = Join-Path $projectRoot 'data/logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logRole = if ($SkipFrontend) { 'backend' }
           elseif ($SkipBackend) { 'frontend' }
           else { 'both' }
$logFile = Join-Path $logDir ("{0}-{1}.log" -f $logRole, (Get-Date -Format 'yyyyMMdd-HHmmss'))

function Log {
    param([string]$Tag, [string]$Message, [ConsoleColor]$Color = 'Cyan')
    Write-Host ("[{0}] " -f (Get-Date -Format 'HH:mm:ss')) -NoNewline -ForegroundColor DarkGray
    Write-Host ("[{0}] " -f $Tag) -NoNewline -ForegroundColor $Color
    Write-Host $Message
}

function Save-CommandOutput {
    param(
        [string]$Tag,
        [object[]]$Lines,
        [ConsoleColor]$Color = 'DarkGray',
        [switch]$Show
    )
    foreach ($line in $Lines) {
        $text = [string]$line
        if ([string]::IsNullOrWhiteSpace($text)) { continue }
        Add-Content -LiteralPath $logFile -Value ("[{0}] [{1}] {2}" -f (Get-Date -Format 'HH:mm:ss'), $Tag, $text)
        if ($Show -or $VerboseLogs) { Log $Tag $text $Color }
    }
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
    Log 'Docker' 'starting long-running infrastructure ...' Magenta
    Push-Location $projectRoot
    try {
        $dockerOutput = @(docker compose up -d --wait --wait-timeout 180 `
            db redis minio milvus-etcd milvus-minio milvus-standalone 2>&1)
        $dockerExit = $LASTEXITCODE
        Save-CommandOutput 'Docker' $dockerOutput
        if ($dockerExit -ne 0) {
            Save-CommandOutput 'Docker' ($dockerOutput | Select-Object -Last 20) -Show
            Log 'Docker' 'Infrastructure did not become healthy.' Red
            Log 'Docker' "Details: $logFile" DarkYellow
            exit 1
        }
        $bucketOutput = @(docker compose run --rm --no-deps minio-create-bucket 2>&1)
        $bucketExit = $LASTEXITCODE
        Save-CommandOutput 'Docker' $bucketOutput
        if ($bucketExit -ne 0) {
            Save-CommandOutput 'Docker' $bucketOutput -Show
            Log 'Docker' 'MinIO bucket initialization failed.' Red
            Log 'Docker' "Details: $logFile" DarkYellow
            exit 1
        }
    } finally { Pop-Location }
    Log 'Docker' 'infrastructure healthy' Green
}

# -----------------------------------------------------------------------------
# 3. Alembic (idempotent)
# -----------------------------------------------------------------------------
if (-not $SkipBackend) {
    Log 'Alembic' 'upgrade head ...' Blue
    Push-Location $projectRoot
    try {
        $migrationOutput = @(& python -c "from alembic.config import CommandLine; CommandLine().main(['upgrade','head'])" 2>&1)
        $migrationExit = $LASTEXITCODE
        Save-CommandOutput 'Alembic' $migrationOutput
        if ($migrationExit -ne 0) {
            Save-CommandOutput 'Alembic' $migrationOutput -Show
            Log 'Alembic' 'Migration failed. Backend will refuse to start until fixed.' Red
            Log 'Alembic' "Details: $logFile" DarkYellow
            exit 1
        }
    } finally { Pop-Location }
    Log 'Alembic' 'schema is current' Green
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

    Log 'Celery' 'jobs worker -> default,background,pipeline,transcription; --pool=solo' Yellow
    $j = Start-Job -Name 'celery' -ScriptBlock {
        param($dir)
        Set-Location $dir
        $env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUTF8 = '1'
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
        & python -m celery -A app.task_queue.celery_app.celery_app worker --loglevel=info --pool=solo --queues=default,background,pipeline,transcription 2>&1
    } -ArgumentList $backendDir
    $jobs += $j; $colors[$j.Name] = 'Yellow'

    Log 'Turns' 'conversation worker -> turns; --pool=threads' DarkCyan
    $j = Start-Job -Name 'turns' -ScriptBlock {
        param($dir)
        Set-Location $dir
        $env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUTF8 = '1'
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
        & python -m celery -A app.task_queue.celery_app.celery_app worker --loglevel=info --pool=threads --concurrency=2 --queues=turns 2>&1
    } -ArgumentList $backendDir
    $jobs += $j; $colors[$j.Name] = 'DarkCyan'

    Log 'Beat' 'scheduler' Magenta
    $j = Start-Job -Name 'beat' -ScriptBlock {
        param($dir, $schedulePath)
        Set-Location $dir
        $env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUTF8 = '1'
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
        & python -m celery -A app.task_queue.celery_app.celery_app beat --loglevel=info --schedule $schedulePath 2>&1
    } -ArgumentList $backendDir, (Join-Path $projectRoot 'data/runtime/celerybeat-schedule')
    $jobs += $j; $colors[$j.Name] = 'Magenta'
}

if (-not $SkipFrontend) {
    if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
        Log 'npm' 'node_modules missing — running npm ci (one-time)' Yellow
        Push-Location $frontendDir
        try { npm ci --no-audit --no-fund | Out-Host } finally { Pop-Location }
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
Write-Host ''
Log 'Starting' 'Processes launched; waiting for application readiness ...' Green
Log 'Starting' "Log file: $logFile" Green
if (-not $VerboseLogs) { Log 'Starting' 'Console mode: concise (use -VerboseLogs for full output)' DarkGray }
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
function ShouldShow([string]$line) {
    if (ShouldDrop $line) { return $false }
    if ($VerboseLogs) { return $true }
    return $line -match '(?i)(\bWARNING\b|\bERROR\b|\bCRITICAL\b|Traceback|Exception|failed|startup sequence (begins|complete)|Application startup complete|VITE v.+ready|Local:\s+http|RAG embedding ready|Reranker ready|WhisperX (加载|ready)|Pyannote diarization ready|Worker voice runtime ready|celery@.+ ready\.|model_catalog seed loaded)'
}
function Trim-Timestamp([string]$line) {
    return ($line -replace '^\[?\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[,.]\d+\]?\s*', '' `
                  -replace '^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+', '')
}

$reportedDead = @{}
$readyState = @{}
foreach ($job in $jobs) { $readyState[$job.Name] = $false }
$allReadyReported = $false
$applicationUrl = if (-not $SkipFrontend) { "http://localhost:$port" } else { "http://localhost:$ApiPort" }
try {
    while ($true) {
        foreach ($job in $jobs) {
            $output = Receive-Job -Job $job -ErrorAction SilentlyContinue
            foreach ($line in $output) {
                $text = [string]$line
                Add-Content -LiteralPath $logFile -Value ("[{0}] [{1}] {2}" -f (Get-Date -Format 'HH:mm:ss'), $job.Name, $text)
                $becameReady = switch ($job.Name) {
                    'uvicorn' { $text -match 'Application startup complete'; break }
                    'celery' { $text -match 'celery@.+ ready\.'; break }
                    'turns' { $text -match 'celery@.+ ready\.'; break }
                    'beat' { $text -match 'beat: Starting'; break }
                    'vite' { $text -match 'VITE v.+ready'; break }
                    default { $false }
                }
                if ($becameReady) { $readyState[$job.Name] = $true }
                if (-not (ShouldShow $text)) { continue }
                Log $job.Name (Trim-Timestamp $text) $colors[$job.Name]
            }
            if (-not $allReadyReported -and $readyState.Values -notcontains $false) {
                Write-Host ''
                Log 'Ready' "Application ready -> $applicationUrl" Green
                Log 'Ready' 'Press Ctrl+C to stop all processes.' Green
                Write-Host ''
                $allReadyReported = $true
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

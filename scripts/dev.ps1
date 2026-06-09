<#
.SYNOPSIS
    Interview Copilot — 个人开发启动脚本（前后端可分离运行）

.DESCRIPTION
    单窗口、内联运行。三种用法：

    A. 默认：一个 tab 里都起
        .\scripts\dev.ps1
        前后端日志合一，Ctrl+C 一并退出。

    B. 前后端分两个 IDE tab 跑（推荐日常开发）
        Tab 1：.\scripts\dev.ps1 -Backend
        Tab 2：.\scripts\dev.ps1 -Frontend
        各自独立 Ctrl+C / 重启，互不影响。

    C. 跳过某步
        .\scripts\dev.ps1 -Backend -SkipDocker     # docker 已起
        .\scripts\dev.ps1 -Backend -SkipMigration  # 不想 alembic
        .\scripts\dev.ps1 -Backend -Workers 4      # uvicorn 多 worker

    脚本会自动 `conda activate Interview_Copilot`，所以你**不需要**先切环境。
    在 (base) 或者别的 env 里都行，进来直接帮你切对。

    用 `.\scripts\dev.ps1`（dot-prefix）启动，而不是 `pwsh scripts/dev.ps1`。
    后者会开子进程，可能丢 conda 激活；脚本兼容这种情况，但每次重新激活
    会慢一两秒。

.PARAMETER Backend
    只起后端（docker + alembic + uvicorn + celery）。与 -Frontend 互斥。
.PARAMETER Frontend
    只起前端（vite）。不跑 docker / alembic。
.PARAMETER ApiPort
    uvicorn 端口（默认 8080）。
.PARAMETER FrontendPort
    vite 端口（默认 5173，被占用自动顺延）。
.PARAMETER Workers
    uvicorn worker 数（默认 1）。本脚本是“启动器”，不开热重载；开发时想热重载，
    在另一个终端自己跑：uvicorn app.main:app --reload --reload-dir app（在 backend/ 下）。
.PARAMETER SkipDocker
    跳过 docker compose up -d。
.PARAMETER SkipMigration
    跳过 alembic upgrade head。
.PARAMETER OpenBrowser
    vite 起好后自动打开浏览器（仅 -Frontend 或默认模式生效）。
.PARAMETER CondaEnv
    conda env 名字。默认 Interview_Copilot。改这个等于"用别的 env 跑"。
#>
[CmdletBinding()]
param(
    [switch]$Backend,
    [switch]$Frontend,
    [int]$ApiPort = 8080,
    [int]$FrontendPort = 5173,
    [int]$Workers = 1,
    [switch]$SkipDocker,
    [switch]$SkipMigration,
    [switch]$OpenBrowser,
    [string]$CondaEnv = 'Interview_Copilot'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# -Backend / -Frontend 是正向开关；内部翻成 Skip* 复用现有分支。
if ($Backend -and $Frontend) {
    Write-Error '-Backend and -Frontend are mutually exclusive. Omit both to run everything.'
}
$RunBackend  = -not $Frontend
$RunFrontend = -not $Backend

# ─── UTF-8 setup (so 中文 / emoji / vite ➜ 不乱码) ────────────────────────
try { chcp 65001 > $null } catch { }
[Console]::InputEncoding  = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding           = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8       = '1'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backendDir  = Join-Path $projectRoot 'backend'
$frontendDir = Join-Path $projectRoot 'frontend'

# ─── Logging helpers ──────────────────────────────────────────────────────
function Say {
    param([string]$Tag, [string]$Message, [ConsoleColor]$Color = 'Cyan')
    Write-Host ("[{0}] " -f (Get-Date -Format 'HH:mm:ss')) -NoNewline -ForegroundColor DarkGray
    Write-Host ("[{0}] " -f $Tag) -NoNewline -ForegroundColor $Color
    Write-Host $Message
}

function Test-PortFree([int]$p) {
    try {
        $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $p)
        $l.Start(); $l.Stop()
        return $true
    } catch { return $false }
}

# ─── Mode banner ──────────────────────────────────────────────────────────
$mode = if ($Backend)      { 'BACKEND ONLY  (docker + alembic + uvicorn + celery)' }
        elseif ($Frontend) { 'FRONTEND ONLY (vite)' }
        else               { 'ALL (backend + frontend in one tab)' }
Write-Host ''
Write-Host "==> dev.ps1  mode: $mode" -ForegroundColor Cyan
Write-Host "    project:        $projectRoot" -ForegroundColor DarkGray
Write-Host ''

# ─── Ensure the right conda env is active ────────────────────────────────
# Borrows the proven approach from the old dev-backend.ps1: source conda's
# PowerShell hook and `conda activate` from inside the script. This makes
# the script work regardless of:
#   - whether parent shell is (base) or already (Interview_Copilot)
#   - whether you launched with `.\dev.ps1` (current shell) or `pwsh dev.ps1`
#     (subshell that loses activation on Windows)
function Invoke-EnsureCondaEnv {
    param([string]$WantEnv)

    if (-not (Get-Command 'conda' -ErrorAction SilentlyContinue)) {
        Write-Error "conda not on PATH. Install Anaconda/Miniconda, or pass -CondaEnv (your venv path won't help — this script assumes conda)."
    }

    # Source conda's hook so `conda activate` is a function, not just an exe.
    # Without sourcing, `conda activate` runs as a subprocess and can't
    # mutate the current shell's PATH/env.
    $condaBase = (& conda info --base 2>$null)
    if (-not $condaBase) {
        Write-Error 'conda info --base failed. Conda install may be broken.'
    }
    $hookPath = Join-Path $condaBase.Trim() 'shell\condabin\conda-hook.ps1'
    if (-not (Test-Path $hookPath)) {
        Write-Error "Conda PowerShell hook not found: $hookPath"
    }
    . $hookPath

    # Always activate, even if prompt claims we're already in $WantEnv —
    # a `pwsh script.ps1` subshell often shows the right prompt but has
    # the wrong PATH. A redundant activate is cheap; a wrong PATH is fatal.
    conda activate $WantEnv 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host ''
        Write-Host "  conda activate $WantEnv failed." -ForegroundColor Red
        Write-Host '  Check the env exists: conda env list' -ForegroundColor Yellow
        Write-Host '  If missing, create it (Python 3.10 / 3.11 / 3.12 all work):' -ForegroundColor Yellow
        Write-Host "      conda create -n $WantEnv python=3.11 -y" -ForegroundColor White
        Write-Host "      conda activate $WantEnv" -ForegroundColor White
        Write-Host '      pip install -r requirements.txt' -ForegroundColor White
        Write-Error "Conda activate failed for env '$WantEnv'."
    }

    # Verify python.exe actually moved into the env (catches "empty env" —
    # the directory exists in conda metadata but has no Python inside).
    $pyExe = (& python -c "import sys; print(sys.executable)" 2>&1).ToString().Trim()
    if ((Split-Path $pyExe -Parent) -notlike "*\envs\$WantEnv*") {
        Write-Host ''
        Write-Host "  Activated $WantEnv but python is still at: $pyExe" -ForegroundColor Red
        Write-Host "  → env '$WantEnv' has no Python installed (it's an empty shell)." -ForegroundColor Yellow
        Write-Host '  Rebuild it:' -ForegroundColor Yellow
        Write-Host "      conda env remove -n $WantEnv -y" -ForegroundColor White
        Write-Host "      conda create -n $WantEnv python=3.11 -y" -ForegroundColor White
        Write-Host "      conda activate $WantEnv" -ForegroundColor White
        Write-Host '      pip install -r requirements.txt' -ForegroundColor White
        Write-Error "Conda env '$WantEnv' has no Python."
    }
    return $pyExe
}

Say 'Init' "Activating conda env: $CondaEnv" Yellow
$pyExe = Invoke-EnsureCondaEnv -WantEnv $CondaEnv
$pyVer = (& python --version 2>&1).ToString().Trim()
Say 'Init' "Python: $pyVer" Green
Say 'Init' "Path:   $pyExe" Green

# ─── Backend prereq: dep + tool checks ────────────────────────────────────
if ($RunBackend) {
    # docker is needed unless explicitly skipped.
    if (-not $SkipDocker -and -not (Get-Command 'docker' -ErrorAction SilentlyContinue)) {
        Write-Error 'docker not on PATH. Install Docker Desktop, or pass -SkipDocker.'
    }

    # Backend deps sanity check — catches "you forgot pip install -r requirements.txt".
    & python -c "import fastapi, alembic, uvicorn, celery, slowapi" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  Backend Python deps missing.' -ForegroundColor Red
        Write-Host '  Fix: pip install -r requirements.txt' -ForegroundColor Yellow
        Write-Error 'Backend deps check failed.'
    }
    Say 'Init' 'Backend deps OK (fastapi, alembic, uvicorn, celery, slowapi)' Green
}

if ($RunFrontend) {
    if (-not (Get-Command 'npm' -ErrorAction SilentlyContinue)) {
        Write-Error 'npm not on PATH. Install Node.js 20+, or pass -Backend to skip frontend.'
    }
}

# ─── Docker infrastructure ────────────────────────────────────────────────
if ($RunBackend -and -not $SkipDocker) {
    Say 'Docker' 'docker compose up -d ...' Magenta
    Push-Location $projectRoot
    try {
        docker compose up -d 2>&1 | ForEach-Object { Say 'Docker' $_ DarkGray }
    } finally { Pop-Location }

    Say 'Docker' 'Waiting for PostgreSQL...' Magenta
    for ($i = 0; $i -lt 30; $i++) {
        docker exec interview_copilot_db pg_isready -U postgres 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 1
    }
    Say 'Docker' 'PostgreSQL ready' Green

    Say 'Docker' 'Waiting for Redis...' Magenta
    for ($i = 0; $i -lt 15; $i++) {
        $pong = docker exec interview_copilot_redis redis-cli ping 2>$null
        if ($pong -eq 'PONG') { break }
        Start-Sleep -Seconds 1
    }
    Say 'Docker' 'Redis ready' Green
}

# ─── Database migrations ──────────────────────────────────────────────────
if ($RunBackend -and -not $SkipMigration) {
    Say 'Alembic' 'upgrade head ...' Blue
    # alembic 1.x has no __main__.py, so `python -m alembic` doesn't work.
    # Use the CommandLine entry point directly — equivalent to console_script
    # and doesn't depend on alembic.exe being on PATH.
    Push-Location $projectRoot
    try {
        & python -c "from alembic.config import CommandLine; CommandLine().main(['upgrade','head'])" 2>&1 |
            ForEach-Object { Say 'Alembic' $_ DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Write-Error 'alembic upgrade head failed. Fix the migration before retrying.'
        }
    } finally { Pop-Location }
    Say 'Alembic' 'schema up to date' Green
}

# ─── Frontend prep (first-run npm install + port probe) ───────────────────
$chosenFrontPort = $FrontendPort
if ($RunFrontend) {
    if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
        Say 'npm' 'node_modules missing — running npm install (one-time)' Yellow
        Push-Location $frontendDir
        try {
            npm install 2>&1 | ForEach-Object { Say 'npm-install' $_ DarkGray }
            if ($LASTEXITCODE -ne 0) { Write-Error 'npm install failed.' }
        } finally { Pop-Location }
    }

    if (-not (Test-PortFree $FrontendPort)) {
        Say 'Vite' "Port $FrontendPort taken; probing next..." DarkYellow
        for ($p = $FrontendPort + 1; $p -lt $FrontendPort + 20; $p++) {
            if (Test-PortFree $p) { $chosenFrontPort = $p; break }
        }
        Say 'Vite' "Using port $chosenFrontPort" DarkYellow
    }
}

# ─── Background jobs ──────────────────────────────────────────────────────
$jobs   = @()
$colors = @{}

if ($RunBackend) {
    $modeText = if ($Workers -gt 1) { "$Workers workers" } else { '1 worker' }
    Say 'API' "uvicorn @ port $ApiPort  -  $modeText" Green
    $uvJob = Start-Job -Name 'uvicorn' -ScriptBlock {
        param($dir, $port, $workers)
        Set-Location $dir
        $env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUTF8 = '1'
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
        # This is a LAUNCHER, not a dev-reload tool — deliberately NO --reload.
        # Each reload re-runs the FastAPI lifespan, which re-loads the embedding
        # + reranker models (slow + GPU churn, and on a single GPU the overlap
        # with the old process can OOM/hang). For hot reload while developing,
        # run in a SEPARATE terminal (from backend/):
        #     uvicorn app.main:app --reload --reload-dir app --port 8080
        if ($workers -gt 1) {
            & python -m uvicorn app.main:app --workers $workers --port $port --host 0.0.0.0 2>&1
        } else {
            & python -m uvicorn app.main:app --port $port 2>&1
        }
    } -ArgumentList $backendDir, $ApiPort, $Workers
    $jobs += $uvJob; $colors[$uvJob.Name] = 'Green'

    Say 'Celery' 'worker (--pool=solo)' Yellow
    $celeryJob = Start-Job -Name 'celery' -ScriptBlock {
        param($dir)
        Set-Location $dir
        $env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUTF8 = '1'
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
        & python -m celery -A app.worker.celery_app.celery_app worker --loglevel=info --pool=solo 2>&1
    } -ArgumentList $backendDir
    $jobs += $celeryJob; $colors[$celeryJob.Name] = 'Yellow'
}

if ($RunFrontend) {
    Say 'Vite' "vite @ port $chosenFrontPort" Cyan
    $viteJob = Start-Job -Name 'vite' -ScriptBlock {
        param($dir, $port)
        Set-Location $dir
        try { chcp 65001 > $null } catch { }
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
        $env:FORCE_COLOR = '1'
        & npm run dev -- --port $port 2>&1
    } -ArgumentList $frontendDir, $chosenFrontPort
    $jobs += $viteJob; $colors[$viteJob.Name] = 'Cyan'

    if ($OpenBrowser) {
        Start-Job -ScriptBlock {
            param($port)
            Start-Sleep -Seconds 4
            Start-Process "http://localhost:$port"
        } -ArgumentList $chosenFrontPort | Out-Null
    }
}

if ($jobs.Count -eq 0) {
    Say 'Done' 'Nothing to start.' DarkYellow
    return
}

# ─── Log file ─────────────────────────────────────────────────────────────
$logDir = Join-Path $projectRoot 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ("dev-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

Write-Host ''
Say 'Ready' '====== Services started ======' Green
if ($RunBackend)  { Say 'Ready' "API:      http://localhost:$ApiPort       (docs: /docs)" Green }
if ($RunFrontend) { Say 'Ready' "Frontend: http://localhost:$chosenFrontPort" Green }
Say 'Ready' "Log file: $logFile" Green
Say 'Ready' 'Press Ctrl+C to stop all.' White
Write-Host ''

# ─── Noisy-line filters (pyannote / lightning emit screen-fuls on cold start) ─
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
function ShouldDrop([string]$line) {
    if ([string]::IsNullOrWhiteSpace($line)) { return $true }
    foreach ($p in $dropPatterns) { if ($line -match [regex]::Escape($p)) { return $true } }
    return $false
}
function StripTimestamp([string]$line) {
    return ($line -replace '^\[?\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[,.]\d+\]?\s*', '' `
                  -replace '^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+', '')
}

# ─── Log-streaming loop ───────────────────────────────────────────────────
$reportedDead = @{}
try {
    while ($true) {
        foreach ($job in $jobs) {
            $output = Receive-Job -Job $job -ErrorAction SilentlyContinue
            foreach ($line in $output) {
                $text = [string]$line
                Add-Content -LiteralPath $logFile -Value ("[{0}] [{1}] {2}" -f (Get-Date -Format 'HH:mm:ss'), $job.Name, $text)
                if (ShouldDrop $text) { continue }
                Say $job.Name (StripTimestamp $text) $colors[$job.Name]
            }
            if (($job.State -eq 'Completed' -or $job.State -eq 'Failed') -and -not $reportedDead[$job.Name]) {
                Say $job.Name "exited (state: $($job.State))" Red
                $reportedDead[$job.Name] = $true
            }
        }
        Start-Sleep -Milliseconds 500
    }
} finally {
    Write-Host ''
    Say 'Shutdown' 'Stopping all jobs...' Red
    foreach ($job in $jobs) {
        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
    Say 'Shutdown' "Done. Full log: $logFile" Red
}

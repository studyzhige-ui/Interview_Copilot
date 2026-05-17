<#
.SYNOPSIS
    Interview Copilot — one-time bootstrap (Windows / PowerShell 7+).
.DESCRIPTION
    Brings a fresh clone to a "ready to develop" state. Run this once
    after cloning. For everyday startup, use scripts/start.ps1.

    What this script does:
      1. Verify prerequisites (docker, npm, python in supported range)
      2. Verify you're in an activated venv / conda env (not system Python)
      3. pip install -r requirements.txt
      4. Create .env from a template if missing (interactive)
      5. Generate SECRET_KEY if blank
      6. docker compose up -d  +  wait for postgres / redis
      7. alembic upgrade head
      8. cd frontend && npm install

    What this script does NOT do:
      - Create or activate your Python environment. Do that yourself first.
      - Download Whisper / Pyannote model weights. Run
        `python scripts/init_models.py` separately if you chose full mode.

.EXAMPLE
    # Activate your env first, then:
    pwsh scripts/setup.ps1
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

try { chcp 65001 > $null } catch { }
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8       = '1'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$frontendDir = Join-Path $projectRoot 'frontend'

function Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok([string]$msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "    $msg" -ForegroundColor Yellow }
function Fail([string]$msg) { Write-Host "    $msg" -ForegroundColor Red; exit 1 }

# -----------------------------------------------------------------------------
# 1. Prerequisites
# -----------------------------------------------------------------------------
Step 'Checking prerequisites'

foreach ($cmd in @('docker', 'npm', 'python')) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Fail "$cmd is not on PATH. Install it (or activate your env) and retry."
    }
}

# Python version: require 3.10 / 3.11 / 3.12. 3.13 has no whisperx/pyannote
# wheels yet; <3.10 is unsupported by torch 2.x and pydantic v2.
$pyVer = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
if ($pyVer -notin @('3.10', '3.11', '3.12')) {
    Fail "Python $pyVer is not supported. Use 3.10, 3.11, or 3.12. (3.13 lacks ML wheels.)"
}
Ok "python $pyVer  ($((& python -c 'import sys; print(sys.executable)' 2>&1).Trim()))"

# Verify the user is in an isolated env. Installing 3 GB of ML deps into
# system / base Python is almost always a mistake — refuse unless the user
# acknowledges with -Force (not exposed; intentional friction).
$inVenv  = [bool]$env:VIRTUAL_ENV
$inConda = [bool]$env:CONDA_PREFIX -and ($env:CONDA_PREFIX -ne $env:CONDA_PREFIX_1)
if (-not ($inVenv -or $inConda)) {
    Warn 'You appear to be using the system / conda-base Python.'
    Warn 'Installing ~3 GB of dependencies here will pollute it.'
    Warn 'Recommended:'
    Warn '    python -m venv .venv && .\.venv\Scripts\Activate.ps1'
    Warn '  or'
    Warn '    conda create -n interview-copilot python=3.12 -y && conda activate interview-copilot'
    Fail 'Activate an isolated env first, then re-run this script.'
}
Ok 'isolated environment detected'

# -----------------------------------------------------------------------------
# 2. Python dependencies
# -----------------------------------------------------------------------------
Step 'Installing Python dependencies (this can take 5-15 min on first run)'
Push-Location $projectRoot
try {
    & python -m pip install --upgrade pip
    & python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Fail 'pip install failed.' }
} finally { Pop-Location }
Ok 'requirements.txt installed'

# -----------------------------------------------------------------------------
# 3. .env scaffolding
# -----------------------------------------------------------------------------
Step 'Configuring .env'
$envFile = Join-Path $projectRoot '.env'
if (Test-Path $envFile) {
    Ok '.env already exists, leaving it alone'
} else {
    Write-Host '    Choose a starting template:' -ForegroundColor Cyan
    Write-Host '      [1] API-light   — all cloud APIs, no GPU, no model downloads (~5 min to first chat)'
    Write-Host '      [2] Local-models — embeddings/reranker/ASR run locally (needs GPU for speed)'
    $choice = Read-Host '    Enter 1 or 2'
    $template = if ($choice -eq '2') { '.env.example' } else { '.env.example.lite' }
    Copy-Item (Join-Path $projectRoot $template) $envFile
    Ok "Copied $template -> .env"
    Warn 'Remember to fill in your API keys before the first run.'
}

$envFileForDocker = Join-Path $projectRoot '.env.docker'
if (-not (Test-Path $envFileForDocker)) {
    Copy-Item (Join-Path $projectRoot '.env.docker.example') $envFileForDocker
    Ok 'Copied .env.docker.example -> .env.docker'
}

# Auto-generate SECRET_KEY if blank.
$envContent = Get-Content $envFile -Raw
if ($envContent -match '(?m)^SECRET_KEY=\s*$') {
    $newKey = & python -c "import secrets; print(secrets.token_urlsafe(48))"
    $envContent = $envContent -replace '(?m)^SECRET_KEY=\s*$', "SECRET_KEY=$newKey"
    Set-Content -LiteralPath $envFile -Value $envContent -NoNewline -Encoding utf8NoBOM
    Ok 'Generated a fresh SECRET_KEY into .env'
}

# -----------------------------------------------------------------------------
# 4. Infrastructure
# -----------------------------------------------------------------------------
Step 'Starting Docker infrastructure (postgres, redis, minio, milvus)'
Push-Location $projectRoot
try {
    docker compose up -d | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail 'docker compose up failed.' }
} finally { Pop-Location }

Step 'Waiting for postgres to accept connections'
for ($i = 0; $i -lt 30; $i++) {
    docker exec interview_copilot_db pg_isready -U postgres 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok 'postgres ready'; break }
    Start-Sleep -Seconds 1
}

# -----------------------------------------------------------------------------
# 5. Database migrations
# -----------------------------------------------------------------------------
Step 'Running database migrations'
Push-Location $projectRoot
try {
    & python -c "from alembic.config import CommandLine; CommandLine().main(['upgrade','head'])"
    if ($LASTEXITCODE -ne 0) { Fail 'alembic upgrade head failed.' }
} finally { Pop-Location }
Ok 'schema is up to date'

# -----------------------------------------------------------------------------
# 6. Frontend
# -----------------------------------------------------------------------------
Step 'Installing frontend dependencies'
Push-Location $frontendDir
try {
    npm install
    if ($LASTEXITCODE -ne 0) { Fail 'npm install failed.' }
} finally { Pop-Location }
Ok 'frontend deps installed'

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
Write-Host ''
Write-Host '==================================================================' -ForegroundColor Green
Write-Host '  Setup complete.' -ForegroundColor Green
Write-Host '==================================================================' -ForegroundColor Green
Write-Host ''
Write-Host '  Next steps:'
Write-Host '    1. Open .env and fill in any provider API keys you want to use'
Write-Host '       (DEEPSEEK_API_KEY at minimum, for the LLM).'
Write-Host '    2. (full mode only) python scripts/init_models.py'
Write-Host '       — downloads Whisper / Pyannote weights for local inference.'
Write-Host '    3. .\scripts\start.ps1'
Write-Host '       — every-day startup (uvicorn + celery + vite, single window).'
Write-Host '       (Note: use the .\ prefix, NOT `pwsh scripts/start.ps1` — the'
Write-Host '        latter spawns a child shell that drops your conda activation.)'
Write-Host ''

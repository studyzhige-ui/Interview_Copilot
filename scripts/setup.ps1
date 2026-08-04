<#
.SYNOPSIS
    Interview Copilot — one-time bootstrap (Windows / PowerShell 7+).
.DESCRIPTION
    Brings a fresh clone to a "ready to develop" state. Run this once
    after cloning. For everyday startup, use scripts/start.ps1.

    What this script does:
      1. Choose an edition and create .env if missing
      2. Choose the Community model profile (remote / local CPU / local CUDA)
      3. Verify prerequisites and install the matching dependencies
      4. Generate SECRET_KEY if blank
      5. docker compose up -d --wait for healthy infrastructure
      6. alembic upgrade head
      7. cd frontend && npm ci
      8. Configure/download the selected local model profile

    What this script does NOT do:
      - Create or activate your Python environment. Do that yourself first.

.EXAMPLE
    # Activate your env first, then:
    pwsh scripts/setup.ps1
#>
[CmdletBinding()]
param(
    [switch]$LocalModels,
    [switch]$Cuda,
    [ValidateSet('remote', 'local-cpu', 'local-cuda')]
    [string]$ModelProfile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

try { chcp 65001 > $null } catch { }
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8       = '1'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$frontendDir = Join-Path $projectRoot 'frontend'
$envFile = Join-Path $projectRoot '.env'

function Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok([string]$msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "    $msg" -ForegroundColor Yellow }
function Fail([string]$msg) { Write-Host "    $msg" -ForegroundColor Red; exit 1 }

# -----------------------------------------------------------------------------
# 1. Edition
# -----------------------------------------------------------------------------
Step 'Configuring edition'
if (Test-Path $envFile) {
    $editionMatch = [regex]::Match(
        (Get-Content -LiteralPath $envFile -Raw -Encoding utf8),
        '(?m)^APP_EDITION=(cloud|community)\s*$'
    )
    $edition = if ($editionMatch.Success) { $editionMatch.Groups[1].Value } else { 'community' }
    Ok ".env already exists; using $edition edition"
} else {
    Write-Host '    Choose an edition:' -ForegroundColor Cyan
    Write-Host '      [1] Community — GitHub self-hosted edition with full developer controls'
    Write-Host '      [2] Cloud     — hosted Web profile with managed foundation models'
    $choice = Read-Host '    Enter 1 or 2'
    $edition = if ($choice -eq '2') { 'cloud' } else { 'community' }
    $template = ".env.$edition.example"
    Copy-Item (Join-Path $projectRoot $template) $envFile
    Ok "Copied $template -> .env"
}
$communityModelProfile = 'managed'
if ($edition -eq 'community') {
    if ($LocalModels -and $Cuda) {
        Fail 'Use either -LocalModels or -Cuda, not both.'
    }
    if ($ModelProfile -and ($LocalModels -or $Cuda)) {
        Fail 'Use -ModelProfile or the legacy -LocalModels/-Cuda switches, not both.'
    }
    if ($ModelProfile) {
        $communityModelProfile = $ModelProfile
    } elseif ($Cuda) {
        $communityModelProfile = 'local-cuda'
    } elseif ($LocalModels) {
        $communityModelProfile = 'local-cpu'
    } else {
        Write-Host '    Choose a Community model profile:' -ForegroundColor Cyan
        Write-Host '      [1] Lightweight remote — API providers, no large local models'
        Write-Host '      [2] Local / hybrid CPU — choose local capabilities and models'
        Write-Host '      [3] Local / hybrid CUDA — NVIDIA acceleration'
        $profileChoice = Read-Host '    Enter 1, 2, or 3'
        $communityModelProfile = switch ($profileChoice) {
            '2' { 'local-cpu' }
            '3' { 'local-cuda' }
            default { 'remote' }
        }
    }
    Ok "Community model profile: $communityModelProfile"
}

$dependencyArgs = if ($edition -eq 'cloud') {
    @('install', '-e', '.[dev]')
} else {
    if ($communityModelProfile -eq 'local-cuda') {
        @(
            'install',
            '--extra-index-url', 'https://download.pytorch.org/whl/cu129',
            '-e', '.[local,cuda,dev]'
        )
    } elseif ($communityModelProfile -eq 'local-cpu') {
        @('install', '-e', '.[local,dev]')
    } else {
        @('install', '-e', '.[dev]')
    }
}

# -----------------------------------------------------------------------------
# 2. Prerequisites
# -----------------------------------------------------------------------------
Step 'Checking prerequisites'

foreach ($cmd in @('docker', 'npm', 'python')) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Fail "$cmd is not on PATH. Install it (or activate your env) and retry."
    }
}

$pyVer = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
$supportedVersions = @('3.11', '3.12', '3.13')
if ($pyVer -notin $supportedVersions) {
    Fail "Python $pyVer is not supported for $edition. Use $($supportedVersions -join ', ')."
}
Ok "python $pyVer  ($((& python -c 'import sys; print(sys.executable)' 2>&1).Trim()))"

# Verify the user is in an isolated env. Installing ML dependencies into
# system / base Python is almost always a mistake — refuse unless the user
# acknowledges with -Force (not exposed; intentional friction).
$inVenv  = [bool]$env:VIRTUAL_ENV
$inConda = [bool]$env:CONDA_PREFIX -and ($env:CONDA_PREFIX -ne $env:CONDA_PREFIX_1)
if (-not ($inVenv -or $inConda)) {
    Warn 'You appear to be using the system / conda-base Python.'
    Warn 'Installing project dependencies here will pollute it.'
    Warn 'Recommended:'
    Warn '    python -m venv .venv && .\.venv\Scripts\Activate.ps1'
    Warn '  or'
    Warn '    conda create -n interview-copilot python=3.12 -y && conda activate interview-copilot'
    Fail 'Activate an isolated env first, then re-run this script.'
}
Ok 'isolated environment detected'

# -----------------------------------------------------------------------------
# 3. Python dependencies
# -----------------------------------------------------------------------------
Step 'Installing Python dependencies (this can take 5-15 min on first run)'
Push-Location $projectRoot
try {
    & python -m pip install --upgrade pip
    & python -m pip @dependencyArgs
    if ($LASTEXITCODE -ne 0) { Fail 'pip install failed.' }
} finally { Pop-Location }
Ok "$edition development dependencies installed from pyproject.toml"

# -----------------------------------------------------------------------------
# 4. Secret
# -----------------------------------------------------------------------------
# Auto-generate SECRET_KEY if blank.
$envContent = Get-Content $envFile -Raw
if ($envContent -match '(?m)^SECRET_KEY=\s*$') {
    $newKey = & python -c "import secrets; print(secrets.token_urlsafe(48))"
    $envContent = $envContent -replace '(?m)^SECRET_KEY=\s*$', "SECRET_KEY=$newKey"
    Set-Content -LiteralPath $envFile -Value $envContent -NoNewline -Encoding utf8NoBOM
    Ok 'Generated a fresh SECRET_KEY into .env'
}

# -----------------------------------------------------------------------------
# 5. Infrastructure
# -----------------------------------------------------------------------------
Step 'Starting Docker infrastructure (postgres, redis, minio, milvus)'
Push-Location $projectRoot
try {
    docker compose up -d --wait --wait-timeout 180 `
        db redis minio milvus-etcd milvus-minio milvus-standalone | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail 'Infrastructure did not become healthy.' }
    docker compose run --rm --no-deps minio-create-bucket | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail 'MinIO bucket initialization failed.' }
} finally { Pop-Location }
Ok 'infrastructure healthy'

# -----------------------------------------------------------------------------
# 6. Database migrations
# -----------------------------------------------------------------------------
Step 'Running database migrations'
Push-Location $projectRoot
try {
    & python -c "from alembic.config import CommandLine; CommandLine().main(['upgrade','head'])"
    if ($LASTEXITCODE -ne 0) { Fail 'alembic upgrade head failed.' }
} finally { Pop-Location }
Ok 'schema is up to date'

# -----------------------------------------------------------------------------
# 7. Frontend
# -----------------------------------------------------------------------------
Step 'Installing frontend dependencies'
Push-Location $frontendDir
try {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { Fail 'npm ci failed.' }
} finally { Pop-Location }
Ok 'frontend deps installed'

# -----------------------------------------------------------------------------
# 8. Optional local model profile
# -----------------------------------------------------------------------------
if ($edition -eq 'community' -and $communityModelProfile -ne 'remote') {
    Step 'Configuring and downloading Community local models'
    Push-Location $projectRoot
    try {
        & python scripts/init_models.py
        if ($LASTEXITCODE -ne 0) { Fail 'Local model initialization failed.' }
    } finally { Pop-Location }
    Ok 'local model profile configured'
}

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
Write-Host '       or configure the operator-provided default LLM.'
Write-Host '    2. To change local models later: python scripts/init_models.py'
Write-Host '    3. .\scripts\start.ps1'
Write-Host '       — every-day startup (uvicorn + celery + vite, single window).'
Write-Host '       (Note: use the .\ prefix, NOT `pwsh scripts/start.ps1` — the'
Write-Host '        latter spawns a child shell that drops your conda activation.)'
Write-Host ''

<#
.SYNOPSIS
    Interview Copilot — clean shutdown (Windows / PowerShell 7+).
.DESCRIPTION
    Stops everything start.ps1 brought up:
      - Any leftover uvicorn / celery / vite processes (best-effort)
      - All docker compose services

    Usually you stop start.ps1 with Ctrl+C and that's enough; this
    script is the "make sure nothing is left behind" hammer.

.PARAMETER Volumes
    Also delete docker volumes (postgres data, milvus data, minio bucket).
    DESTRUCTIVE — wipes the database. Use only when intentionally resetting.

.EXAMPLE
    pwsh scripts/stop.ps1
    pwsh scripts/stop.ps1 -Volumes   # nuke DB / vector store / object store
#>
[CmdletBinding()]
param(
    [switch]$Volumes
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok([string]$msg)   { Write-Host "    $msg" -ForegroundColor Green }

# -----------------------------------------------------------------------------
# 1. Kill any straggler dev processes.
#    Match by command line so we only hit OUR processes, not unrelated ones.
# -----------------------------------------------------------------------------
Step 'Stopping leftover dev processes (uvicorn / celery / vite)'
$patterns = @(
    'uvicorn app.main:app',
    'celery_app.celery_app worker',
    'node.*vite'
)
$killed = 0
foreach ($pat in $patterns) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match $pat) } |
        ForEach-Object {
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
                Ok "killed PID $($_.ProcessId): $pat"
                $killed++
            } catch { }
        }
}
if ($killed -eq 0) { Ok 'no leftover processes found' }

# -----------------------------------------------------------------------------
# 2. Bring down docker compose
# -----------------------------------------------------------------------------
Step 'docker compose down'
Push-Location $projectRoot
try {
    if ($Volumes) {
        Write-Host '    --Volumes set: also removing data volumes (DESTRUCTIVE)' -ForegroundColor Yellow
        docker compose down -v | Out-Host
    } else {
        docker compose down | Out-Host
    }
} finally { Pop-Location }

Write-Host ''
Write-Host '==================================================================' -ForegroundColor Green
if ($Volumes) {
    Write-Host '  All services stopped AND data volumes wiped.' -ForegroundColor Green
    Write-Host '  Next start.ps1 will rebuild an empty DB; remember to re-run' -ForegroundColor Green
    Write-Host '  alembic upgrade head (start.ps1 does this automatically).' -ForegroundColor Green
} else {
    Write-Host '  All services stopped. Data volumes preserved.' -ForegroundColor Green
}
Write-Host '==================================================================' -ForegroundColor Green

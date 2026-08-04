<#
.SYNOPSIS
    Interview Copilot — clean shutdown (Windows / PowerShell 7+).
.DESCRIPTION
    Stops this repository's Docker Compose services. Host development
    processes belong to the terminal running start.ps1 and are stopped
    there with Ctrl+C; this script never scans or kills unrelated processes.

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

# -----------------------------------------------------------------------------
# Bring down docker compose
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

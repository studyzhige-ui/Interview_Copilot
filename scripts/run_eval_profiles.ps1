param(
    [string]$PythonExe = "python",
    [int]$EvalLimit = 200,
    [int]$EvalConcurrency = 4,
    [int]$RagasChunkSize = 10,
    [int]$RagasMaxWorkers = 32,
    [double]$EvalRelevanceThreshold = 0.15,
    [int]$EvalTimeoutSeconds = 60,
    [switch]$Resume
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$EvalScript = Join-Path $RepoRoot "evaluation\run_rag_eval.py"

if (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue) -and -not (Test-Path $PythonExe)) {
    throw "Python interpreter not found: $PythonExe"
}

if (-not (Test-Path $EvalScript)) {
    throw "Evaluation script not found: $EvalScript"
}

Set-Location $RepoRoot

function Invoke-EvalProfile {
    param(
        [Parameter(Mandatory = $true)][string]$ProfileName,
        [Parameter(Mandatory = $true)][double]$MinScore,
        [Parameter(Mandatory = $true)][string]$ForceRebuild
    )

    Write-Host ""
    Write-Host "=== Running profile: $ProfileName (EVAL_MIN_SCORE=$MinScore) ===" -ForegroundColor Cyan

    $env:EVAL_LIMIT = [string]$EvalLimit
    $env:EVAL_CONCURRENCY = [string]$EvalConcurrency
    $env:RAGAS_CHUNK_SIZE = [string]$RagasChunkSize
    $env:RAGAS_MAX_WORKERS = [string]$RagasMaxWorkers
    $env:EVAL_RELEVANCE_THRESHOLD = [string]$EvalRelevanceThreshold
    $env:EVAL_TIMEOUT_SECONDS = [string]$EvalTimeoutSeconds
    $env:EVAL_MIN_SCORE = [string]$MinScore
    $env:EVAL_FORCE_REBUILD = $ForceRebuild

    & $PythonExe $EvalScript
    if ($LASTEXITCODE -ne 0) {
        throw "Evaluation failed for profile '$ProfileName' with exit code $LASTEXITCODE"
    }
}

$firstRunRebuild = if ($Resume) { "0" } else { "1" }
$secondRunRebuild = "0"

Invoke-EvalProfile -ProfileName "pure_recall" -MinScore 0.0 -ForceRebuild $firstRunRebuild
Invoke-EvalProfile -ProfileName "production_like" -MinScore 0.5 -ForceRebuild $secondRunRebuild

Write-Host ""
Write-Host "Finished. Results saved under data/evaluation:" -ForegroundColor Green
Write-Host "  eval_results_min_score_0_0.json"
Write-Host "  eval_results_min_score_0_5.json"
Write-Host "  eval_details_min_score_0_0.json"
Write-Host "  eval_details_min_score_0_5.json"

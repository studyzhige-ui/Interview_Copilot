# Start Codex from PowerShell 7 with UTF-8 settings.
# Run from PowerShell 7:
#   .\scripts\start_codex_pwsh.ps1

chcp 65001 > $null

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

Set-Location -LiteralPath (Resolve-Path "$PSScriptRoot\..")
codex

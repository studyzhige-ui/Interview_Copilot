$ErrorActionPreference = 'Stop'
$resumePython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (-not (Test-Path -LiteralPath $resumePython)) { throw '请先配置 Python 和 README 中列出的依赖。' }
& $resumePython -X utf8 (Join-Path $PSScriptRoot 'server.py')

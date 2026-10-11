# Fresh packaged-process smoke: does not claim installed protocol registration.
$ErrorActionPreference = 'Stop'
if (-not $IsWindows -or $env:IC_DESKTOP_ACCEPTANCE -ne '1') { throw 'Explicit Windows acceptance environment required' }
$executable = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../release/win-unpacked/Interview Copilot.exe')).Path
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('copilot-package-contract-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$first = $null
$second = $null
try {
    $arguments = @('--user-data-dir="' + $testRoot + '"')
    $first = Start-Process -FilePath $executable -ArgumentList $arguments -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 8
    if ($first.HasExited) { throw 'Packaged application exited during startup' }
    $second = Start-Process -FilePath $executable -ArgumentList $arguments -WindowStyle Hidden -PassThru
    if (-not $second.WaitForExit(15000)) { throw 'Second instance did not yield to the first' }
    $first.Refresh()
    if ($first.HasExited) { throw 'Primary instance was lost during dispatch' }
    @{ passed = $true; checks = @('packaged-startup', 'single-instance'); installedProtocolVerified = $false } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot '../release/windows-dispatch-report.json') -Encoding utf8NoBOM
} finally {
    foreach ($process in @($second, $first)) {
        if ($null -ne $process -and -not $process.HasExited) { $process.Kill($true); $process.WaitForExit() }
    }
    $resolved = [IO.Path]::GetFullPath($testRoot)
    $expected = Join-Path ([IO.Path]::GetTempPath()) 'copilot-package-contract-'
    if (-not $resolved.StartsWith($expected, [StringComparison]::OrdinalIgnoreCase)) { throw 'Cleanup path mismatch' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

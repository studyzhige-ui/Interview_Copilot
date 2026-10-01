# Disposable hosted Windows CI only. Synthetic intents prove OS delivery, not
# live Supabase/PKCE, Docker Desktop, microphone, or a signed release.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Require($Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
Require ($env:CI -eq 'true' -and $env:GITHUB_ACTIONS -eq 'true' -and $env:RUNNER_OS -eq 'Windows' -and $env:IC_DESKTOP_ACCEPTANCE -eq '1') 'This test requires an explicitly disposable hosted Windows CI runner'
$release = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../release'))
$manifest = Get-Content (Join-Path $release 'win-unpacked/resources/runtime/desktop-runtime.json') -Raw | ConvertFrom-Json
Require ($manifest.auth.url -eq 'https://fixture.supabase.co' -and $manifest.auth.publishableKey -eq 'sb_publishable_synthetic_fixture') 'Only the synthetic acceptance package may be installed'
$schemeKey = 'HKCU:\Software\Classes\interview-copilot'
$profile = Join-Path $env:APPDATA 'Interview Copilot'
# Never overwrite an existing profile/association, even on a misconfigured runner.
Require (-not (Test-Path $schemeKey)) 'A protocol association already exists; refusing to replace it'
Require (-not (Test-Path $profile)) 'An application profile already exists; refusing to use it'
$fixture = Join-Path $env:RUNNER_TEMP ('copilot-os-acceptance-' + [guid]::NewGuid().ToString())
$installation = Join-Path $fixture 'Installed App With Spaces'
$executable = Join-Path $installation 'Interview Copilot.exe'
$pending = Join-Path $profile 'local-workspace/pending-auth.json'
$reportPath = Join-Path $release 'windows-dispatch-report.json'
$report = [ordered]@{ source_commit = $env:IC_SOURCE_COMMIT; validation_only = $true; passed = $false; checks = @(); cleanup_verified = $false; boundary = 'Installed Windows protocol and single-instance delivery using synthetic pending metadata only; no live Auth/PKCE, Docker Desktop, email, or microphone' }
$installed = $false
function AppProcesses {
  @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $executable })
}
function MainProcesses {
  @(AppProcesses | Where-Object { $_.CommandLine -notmatch '(?i)--type=' })
}
function StopFixture {
  # Re-read each executable path immediately before stopping; no global Electron
  # name lookup, process-tree kill, or unrelated process shutdown.
  foreach ($item in (AppProcesses)) {
    $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($item.ProcessId)"
    if ($current -and $current.ExecutablePath -eq $executable) { Stop-Process -Id $current.ProcessId -Force -ErrorAction SilentlyContinue }
  }
}
function AwaitCondition([scriptblock]$Condition, [string]$Message) {
  $deadline = [DateTime]::UtcNow.AddSeconds(30)
  do { if (& $Condition) { return }; Start-Sleep -Milliseconds 250 } while ([DateTime]::UtcNow -lt $deadline)
  throw $Message
}
function NewIntent([int]$Lifetime = 300000) {
  [ordered]@{ id = [guid]::NewGuid().ToString(); purpose = 'recovery'; expiresAt = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() + $Lifetime }
}
function SaveIntent($Intent) {
  [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($pending)) | Out-Null
  [IO.File]::WriteAllText($pending, ($Intent | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
}
function CurrentIntentIs($Intent) {
  if (-not (Test-Path $pending)) { return $false }
  $value = Get-Content $pending -Raw | ConvertFrom-Json
  return $value.id -eq $Intent.id
}
function Dispatch($Intent) {
  # ShellExecute invokes the installed OS association. These values are synthetic
  # and never logged. A preserved fragment is necessary for the file to be consumed.
  $url = 'interview-copilot://auth/recovery?code=synthetic_acceptance_code_123456#state=' + $Intent.id
  Start-Process -FilePath $url -ErrorAction Stop | Out-Null
}
try {
  New-Item -ItemType Directory -Path $fixture | Out-Null
  $installer = Join-Path $release 'Interview-Copilot-acceptance-fixture.exe'
  # NSIS requires /D= to be the last argument and consumes the remaining spaces.
  $installed = $true
  $install = Start-Process -FilePath $installer -ArgumentList @('/S', "/D=$installation") -Wait -PassThru
  Require ($install.ExitCode -eq 0 -and (Test-Path $executable)) 'Fixture installation did not complete'
  # This pinned NSIS target does not handle build.protocols. The actual packaged
  # app registers its callback on first launch, before any account operation.
  Start-Process -FilePath $executable | Out-Null
  AwaitCondition { Test-Path (Join-Path $schemeKey 'shell/open/command') } 'First launch did not register the installed fixture'
  $association = (Get-Item (Join-Path $schemeKey 'shell/open/command')).GetValue('')
  Require ($association -match ('^"' + [regex]::Escape($executable) + '"\s+"%1"$')) 'Protocol association does not target the installed fixture'
  $report.checks += 'NSIS installation and first-launch exact per-user protocol executable registration'
  StopFixture
  AwaitCondition { @(AppProcesses).Count -eq 0 } 'Fixture did not stop before cold launch'
  $a = NewIntent; SaveIntent $a; Dispatch $a
  AwaitCondition { @(MainProcesses).Count -eq 1 -and -not (Test-Path $pending) } 'Cold OS dispatch did not consume the matching synthetic intent'
  $mainId = @(MainProcesses)[0].ProcessId
  $report.checks += 'Closed-app OS ShellExecute delivers query code and fragment state'
  $b = NewIntent; SaveIntent $b; Dispatch $a
  Start-Sleep -Seconds 2
  Require (CurrentIntentIs $b) 'A stale callback consumed the replacement intent'
  Dispatch $b
  AwaitCondition { -not (Test-Path $pending) } 'The replacement callback was not delivered'
  AwaitCondition { @(MainProcesses).Count -eq 1 -and @(MainProcesses)[0].ProcessId -eq $mainId } 'Warm callbacks did not remain in the original main instance'
  $report.checks += 'Same-purpose stale callback preserves replacement and valid callback reaches original instance'
  $c = NewIntent; SaveIntent $c; Dispatch $b
  Start-Sleep -Seconds 2
  Require (CurrentIntentIs $c) 'A duplicate callback consumed a newer intent'
  AwaitCondition { @(MainProcesses).Count -eq 1 -and @(MainProcesses)[0].ProcessId -eq $mainId } 'Duplicate callback launched another main instance'
  $expired = NewIntent -Lifetime -1000; SaveIntent $expired; Dispatch $expired
  Start-Sleep -Seconds 2
  Require (CurrentIntentIs $expired) 'Expired pending metadata was accepted'
  $report.checks += 'Duplicate and expired callbacks rejected without consuming current pending metadata'
  StopFixture
  AwaitCondition { @(AppProcesses).Count -eq 0 } 'Fixture did not stop before restart'
  $d = NewIntent; SaveIntent $d; Dispatch $d
  AwaitCondition { @(MainProcesses).Count -eq 1 -and -not (Test-Path $pending) } 'Installed callback did not survive a closed-app restart'
  $report.checks += 'Installed registration survives a fresh closed-app restart'
  $report.passed = $true
} catch {
  # Never echo Start-Process exception arguments or URI/code values.
  $report.failure = 'Windows installed dispatch acceptance failed; see the completed checks in this report'
  throw 'Windows installed dispatch acceptance failed'
} finally {
  try {
    StopFixture
    AwaitCondition { @(AppProcesses).Count -eq 0 } 'Fixture processes remained during cleanup'
    if ($installed) {
      $uninstaller = Join-Path $installation 'Uninstall Interview Copilot.exe'
      Require (Test-Path $uninstaller) 'Fixture uninstaller is missing'
      $uninstall = Start-Process -FilePath $uninstaller -ArgumentList '/S' -Wait -PassThru
      Require ($uninstall.ExitCode -eq 0) 'Fixture uninstall failed'
      AwaitCondition { -not (Test-Path $schemeKey) } 'Fixture protocol association remained after uninstall'
      AwaitCondition { -not (Test-Path $executable) } 'Fixture executable remained after uninstall'
    }
    if (Test-Path $profile) { Remove-Item -LiteralPath $profile -Recurse -Force }
    if (Test-Path $fixture) { Remove-Item -LiteralPath $fixture -Recurse -Force }
    $report.cleanup_verified = $true
  } catch {
    $report.passed = $false
    $report.cleanup_failure = 'Fixture cleanup did not complete; this disposable runner must not be reused'
    Write-Error 'Windows fixture cleanup failed' -ErrorAction Continue
  }
  $report | ConvertTo-Json -Depth 6 | Set-Content -Path $reportPath -Encoding utf8
}
Require ($report.passed -and $report.cleanup_verified) 'Installed dispatch acceptance or cleanup failed'
$report | ConvertTo-Json -Depth 6

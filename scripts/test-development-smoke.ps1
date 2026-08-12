[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$taskTempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$fixtureRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $taskTempBase "museecho-development-smoke-test-$PID-$([System.IO.Path]::GetRandomFileName())")
)
$fakeRepository = Join-Path $fixtureRoot 'repository'
$fakeScripts = Join-Path $fakeRepository 'scripts'
$fakeBin = Join-Path $fixtureRoot 'bin'
$dockerLog = Join-Path $fixtureRoot 'docker.log'
$runnerPath = Join-Path $fakeScripts 'development-smoke.ps1'
$isWindowsPlatform = $env:OS -eq 'Windows_NT'
$fakeDockerPath = Join-Path $fakeBin $(if ($isWindowsPlatform) { 'docker.cmd' } else { 'docker' })
$fakeCurlPath = Join-Path $fakeBin $(if ($isWindowsPlatform) { 'curl.cmd' } else { 'curl' })
$defaultCurlBootstrap = Join-Path $fixtureRoot 'run-default-curl.ps1'
$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell.exe' }
$savedPath = $env:PATH
$savedLog = $env:MUSEECHO_FAKE_DOCKER_LOG
$savedMode = $env:MUSEECHO_FAKE_DOCKER_MODE
$savedCurlMode = $env:MUSEECHO_FAKE_CURL_MODE
$cleanupExitCodePattern = '(?<!\d)code[ \t]+29(?!\d)'
$ansiSgr = [string][char]27

function Invoke-SmokeProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Mode,
        [switch]$SuccessfulCurl,
        [switch]$FailingCurl,
        [switch]$DefaultCurl,
        [switch]$FormatCleanupFailure,
        [switch]$AddAnsiCleanupFormatting,
        [int]$FormattedCleanupExitCode = 29
    )
    [System.IO.File]::WriteAllText($dockerLog, '', [Text.UTF8Encoding]::new($false))
    $env:MUSEECHO_FAKE_DOCKER_MODE = $Mode
    if ($SuccessfulCurl -and $FailingCurl) {
        throw 'a curl probe cannot request both success and failure'
    }
    $env:MUSEECHO_FAKE_CURL_MODE = if ($FailingCurl) { 'failure' } else { 'success' }
    $savedErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($DefaultCurl) {
            $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $defaultCurlBootstrap)
        } else {
            $arguments = @(
                '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $runnerPath,
                '-DockerCommand', $fakeDockerPath
            )
            if ($SuccessfulCurl -or $FailingCurl) { $arguments += @('-CurlCommand', $fakeCurlPath) }
        }
        $output = & $shell @arguments 2>&1 | Out-String
        if ($FormatCleanupFailure) {
            $output = $output.Replace(
                'docker compose down failed with exit code 29',
                'docker compose down failed with exit'
            )
            $output = [regex]::Replace(
                $output,
                'code 29(?!\d)',
                "`n      | code $FormattedCleanupExitCode"
            )
        }
        if ($AddAnsiCleanupFormatting) {
            $output = $output.Replace(
                'docker compose down failed with exit',
                "${ansiSgr}[31;1mdocker${ansiSgr}[0m ${ansiSgr}[31;1mcompose down failed with exit${ansiSgr}[0m"
            )
            $output = [regex]::Replace(
                $output,
                'code 29(?!\d)',
                "${ansiSgr}[31;1mcode 29${ansiSgr}[0m"
            )
        }
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorPreference
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $output
        SemanticOutput = [regex]::Replace($output, "$([char]27)\[[0-9;]*m", '')
        DockerLog = [System.IO.File]::ReadAllText($dockerLog)
    }
}

try {
    New-Item -ItemType Directory -Path $fakeScripts, $fakeBin | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'development-smoke.ps1') `
        -Destination $runnerPath
    $fakeDockerContents = if ($isWindowsPlatform) {
        @'
@echo off
echo %*>>"%MUSEECHO_FAKE_DOCKER_LOG%"
for /f %%C in ('find /c /v "" ^< "%MUSEECHO_FAKE_DOCKER_LOG%"') do set CALLCOUNT=%%C
if "%MUSEECHO_FAKE_DOCKER_MODE%"=="up-fail" if "%CALLCOUNT%"=="1" exit /b 23
if "%MUSEECHO_FAKE_DOCKER_MODE%"=="down-fail" if not "%CALLCOUNT%"=="1" exit /b 29
exit /b 0
'@
    } else {
        @'
#!/bin/sh
printf '%s\n' "$*" >> "$MUSEECHO_FAKE_DOCKER_LOG"
call_count=$(wc -l < "$MUSEECHO_FAKE_DOCKER_LOG")
if [ "$MUSEECHO_FAKE_DOCKER_MODE" = up-fail ] && [ "$call_count" = 1 ]; then exit 23; fi
if [ "$MUSEECHO_FAKE_DOCKER_MODE" = down-fail ] && [ "$call_count" != 1 ]; then exit 29; fi
exit 0
'@
    }
    if (-not $isWindowsPlatform) {
        $fakeDockerContents = $fakeDockerContents.Replace("`r`n", "`n")
    }
    [System.IO.File]::WriteAllText($fakeDockerPath, $fakeDockerContents, [Text.UTF8Encoding]::new($false))
    if (-not $isWindowsPlatform) {
        & chmod 700 $fakeDockerPath
        if ($LASTEXITCODE -ne 0) { throw 'could not make fake Docker executable' }
    }
    $fakeCurlContents = if ($isWindowsPlatform) {
        "@echo off`r`nif `"%MUSEECHO_FAKE_CURL_MODE%`"==`"failure`" exit /b 17`r`necho %*| findstr /c:`"/api/health`" >nul && echo {`"status`":`"ready`"} && exit /b 0`r`necho ^<div id=`"root`"^> && exit /b 0`r`n"
    } else {
        @'
#!/bin/sh
if [ "$MUSEECHO_FAKE_CURL_MODE" = "failure" ]; then
  printf '%s\n' 'fake curl failed' >&2
  exit 17
fi
case "$*" in
  */api/health*) echo '{"status":"ready"}' ;;
  *) echo '<div id="root">' ;;
esac
exit 0
'@
    }
    if (-not $isWindowsPlatform) {
        $fakeCurlContents = $fakeCurlContents.Replace("`r`n", "`n")
    }
    [System.IO.File]::WriteAllText($fakeCurlPath, $fakeCurlContents, [Text.UTF8Encoding]::new($false))
    if (-not $isWindowsPlatform) {
        & chmod 700 $fakeCurlPath
        if ($LASTEXITCODE -ne 0) { throw 'could not make fake curl executable' }
    }
    $env:MUSEECHO_FAKE_DOCKER_LOG = $dockerLog
    $env:PATH = "$fakeBin$([IO.Path]::PathSeparator)$savedPath"
    $escapedRunnerPath = $runnerPath.Replace("'", "''")
    $escapedDockerPath = $fakeDockerPath.Replace("'", "''")
    [System.IO.File]::WriteAllText(
        $defaultCurlBootstrap,
        @"
function Invoke-FakeDefaultCurl {
    throw 'Linux curl command was not selected'
}
Set-Alias -Name curl.exe -Value Invoke-FakeDefaultCurl -Scope Global
if (Test-Path Alias:curl) { Remove-Item Alias:curl -Force }
`$env:OS = 'Linux'
& '$escapedRunnerPath' -DockerCommand '$escapedDockerPath'
exit `$LASTEXITCODE
"@,
        [Text.UTF8Encoding]::new($false)
    )

    $partialUp = Invoke-SmokeProbe -Mode 'up-fail'
    if ($partialUp.ExitCode -eq 0 -or $partialUp.Output -notmatch 'failed to start') {
        throw "development smoke did not preserve the partial-up failure`n$($partialUp.Output)"
    }
    if ($partialUp.DockerLog -notmatch '(?m)^compose .* down ') {
        throw "development smoke did not clean up after partial compose up`n$($partialUp.DockerLog)"
    }
    if ($partialUp.Output -match 'cleanup failed') {
        throw "primary-only failure was incorrectly reported as cleanup failure`n$($partialUp.Output)"
    }

    $defaultCurl = Invoke-SmokeProbe -Mode 'success' -DefaultCurl
    if ($defaultCurl.ExitCode -ne 0 -or $defaultCurl.Output -notmatch 'development smoke passed') {
        throw "development smoke default curl command was not executable`n$($defaultCurl.Output)"
    }

    $cleanupOnly = Invoke-SmokeProbe -Mode 'down-fail' -SuccessfulCurl -FormatCleanupFailure -AddAnsiCleanupFormatting
    if ($cleanupOnly.ExitCode -eq 0) {
        throw 'development smoke swallowed its cleanup-only failure'
    }
    if (
        $cleanupOnly.SemanticOutput -notmatch 'development smoke cleanup failed' -or
        $cleanupOnly.SemanticOutput -notmatch 'docker compose down failed with exit' -or
        $cleanupOnly.SemanticOutput -notmatch $cleanupExitCodePattern -or
        $cleanupOnly.SemanticOutput -match 'HTTPS API health probe failed'
    ) {
        throw "development smoke did not isolate cleanup-only failure`n$($cleanupOnly.Output)"
    }

    $wrongCleanupExitCode = Invoke-SmokeProbe -Mode 'down-fail' -SuccessfulCurl -FormatCleanupFailure -AddAnsiCleanupFormatting -FormattedCleanupExitCode 290
    if ($wrongCleanupExitCode.SemanticOutput -match $cleanupExitCodePattern) {
        throw "development smoke accepted cleanup exit code other than 29`n$($wrongCleanupExitCode.Output)"
    }

    $combinedFailure = Invoke-SmokeProbe -Mode 'down-fail' -FailingCurl
    if ($combinedFailure.ExitCode -eq 0) {
        throw 'development smoke swallowed its cleanup failure'
    }
    if (
        $combinedFailure.SemanticOutput -notmatch 'development HTTPS API health probe failed' -or
        $combinedFailure.SemanticOutput -notmatch 'docker compose down failed with exit' -or
        $combinedFailure.SemanticOutput -notmatch $cleanupExitCodePattern -or
        $combinedFailure.SemanticOutput -match 'Documented HTTPS same-origin development smoke passed'
    ) {
        throw "development smoke did not report both primary and cleanup failures`n$($combinedFailure.Output)"
    }

    Write-Host 'Development smoke synthetic lifecycle tests passed.'
    $global:LASTEXITCODE = 0
}
finally {
    $env:PATH = $savedPath
    $env:MUSEECHO_FAKE_DOCKER_LOG = $savedLog
    $env:MUSEECHO_FAKE_DOCKER_MODE = $savedMode
    $env:MUSEECHO_FAKE_CURL_MODE = $savedCurlMode
    if (Test-Path -LiteralPath $fixtureRoot) {
        [System.IO.Directory]::Delete($fixtureRoot, $true)
    }
}

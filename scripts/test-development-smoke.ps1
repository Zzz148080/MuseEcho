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
$childProbePath = Join-Path $fixtureRoot 'run-smoke-probe.ps1'
$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell.exe' }
$savedPath = $env:PATH
$savedLog = $env:MUSEECHO_FAKE_DOCKER_LOG
$savedMode = $env:MUSEECHO_FAKE_DOCKER_MODE
$savedCurlMode = $env:MUSEECHO_FAKE_CURL_MODE
$cleanupExitCodePattern = '(?<!\d)code 29(?!\d)'
$probeMarkerPrefix = 'MUSEECHO_SMOKE_PROBE:'
$probeSuccessMarker = "${probeMarkerPrefix}SUCCESS"
$probeExceptionMarkerPrefix = "${probeMarkerPrefix}EXCEPTION_MESSAGE_BASE64:"
$strictUtf8 = [Text.UTF8Encoding]::new($false, $true)

function ConvertFrom-SmokeProbeOutcome {
    param(
        [Parameter(Mandatory = $true)][string]$Output,
        [Parameter(Mandatory = $true)][int]$ExitCode
    )
    $markerLines = @([regex]::Matches($Output, "(?m)^$([regex]::Escape($probeMarkerPrefix)).*$"))
    if ($markerLines.Count -ne 1) {
        throw "development smoke probe emitted an invalid marker count`n$Output"
    }
    $marker = $markerLines[0].Value.TrimEnd("`r")
    $exceptionMessage = $null
    if ($marker -eq $probeSuccessMarker) {
        if ($ExitCode -ne 0) {
            throw "development smoke probe reported success with a nonzero exit code`n$Output"
        }
    } elseif ($marker.StartsWith($probeExceptionMarkerPrefix, [StringComparison]::Ordinal)) {
        if ($ExitCode -eq 0) {
            throw "development smoke probe reported failure with a zero exit code`n$Output"
        }
        $encodedMessage = $marker.Substring($probeExceptionMarkerPrefix.Length)
        if ([string]::IsNullOrEmpty($encodedMessage)) {
            throw "development smoke probe emitted an empty exception marker`n$Output"
        }
        try {
            $decodedBytes = [Convert]::FromBase64String($encodedMessage)
            if ([Convert]::ToBase64String($decodedBytes) -cne $encodedMessage) {
                throw 'non-canonical Base64'
            }
            $exceptionMessage = $strictUtf8.GetString($decodedBytes)
        } catch {
            throw "development smoke probe emitted a malformed exception marker`n$Output"
        }
        if ([string]::IsNullOrEmpty($exceptionMessage)) {
            throw "development smoke probe emitted an empty exception message`n$Output"
        }
    } else {
        throw "development smoke probe emitted an unknown marker`n$Output"
    }
    return [pscustomobject]@{
        ExceptionMessage = $exceptionMessage
    }
}

function Invoke-SmokeProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Mode,
        [switch]$SuccessfulCurl,
        [switch]$FailingCurl,
        [switch]$DefaultCurl
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
        $arguments = @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $childProbePath,
            '-RunnerPath', $runnerPath, '-DockerCommand', $fakeDockerPath
        )
        if ($DefaultCurl) { $arguments += '-DefaultCurl' }
        else { $arguments += @('-CurlCommand', $fakeCurlPath) }
        $output = & $shell @arguments 2>&1 | Out-String
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorPreference
    }
    $outcome = ConvertFrom-SmokeProbeOutcome -Output $output -ExitCode $exitCode
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $output
        ExceptionMessage = $outcome.ExceptionMessage
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
    [System.IO.File]::WriteAllText(
        $childProbePath,
        @'
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RunnerPath,
    [Parameter(Mandatory = $true)][string]$DockerCommand,
    [string]$CurlCommand,
    [switch]$DefaultCurl
)

$ErrorActionPreference = 'Stop'
$markerPrefix = 'MUSEECHO_SMOKE_PROBE:'
try {
    if ($DefaultCurl) {
        $env:OS = 'Linux'
        if (Test-Path Alias:curl) { Remove-Item Alias:curl -Force }
        & $RunnerPath -DockerCommand $DockerCommand
    } else {
        & $RunnerPath -DockerCommand $DockerCommand -CurlCommand $CurlCommand
    }
    if ($LASTEXITCODE -ne 0) {
        throw "development smoke exited with code $LASTEXITCODE without a terminating exception"
    }
    [Console]::Out.WriteLine("${markerPrefix}SUCCESS")
    exit 0
} catch {
    $encodedMessage = [Convert]::ToBase64String([Text.UTF8Encoding]::new($false).GetBytes($_.Exception.Message))
    [Console]::Out.WriteLine("${markerPrefix}EXCEPTION_MESSAGE_BASE64:$encodedMessage")
    exit 1
}
'@,
        [Text.UTF8Encoding]::new($false)
    )

    foreach ($invalidProbe in @(
            [pscustomobject]@{ Name = 'missing'; Output = 'no marker'; ExitCode = 1 },
            [pscustomobject]@{ Name = 'duplicate'; Output = "$probeSuccessMarker`n$probeSuccessMarker"; ExitCode = 0 },
            [pscustomobject]@{ Name = 'malformed'; Output = "${probeExceptionMarkerPrefix}%%%"; ExitCode = 1 },
            [pscustomobject]@{ Name = 'invalid-utf8'; Output = "${probeExceptionMarkerPrefix}/w=="; ExitCode = 1 },
            [pscustomobject]@{ Name = 'empty-failure-payload'; Output = $probeExceptionMarkerPrefix; ExitCode = 1 },
            [pscustomobject]@{ Name = 'success-with-payload'; Output = "${probeSuccessMarker}:unexpected"; ExitCode = 0 },
            [pscustomobject]@{ Name = 'wrong-success-exit'; Output = $probeSuccessMarker; ExitCode = 1 },
            [pscustomobject]@{ Name = 'wrong-failure-exit'; Output = "${probeExceptionMarkerPrefix}ZmFpbGVk"; ExitCode = 0 }
        )) {
        try {
            ConvertFrom-SmokeProbeOutcome -Output $invalidProbe.Output -ExitCode $invalidProbe.ExitCode | Out-Null
            throw "development smoke probe accepted $($invalidProbe.Name) marker state"
        } catch {
            if ($_.Exception.Message -eq "development smoke probe accepted $($invalidProbe.Name) marker state") {
                throw
            }
        }
    }

    $partialUp = Invoke-SmokeProbe -Mode 'up-fail'
    if ($partialUp.ExitCode -eq 0 -or $partialUp.ExceptionMessage -notmatch 'failed to start') {
        throw "development smoke did not preserve the partial-up failure`n$($partialUp.Output)"
    }
    if ($partialUp.DockerLog -notmatch '(?m)^compose .* down ') {
        throw "development smoke did not clean up after partial compose up`n$($partialUp.DockerLog)"
    }
    if ($partialUp.ExceptionMessage -match 'cleanup failed') {
        throw "primary-only failure was incorrectly reported as cleanup failure`n$($partialUp.Output)"
    }

    $defaultCurl = Invoke-SmokeProbe -Mode 'success' -DefaultCurl
    if ($defaultCurl.ExitCode -ne 0 -or $defaultCurl.Output -notmatch 'development smoke passed') {
        throw "development smoke default curl command was not executable`n$($defaultCurl.Output)"
    }

    $cleanupOnly = Invoke-SmokeProbe -Mode 'down-fail' -SuccessfulCurl
    if ($cleanupOnly.ExitCode -eq 0) {
        throw 'development smoke swallowed its cleanup-only failure'
    }
    if (
        $cleanupOnly.ExceptionMessage -notmatch 'development smoke cleanup failed' -or
        $cleanupOnly.ExceptionMessage -notmatch 'docker compose down failed with exit' -or
        $cleanupOnly.ExceptionMessage -notmatch $cleanupExitCodePattern -or
        $cleanupOnly.ExceptionMessage -match 'HTTPS API health probe failed'
    ) {
        throw "development smoke did not isolate cleanup-only failure`n$($cleanupOnly.Output)"
    }

    $wrongCleanupExitMessage = $cleanupOnly.ExceptionMessage.Replace('code 29', 'code 290')
    if ($wrongCleanupExitMessage -match $cleanupExitCodePattern) {
        throw "development smoke accepted cleanup exit code other than 29`n$($cleanupOnly.Output)"
    }

    $combinedFailure = Invoke-SmokeProbe -Mode 'down-fail' -FailingCurl
    if ($combinedFailure.ExitCode -eq 0) {
        throw 'development smoke swallowed its cleanup failure'
    }
    if (
        $combinedFailure.ExceptionMessage -notmatch 'development HTTPS API health probe failed' -or
        $combinedFailure.ExceptionMessage -notmatch 'docker compose down failed with exit' -or
        $combinedFailure.ExceptionMessage -notmatch $cleanupExitCodePattern -or
        $combinedFailure.ExceptionMessage -match 'Documented HTTPS same-origin development smoke passed'
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

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
$fakeDockerPath = Join-Path $fakeBin 'docker.cmd'
$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell.exe' }
$savedPath = $env:PATH
$savedLog = $env:MUSEECHO_FAKE_DOCKER_LOG
$savedMode = $env:MUSEECHO_FAKE_DOCKER_MODE

function Invoke-SmokeProbe {
    param([Parameter(Mandatory = $true)][string]$Mode)
    [System.IO.File]::WriteAllText($dockerLog, '', [Text.UTF8Encoding]::new($false))
    $env:MUSEECHO_FAKE_DOCKER_MODE = $Mode
    $savedErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $shell -NoProfile -ExecutionPolicy Bypass -File $runnerPath `
            -DockerCommand $fakeDockerPath 2>&1 | Out-String
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorPreference
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $output
        DockerLog = [System.IO.File]::ReadAllText($dockerLog)
    }
}

try {
    New-Item -ItemType Directory -Path $fakeScripts, $fakeBin | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'development-smoke.ps1') `
        -Destination $runnerPath
    [System.IO.File]::WriteAllText(
        $fakeDockerPath,
        @'
@echo off
echo %*>>"%MUSEECHO_FAKE_DOCKER_LOG%"
for /f %%C in ('find /c /v "" ^< "%MUSEECHO_FAKE_DOCKER_LOG%"') do set CALLCOUNT=%%C
if "%MUSEECHO_FAKE_DOCKER_MODE%"=="up-fail" if "%CALLCOUNT%"=="1" exit /b 23
if "%MUSEECHO_FAKE_DOCKER_MODE%"=="down-fail" if not "%CALLCOUNT%"=="1" exit /b 29
exit /b 0
'@,
        [Text.UTF8Encoding]::new($false)
    )
    $env:MUSEECHO_FAKE_DOCKER_LOG = $dockerLog
    $env:PATH = "$fakeBin$([IO.Path]::PathSeparator)$savedPath"

    $partialUp = Invoke-SmokeProbe -Mode 'up-fail'
    if ($partialUp.ExitCode -eq 0 -or $partialUp.Output -notmatch 'failed to start') {
        throw "development smoke did not preserve the partial-up failure`n$($partialUp.Output)"
    }
    if ($partialUp.DockerLog -notmatch '(?m)^compose .* down ') {
        throw "development smoke did not clean up after partial compose up`n$($partialUp.DockerLog)"
    }

    $downFailure = Invoke-SmokeProbe -Mode 'down-fail'
    if ($downFailure.ExitCode -eq 0) {
        throw 'development smoke swallowed its cleanup failure'
    }
    if (
        $downFailure.Output -notmatch 'development HTTPS API health probe failed' -or
        $downFailure.Output -notmatch 'docker compose down failed with exit code 29'
    ) {
        throw "development smoke did not report both primary and cleanup failures`n$($downFailure.Output)"
    }

    Write-Host 'Development smoke synthetic lifecycle tests passed.'
}
finally {
    $env:PATH = $savedPath
    $env:MUSEECHO_FAKE_DOCKER_LOG = $savedLog
    $env:MUSEECHO_FAKE_DOCKER_MODE = $savedMode
    if (Test-Path -LiteralPath $fixtureRoot) {
        [System.IO.Directory]::Delete($fixtureRoot, $true)
    }
}

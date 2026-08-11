[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$savedSecretsDirectory = $env:MUSEECHO_SECRETS_DIR
$taskTempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$fixtureRoot = Join-Path $taskTempParent "museecho-container-contract-test-$PID-$([System.IO.Path]::GetRandomFileName())"
$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell.exe' }
$savedPath = $env:PATH
$savedDockerLog = $env:MUSEECHO_FAKE_DOCKER_LOG

Push-Location $repositoryRoot
try {
    $env:MUSEECHO_SECRETS_DIR = '.\repository-relative-secrets-must-not-win'
    $configText = & docker compose --profile production config --format json
    if ($LASTEXITCODE -ne 0) { throw 'production Compose config failed' }
    $config = $configText | ConvertFrom-Json
    $secretMount = @($config.services.app.volumes) |
        Where-Object { $_.target -eq '/run/secrets' } |
        Select-Object -First 1
    if (-not $secretMount) { throw 'production app has no /run/secrets mount' }
    if ($secretMount.type -ne 'bind' -or -not $secretMount.read_only) {
        throw 'production Secret mount must be a read-only bind'
    }
    if ($secretMount.source -ne '/etc/museecho/secrets') {
        throw "production Secret source is not fixed: $($secretMount.source)"
    }

    $fakeRepository = Join-Path $fixtureRoot 'incomplete-repository'
    $fakeScripts = Join-Path $fakeRepository 'scripts'
    $smokeTempParent = Join-Path $fixtureRoot 'smoke-temp'
    New-Item -ItemType Directory -Path $fakeScripts | Out-Null
    New-Item -ItemType Directory -Path $smokeTempParent | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'container-smoke.ps1') `
        -Destination (Join-Path $fakeScripts 'container-smoke.ps1')
    $savedErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $failureOutput = & $shell -NoProfile -ExecutionPolicy Bypass `
            -File (Join-Path $fakeScripts 'container-smoke.ps1') `
            -TaskTempParent $smokeTempParent 2>&1 | Out-String
        $failureExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorPreference
    }
    if ($failureExit -eq 0 -or $failureOutput -notmatch 'Required distribution file is missing') {
        throw "smoke setup failure probe did not reach fixture setup`n$failureOutput"
    }
    $residue = @(Get-ChildItem -LiteralPath $smokeTempParent -Directory `
        -Filter 'museecho-container-smoke-*')
    if ($residue.Count -ne 0) {
        throw "smoke fixture setup failure left task-temp residue: $($residue.FullName -join ', ')"
    }

    $offlineRepository = Join-Path $fixtureRoot 'offline-repository'
    $offlineScripts = Join-Path $offlineRepository 'scripts'
    $offlineTempParent = Join-Path $fixtureRoot 'offline-smoke-temp'
    $fakeBin = Join-Path $fixtureRoot 'fake-bin'
    $dockerLog = Join-Path $fixtureRoot 'offline-docker.log'
    New-Item -ItemType Directory -Path $offlineScripts, $offlineTempParent, $fakeBin | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'container-smoke.ps1') `
        -Destination (Join-Path $offlineScripts 'container-smoke.ps1')
    foreach ($requiredFile in @('Dockerfile', 'compose.yaml', 'Caddyfile')) {
        [System.IO.File]::WriteAllText(
            (Join-Path $offlineRepository $requiredFile),
            'offline synthetic fixture',
            [Text.UTF8Encoding]::new($false)
        )
    }
    $fakeDocker = Join-Path $fakeBin 'docker.cmd'
    [System.IO.File]::WriteAllText(
        $fakeDocker,
        @'
@echo off
echo %*>>"%MUSEECHO_FAKE_DOCKER_LOG%"
if "%1"=="image" if "%2"=="inspect" (
  echo sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  exit /b 0
)
echo %*| findstr /c:" config " >nul
if not errorlevel 1 exit /b 0
echo %*| findstr /c:" up " >nul
if not errorlevel 1 exit /b 23
echo %*| findstr /c:" down " >nul
if not errorlevel 1 exit /b 0
exit /b 99
'@,
        [Text.UTF8Encoding]::new($false)
    )
    $env:MUSEECHO_FAKE_DOCKER_LOG = $dockerLog
    $env:PATH = "$fakeBin$([IO.Path]::PathSeparator)$savedPath"
    $savedErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $offlineOutput = & $shell -NoProfile -ExecutionPolicy Bypass `
            -File (Join-Path $offlineScripts 'container-smoke.ps1') `
            -TaskTempParent $offlineTempParent -NoBuild `
            -DockerCommand $fakeDocker 2>&1 | Out-String
        $offlineExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorPreference
    }
    if ($offlineExit -eq 0) {
        throw 'no-build smoke probe unexpectedly completed through the forced up failure'
    }
    $offlineDockerLog = if (Test-Path -LiteralPath $dockerLog) {
        Get-Content -Raw -LiteralPath $dockerLog
    } else {
        ''
    }
    if ($offlineDockerLog -match '(?m)^compose .* build(?: |$)') {
        throw "no-build smoke invoked docker compose build`n$offlineDockerLog"
    }
    if ($offlineDockerLog -notmatch '(?m)^compose .* up .*--no-build') {
        throw "no-build smoke did not enforce compose up --no-build`n$offlineDockerLog`n$offlineOutput"
    }
    if ([regex]::Matches($offlineDockerLog, '(?m)^image inspect ').Count -ne 2) {
        throw "no-build smoke did not inspect both existing image identities`n$offlineDockerLog"
    }

    Write-Host 'Container contract synthetic tests passed.'
} finally {
    $env:PATH = $savedPath
    $env:MUSEECHO_FAKE_DOCKER_LOG = $savedDockerLog
    $env:MUSEECHO_SECRETS_DIR = $savedSecretsDirectory
    Pop-Location
    if (Test-Path -LiteralPath $fixtureRoot) {
        [System.IO.Directory]::Delete($fixtureRoot, $true)
    }
}

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$taskTempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$fixtureRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $taskTempBase "museecho-container-pytest-test-$PID-$([System.IO.Path]::GetRandomFileName())")
)
$fakeRepository = Join-Path $fixtureRoot 'repository'
$fakeScripts = Join-Path $fakeRepository 'scripts'
$fakeSitePackages = Join-Path $fakeRepository '.venv\Lib\site-packages'
$runnerTempParent = Join-Path $fixtureRoot 'runner-temp'
$runnerPath = Join-Path $fakeScripts 'container-pytest.ps1'
$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell.exe' }
$isWindowsPlatform = $env:OS -eq 'Windows_NT'
$fakeDockerPath = Join-Path $fixtureRoot $(
    if ($isWindowsPlatform) { 'fake-docker.cmd' } else { 'fake-docker' }
)

try {
    New-Item -ItemType Directory -Path $fakeScripts | Out-Null
    New-Item -ItemType Directory -Path $fakeSitePackages | Out-Null
    New-Item -ItemType Directory -Path $runnerTempParent | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'container-pytest.ps1') `
        -Destination $runnerPath
    foreach ($module in @('pytest', '_pytest', 'pluggy', 'iniconfig', 'pygments')) {
        New-Item -ItemType Directory -Path (Join-Path $fakeSitePackages $module) | Out-Null
    }
    [System.IO.File]::WriteAllText(
        (Join-Path $fakeSitePackages 'py.py'),
        '',
        [System.Text.Encoding]::UTF8
    )
    $fakeDocker = if ($isWindowsPlatform) {
        @'
@echo off
if "%1"=="image" if "%2"=="inspect" exit /b 0
if "%1"=="create" exit /b 0
if "%1"=="start" exit /b 0
if "%1"=="rm" if "%2"=="--force" exit /b 23
exit /b 99
'@
    } else {
        @'
#!/bin/sh
if [ "$1" = image ] && [ "$2" = inspect ]; then exit 0; fi
if [ "$1" = create ]; then exit 0; fi
if [ "$1" = start ]; then exit 0; fi
if [ "$1" = rm ] && [ "$2" = --force ]; then exit 23; fi
exit 99
'@
    }
    [System.IO.File]::WriteAllText(
        $fakeDockerPath,
        $fakeDocker,
        [System.Text.UTF8Encoding]::new($false)
    )
    if (-not $isWindowsPlatform) {
        & chmod 700 $fakeDockerPath
        if ($LASTEXITCODE -ne 0) { throw 'could not make fake Docker executable' }
    }

    $savedErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $shell -NoProfile -ExecutionPolicy Bypass -File $runnerPath `
            -Image fake-image:local `
            -DockerCommand $fakeDockerPath `
            -TaskTempParent $runnerTempParent 2>&1 | Out-String
        $actualExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorPreference
    }
    if ($actualExit -eq 0 -or $output -notmatch 'docker rm --force failed with exit code 23') {
        throw "container pytest did not surface Docker cleanup failure`n$output"
    }
    $residue = @(Get-ChildItem -LiteralPath $runnerTempParent -Directory `
        -Filter 'museecho-container-pytest-*')
    if ($residue.Count -ne 0) {
        throw "container pytest left dependency task-temp residue: $($residue.FullName -join ', ')"
    }

    Write-Host 'Container pytest synthetic cleanup tests passed.'
    $global:LASTEXITCODE = 0
} finally {
    if (Test-Path -LiteralPath $fixtureRoot) {
        [System.IO.Directory]::Delete($fixtureRoot, $true)
    }
}

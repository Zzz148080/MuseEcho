[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$EvidenceDirectory,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$PythonCommand = ''
)

$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw 'Version must be a three-part semantic version without a v prefix'
}
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$evidenceRoot = [System.IO.Path]::GetFullPath($EvidenceDirectory)
$outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
if (-not (Test-Path -LiteralPath $evidenceRoot -PathType Container)) {
    throw "evidence directory is missing: $evidenceRoot"
}
if (-not $PythonCommand) {
    $venvPython = if ($env:OS -eq 'Windows_NT') {
        Join-Path $repositoryRoot '.venv/Scripts/python.exe'
    } else {
        Join-Path $repositoryRoot '.venv/bin/python'
    }
    $PythonCommand = if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $venvPython
    } else {
        'python'
    }
}

$appTar = Join-Path $evidenceRoot 'museecho-app.tar'
$gatewayTar = Join-Path $evidenceRoot 'museecho-gateway.tar'
$manifestPath = Join-Path $evidenceRoot 'release-images.json'
$verifier = Join-Path $PSScriptRoot 'verify_release_identity.py'
$templateRoot = Join-Path $repositoryRoot 'release/offline-runtime'
$smokeSource = Join-Path $PSScriptRoot 'container-smoke.ps1'
foreach ($path in @(
    $appTar,
    $gatewayTar,
    $manifestPath,
    $verifier,
    (Join-Path $templateRoot 'offline-runtime.ps1'),
    (Join-Path $templateRoot 'compose.yaml'),
    (Join-Path $templateRoot 'README.md'),
    $smokeSource
)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "required offline release input is missing: $path"
    }
}

& $PythonCommand $verifier verify --manifest $manifestPath `
    --tar "app=$appTar" --tar "gateway=$gatewayTar"
if ($LASTEXITCODE -ne 0) {
    throw 'release identity verification failed before offline packaging'
}

$taskTempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$stagingRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $taskTempParent "museecho-offline-package-$PID-$([System.IO.Path]::GetRandomFileName())")
)
if (-not $stagingRoot.StartsWith($taskTempParent, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'invalid offline release staging path'
}
$zipName = "museecho-offline-runtime-v$Version.zip"
$zipPath = Join-Path $outputRoot $zipName
$checksumPath = Join-Path $outputRoot 'SHA256SUMS.txt'

try {
    New-Item -ItemType Directory -Path $stagingRoot | Out-Null
    $stagingScripts = Join-Path $stagingRoot 'scripts'
    New-Item -ItemType Directory -Path $stagingScripts | Out-Null
    foreach ($name in @('offline-runtime.ps1', 'compose.yaml', 'README.md')) {
        Copy-Item -LiteralPath (Join-Path $templateRoot $name) -Destination (Join-Path $stagingRoot $name)
    }
    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $stagingRoot 'release-images.json')
    Copy-Item -LiteralPath $smokeSource -Destination (Join-Path $stagingScripts 'container-smoke.ps1')
    [System.IO.File]::WriteAllText(
        (Join-Path $stagingRoot 'release-version.txt'),
        "v$Version`n",
        [System.Text.UTF8Encoding]::new($false)
    )

    if (-not (Test-Path -LiteralPath $outputRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $outputRoot | Out-Null
    }
    foreach ($path in @($zipPath, $checksumPath)) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            Remove-Item -LiteralPath $path -Force
        }
    }
    Compress-Archive -Path (Join-Path $stagingRoot '*') -DestinationPath $zipPath `
        -CompressionLevel Optimal

    $checksums = @(
        "$(((Get-FileHash -Algorithm SHA256 -LiteralPath $appTar).Hash.ToLowerInvariant()))  museecho-app.tar",
        "$(((Get-FileHash -Algorithm SHA256 -LiteralPath $gatewayTar).Hash.ToLowerInvariant()))  museecho-gateway.tar",
        "$(((Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()))  $zipName"
    )
    [System.IO.File]::WriteAllLines(
        $checksumPath,
        $checksums,
        [System.Text.UTF8Encoding]::new($false)
    )
} finally {
    if (Test-Path -LiteralPath $stagingRoot -PathType Container) {
        [System.IO.Directory]::Delete($stagingRoot, $true)
    }
}

Write-Host "Offline runtime kit: $zipPath"
Write-Host "Offline runtime checksums: $checksumPath"

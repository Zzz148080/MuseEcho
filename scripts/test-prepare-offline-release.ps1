[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$packager = Join-Path $PSScriptRoot 'prepare-offline-release.ps1'
$taskTempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$fixtureRoot = Join-Path $taskTempParent "museecho-offline-package-test-$PID-$([System.IO.Path]::GetRandomFileName())"
$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell.exe' }
$python = if ($env:OS -eq 'Windows_NT') {
    Join-Path $repositoryRoot '.venv/Scripts/python.exe'
} else {
    Join-Path $repositoryRoot '.venv/bin/python'
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )
    [System.IO.File]::WriteAllText($Path, $Value, [System.Text.UTF8Encoding]::new($false))
}

function New-DockerSaveFixture {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    $root = Join-Path $fixtureRoot "tar-$Name"
    New-Item -ItemType Directory -Path $root | Out-Null
    $configPath = Join-Path $root 'config.json'
    Write-Utf8NoBom -Path $configPath -Value "{`"architecture`":`"amd64`",`"os`":`"linux`",`"fixture`":`"$Name`"}"
    $configDigest = (Get-FileHash -Algorithm SHA256 -LiteralPath $configPath).Hash.ToLowerInvariant()
    $configName = "$configDigest.json"
    Move-Item -LiteralPath $configPath -Destination (Join-Path $root $configName)
    $manifestEntry = [ordered]@{
        Config = $configName
        RepoTags = @("museecho-$Name`:local")
        Layers = @()
    }
    Write-Utf8NoBom -Path (Join-Path $root 'manifest.json') `
        -Value ("[" + ($manifestEntry | ConvertTo-Json -Depth 4 -Compress) + "]`n")
    & tar -cf $Destination -C $root manifest.json $configName
    if ($LASTEXITCODE -ne 0) { throw "could not create $Name Docker-save fixture" }
    return "sha256:$configDigest"
}

function Invoke-Packager {
    param(
        [Parameter(Mandatory = $true)][string]$EvidenceDirectory,
        [Parameter(Mandatory = $true)][string]$OutputDirectory
    )
    $savedErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $shell -NoProfile -ExecutionPolicy Bypass -File $packager `
            -Version 0.1.0 -EvidenceDirectory $EvidenceDirectory `
            -OutputDirectory $OutputDirectory -PythonCommand $python 2>&1 | Out-String
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorPreference
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Output = $output }
}

try {
    if (-not (Test-Path -LiteralPath $packager -PathType Leaf)) {
        throw 'offline release packager is missing'
    }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "project Python is missing: $python"
    }
    $evidence = Join-Path $fixtureRoot 'evidence'
    $output = Join-Path $fixtureRoot 'output'
    $expanded = Join-Path $fixtureRoot 'expanded'
    New-Item -ItemType Directory -Path $evidence | Out-Null
    $appTar = Join-Path $evidence 'museecho-app.tar'
    $gatewayTar = Join-Path $evidence 'museecho-gateway.tar'
    $appId = New-DockerSaveFixture -Name app -Destination $appTar
    $gatewayId = New-DockerSaveFixture -Name gateway -Destination $gatewayTar
    $manifest = [ordered]@{
        schema_version = 1
        images = [ordered]@{
            app = [ordered]@{
                image_id = $appId
                tar_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $appTar).Hash.ToLowerInvariant()
            }
            gateway = [ordered]@{
                image_id = $gatewayId
                tar_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $gatewayTar).Hash.ToLowerInvariant()
            }
        }
    }
    $manifestPath = Join-Path $evidence 'release-images.json'
    Write-Utf8NoBom -Path $manifestPath -Value (($manifest | ConvertTo-Json -Depth 4) + "`n")

    $result = Invoke-Packager -EvidenceDirectory $evidence -OutputDirectory $output
    if ($result.ExitCode -ne 0) { throw "offline release packaging failed`n$($result.Output)" }
    $zipName = 'museecho-offline-runtime-v0.1.0.zip'
    $zipPath = Join-Path $output $zipName
    if (-not (Test-Path -LiteralPath $zipPath -PathType Leaf)) { throw 'runtime zip is missing' }
    Expand-Archive -LiteralPath $zipPath -DestinationPath $expanded
    foreach ($relativePath in @(
        'offline-runtime.ps1',
        'compose.yaml',
        'release-images.json',
        'README.md',
        'release-version.txt',
        'scripts/container-smoke.ps1'
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $expanded $relativePath) -PathType Leaf)) {
            throw "runtime zip is missing $relativePath"
        }
    }
    if ((Get-Content -Raw -LiteralPath (Join-Path $expanded 'release-version.txt')).Trim() -ne 'v0.1.0') {
        throw 'runtime zip contains the wrong release version'
    }

    $expectedChecksums = @(
        "$(($manifest.images.app.tar_sha256))  museecho-app.tar",
        "$(($manifest.images.gateway.tar_sha256))  museecho-gateway.tar",
        "$(((Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()))  $zipName"
    )
    $actualChecksums = @(Get-Content -LiteralPath (Join-Path $output 'SHA256SUMS.txt'))
    if (($actualChecksums -join "`n") -ne ($expectedChecksums -join "`n")) {
        throw "release checksums mismatch`n$($actualChecksums -join "`n")"
    }

    $badEvidence = Join-Path $fixtureRoot 'bad-evidence'
    $badOutput = Join-Path $fixtureRoot 'bad-output'
    Copy-Item -LiteralPath $evidence -Destination $badEvidence -Recurse
    $badManifestPath = Join-Path $badEvidence 'release-images.json'
    $badManifest = Get-Content -Raw -LiteralPath $badManifestPath | ConvertFrom-Json
    $badManifest.images.app.tar_sha256 = 'f' * 64
    Write-Utf8NoBom -Path $badManifestPath -Value (($badManifest | ConvertTo-Json -Depth 4) + "`n")
    $badResult = Invoke-Packager -EvidenceDirectory $badEvidence -OutputDirectory $badOutput
    if ($badResult.ExitCode -eq 0 -or $badResult.Output -notmatch 'release identity') {
        throw "packager accepted a mutated identity manifest`n$($badResult.Output)"
    }
    if (Test-Path -LiteralPath (Join-Path $badOutput $zipName) -PathType Leaf) {
        throw 'failed packaging left a runtime zip'
    }

    Write-Host 'Offline release packaging synthetic tests passed.'
    $global:LASTEXITCODE = 0
} finally {
    if (Test-Path -LiteralPath $fixtureRoot) {
        [System.IO.Directory]::Delete($fixtureRoot, $true)
    }
}

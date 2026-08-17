[CmdletBinding()]
param(
    [ValidateSet('Verify', 'Import', 'Start', 'Smoke', 'Stop')]
    [string]$Action = 'Verify',
    [string]$ArtifactDirectory = $PSScriptRoot,
    [string]$SecretsDirectory = '',
    [string]$DockerCommand = 'docker',
    [string]$CurlCommand = 'curl.exe',
    [ValidateRange(1, 65535)][int]$HttpsPort = 4173
)

$ErrorActionPreference = 'Stop'
$artifactRoot = [System.IO.Path]::GetFullPath($ArtifactDirectory)
$composePath = Join-Path $artifactRoot 'compose.yaml'
$manifestPath = Join-Path $artifactRoot 'release-images.json'
$tarPaths = @{
    app = Join-Path $artifactRoot 'museecho-app.tar'
    gateway = Join-Path $artifactRoot 'museecho-gateway.tar'
}
$imageNames = @{
    app = 'museecho-app:local'
    gateway = 'museecho-gateway:local'
}

if (-not $SecretsDirectory) {
    $userProfilePath = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
    if (-not $userProfilePath) { throw 'could not determine a default external Secret directory' }
    $SecretsDirectory = Join-Path $userProfilePath 'MuseEchoSecrets'
}
$secretRoot = [System.IO.Path]::GetFullPath($SecretsDirectory)

function Invoke-Docker {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $DockerCommand @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed: $($Arguments -join ' ')"
    }
}

function Invoke-OfflineCompose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $DockerCommand compose --file $composePath --project-name museecho-offline @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "offline Compose command failed: $($Arguments -join ' ')"
    }
}

function Assert-RequiredFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "required offline runtime file is missing: $([System.IO.Path]::GetFileName($Path))"
    }
}

function Read-ReleaseIdentity {
    foreach ($path in @($manifestPath, $tarPaths.app, $tarPaths.gateway)) {
        Assert-RequiredFile -Path $path
    }
    try {
        $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    } catch {
        throw 'release-images.json is not valid JSON'
    }
    if ($manifest.schema_version -ne 1 -or -not $manifest.images) {
        throw 'release image identity schema mismatch'
    }
    $names = @($manifest.images.PSObject.Properties.Name | Sort-Object)
    if ($names.Count -ne 2 -or $names[0] -ne 'app' -or $names[1] -ne 'gateway') {
        throw 'release image identity must contain exactly app and gateway'
    }
    $identities = [ordered]@{}
    foreach ($name in @('app', 'gateway')) {
        $entry = $manifest.images.$name
        if ($entry.image_id -notmatch '^sha256:[0-9a-f]{64}$') {
            throw "$name release image id is invalid"
        }
        if ($null -ne $entry.manifest_digest -and `
            $entry.manifest_digest -notmatch '^sha256:[0-9a-f]{64}$') {
            throw "$name release manifest digest is invalid"
        }
        if ($entry.tar_sha256 -notmatch '^[0-9a-f]{64}$') {
            throw "$name release tar SHA-256 is invalid"
        }
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $tarPaths[$name]).Hash.ToLowerInvariant()
        if ($actual -ne $entry.tar_sha256) {
            throw "$name release tar SHA-256 mismatch"
        }
        $identities[$name] = [pscustomobject]@{
            Config = [string]$entry.image_id
            Manifest = if ($null -ne $entry.manifest_digest) {
                [string]$entry.manifest_digest
            } else { '' }
        }
    }
    $appAllowedIds = @($identities.app.Config, $identities.app.Manifest) |
        Where-Object { $_ }
    $gatewayAllowedIds = @($identities.gateway.Config, $identities.gateway.Manifest) |
        Where-Object { $_ }
    $overlap = @($appAllowedIds | Where-Object { $_ -in $gatewayAllowedIds })
    if ($overlap.Count -gt 0) {
        throw 'app and gateway release identity sets must not overlap'
    }
    return $identities
}

function Import-ReleaseImages {
    $identities = Read-ReleaseIdentity
    foreach ($name in @('app', 'gateway')) {
        Invoke-Docker load --input $tarPaths[$name]
    }
    foreach ($name in @('app', 'gateway')) {
        $loaded = @(& $DockerCommand image inspect --format '{{.Id}}' $imageNames[$name])
        $loadedId = ($loaded -join '').Trim()
        $allowedIds = @($identities[$name].Config, $identities[$name].Manifest) |
            Where-Object { $_ }
        if ($LASTEXITCODE -ne 0 -or $loadedId -notin $allowedIds) {
            throw "$name loaded image identity mismatch: $loadedId, expected $($allowedIds -join ' or ')"
        }
        $identities[$name] | Add-Member -NotePropertyName Loaded -NotePropertyValue $loadedId
    }
    return $identities
}

function Initialize-AudioSecret {
    if (-not (Test-Path -LiteralPath $secretRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $secretRoot | Out-Null
    }
    $audioKeyPath = Join-Path $secretRoot 'audio-kek'
    if (-not (Test-Path -LiteralPath $audioKeyPath -PathType Leaf)) {
        $keyBytes = New-Object byte[] 32
        $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $generator.GetBytes($keyBytes)
        } finally {
            $generator.Dispose()
        }
        [System.IO.File]::WriteAllText(
            $audioKeyPath,
            [Convert]::ToBase64String($keyBytes),
            [System.Text.Encoding]::ASCII
        )
    }
    try {
        $decoded = [Convert]::FromBase64String((Get-Content -Raw -LiteralPath $audioKeyPath))
    } catch {
        throw 'audio-kek must contain valid Base64'
    }
    if ($decoded.Length -ne 32) { throw 'audio-kek must decode to exactly 32 bytes' }
}

function Set-ComposeEnvironment {
    $env:MUSEECHO_SECRETS_DIR = $secretRoot
    $env:MUSEECHO_HTTPS_PORT = [string]$HttpsPort
    $env:MUSEECHO_TRUSTED_ORIGINS = "https://localhost:$HttpsPort,https://127.0.0.1:$HttpsPort"
}

if ($Action -eq 'Verify') {
    $null = Read-ReleaseIdentity
    Write-Host 'Offline runtime assets verified.'
    exit 0
}

Assert-RequiredFile -Path $composePath
if ($Action -eq 'Stop') {
    Set-ComposeEnvironment
    Invoke-OfflineCompose down --remove-orphans
    Write-Host 'MuseEcho stopped; encrypted analysis data was preserved.'
    exit 0
}

$identities = Import-ReleaseImages
if ($Action -eq 'Import') {
    Write-Host "Offline images imported: app=$($identities.app.Loaded) gateway=$($identities.gateway.Loaded)"
    exit 0
}

if ($Action -eq 'Smoke') {
    $smokePath = Join-Path $artifactRoot 'scripts/container-smoke.ps1'
    Assert-RequiredFile -Path $smokePath
    & $smokePath -NoBuild -DockerCommand $DockerCommand -CurlCommand $CurlCommand `
        -ReleaseManifest $manifestPath
    if ($LASTEXITCODE -ne 0) { throw 'offline runtime smoke failed' }
    Write-Host 'Offline runtime smoke passed.'
    exit 0
}

Initialize-AudioSecret
Set-ComposeEnvironment
Invoke-OfflineCompose config --quiet
Invoke-OfflineCompose up --detach --wait --no-build
Write-Host "MuseEcho is ready at https://localhost:$HttpsPort"

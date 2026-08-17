[CmdletBinding()]
param(
    [string]$TaskTempParent = [System.IO.Path]::GetTempPath(),
    [switch]$NoBuild,
    [string]$DockerCommand = 'docker',
    [string]$CurlCommand = 'curl.exe',
    [string]$ReleaseManifest = '',
    [string]$ExpectedAppDaemonImageId = '',
    [string]$ExpectedAppConfigImageId = '',
    [string]$ExpectedGatewayDaemonImageId = '',
    [string]$ExpectedGatewayConfigImageId = ''
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$requiredFiles = if ($NoBuild) { @('compose.yaml') } else { @('Dockerfile', 'compose.yaml', 'Caddyfile') }
$taskTempParentPath = [System.IO.Path]::GetFullPath($TaskTempParent)
$smokeRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $taskTempParentPath "museecho-container-smoke-$PID-$([System.IO.Path]::GetRandomFileName())")
)
if (-not $smokeRoot.StartsWith($taskTempParentPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'invalid smoke task-temp path'
}
if ($smokeRoot.StartsWith($repositoryRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'smoke fixtures must be outside the repository'
}
$secretRoot = Join-Path $smokeRoot 'secrets'
$audioPath = Join-Path $smokeRoot 'fixture.wav'
$cookiePath = Join-Path $smokeRoot 'cookies.txt'
$createResponsePath = Join-Path $smokeRoot 'create.json'
$statusResponsePath = Join-Path $smokeRoot 'status.json'
$healthResponsePath = Join-Path $smokeRoot 'health.json'
$composeOverridePath = Join-Path $smokeRoot 'compose.smoke.yaml'
$composeFiles = @('--file', (Join-Path $repositoryRoot 'compose.yaml'), '--file', $composeOverridePath)

function Get-FreeTcpPort {
    $listener = New-Object System.Net.Sockets.TcpListener(
        [System.Net.IPAddress]::Loopback,
        0
    )
    $listener.Start()
    try {
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    } finally {
        $listener.Stop()
    }
}

function Invoke-DockerCompose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $DockerCommand compose @composeFiles --profile production @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose smoke override $($Arguments -join ' ') failed"
    }
}

function Assert-ImageId {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Value -notmatch '^sha256:[0-9a-f]{64}$') {
        throw "$Label must be a lowercase sha256 image identity"
    }
}

function Assert-Digest {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Value -notmatch '^[0-9a-f]{64}$') {
        throw "$Label must be a lowercase sha256 digest"
    }
}

function Read-TrustedReleaseIdentity {
    if (-not $ReleaseManifest -or -not (Test-Path -LiteralPath $ReleaseManifest -PathType Leaf)) {
        throw 'no-build smoke requires a trusted release manifest'
    }
    try {
        $manifest = Get-Content -Raw -LiteralPath $ReleaseManifest | ConvertFrom-Json
    } catch {
        throw 'trusted release manifest is not valid JSON'
    }
    if ($manifest.schema_version -eq 1 -and $manifest.images) {
        $names = @($manifest.images.PSObject.Properties.Name | Sort-Object)
        if ($names.Count -ne 2 -or $names[0] -ne 'app' -or $names[1] -ne 'gateway') {
            throw 'release image identity must contain exactly app and gateway'
        }
        Assert-ImageId -Value $manifest.images.app.image_id -Label 'app release image id'
        Assert-ImageId -Value $manifest.images.gateway.image_id -Label 'gateway release image id'
        if ($null -ne $manifest.images.app.manifest_digest) {
            Assert-ImageId -Value $manifest.images.app.manifest_digest `
                -Label 'app release manifest digest'
        }
        if ($null -ne $manifest.images.gateway.manifest_digest) {
            Assert-ImageId -Value $manifest.images.gateway.manifest_digest `
                -Label 'gateway release manifest digest'
        }
        Assert-Digest -Value $manifest.images.app.tar_sha256 -Label 'app release tar digest'
        Assert-Digest -Value $manifest.images.gateway.tar_sha256 -Label 'gateway release tar digest'
        $appAllowedIds = @([string]$manifest.images.app.image_id)
        if ($manifest.images.app.manifest_digest) {
            $appAllowedIds += [string]$manifest.images.app.manifest_digest
        }
        $gatewayAllowedIds = @([string]$manifest.images.gateway.image_id)
        if ($manifest.images.gateway.manifest_digest) {
            $gatewayAllowedIds += [string]$manifest.images.gateway.manifest_digest
        }
        $overlap = @($appAllowedIds | Where-Object { $_ -in $gatewayAllowedIds })
        if ($overlap.Count -gt 0) {
            throw 'app and gateway must not share image identities'
        }
        $script:ExpectedAppDaemonImageIds = $appAllowedIds
        $script:ExpectedAppConfigImageId = [string]$manifest.images.app.image_id
        $script:ExpectedGatewayDaemonImageIds = $gatewayAllowedIds
        $script:ExpectedGatewayConfigImageId = [string]$manifest.images.gateway.image_id
        return
    }
    $expected = [ordered]@{
        AppDaemon = $ExpectedAppDaemonImageId
        AppConfig = $ExpectedAppConfigImageId
        GatewayDaemon = $ExpectedGatewayDaemonImageId
        GatewayConfig = $ExpectedGatewayConfigImageId
    }
    foreach ($entry in $expected.GetEnumerator()) {
        Assert-ImageId -Value $entry.Value -Label "expected $($entry.Key)"
    }
    if (
        $ExpectedAppDaemonImageId -eq $ExpectedGatewayDaemonImageId -or
        $ExpectedAppConfigImageId -eq $ExpectedGatewayConfigImageId -or
        $ExpectedAppDaemonImageId -eq $ExpectedGatewayConfigImageId -or
        $ExpectedAppConfigImageId -eq $ExpectedGatewayDaemonImageId
    ) {
        throw 'app and gateway must not share image identities'
    }
    if (
        $manifest.schema_version -ne 1 -or
        $manifest.app.daemon_image_id -ne $ExpectedAppDaemonImageId -or
        $manifest.app.config_image_id -ne $ExpectedAppConfigImageId -or
        $manifest.gateway.daemon_image_id -ne $ExpectedGatewayDaemonImageId -or
        $manifest.gateway.config_image_id -ne $ExpectedGatewayConfigImageId
    ) {
        throw 'trusted release identity mismatch'
    }
    $script:ExpectedAppDaemonImageIds = @($ExpectedAppDaemonImageId)
    $script:ExpectedGatewayDaemonImageIds = @($ExpectedGatewayDaemonImageId)
}

function Get-ExistingImageId {
    param(
        [Parameter(Mandatory = $true)][string]$Image,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Service
    )
    $output = @(& $DockerCommand image inspect --format '{{.Id}}' $Image)
    $inspectExit = $LASTEXITCODE
    $imageId = ($output -join '').Trim()
    if ($inspectExit -ne 0 -or $imageId -notmatch '^sha256:[0-9a-f]{64}$') {
        throw "no-build smoke requires an existing sha256 image identity for $Image"
    }
    if ($imageId -notin $Expected) {
        throw "$Service daemon image identity mismatch: $imageId, expected $($Expected -join ' or ')"
    }
    return $imageId
}

function Assert-ComposeImageConfiguration {
    $output = @(& $DockerCommand compose @composeFiles --profile production config --format json)
    if ($LASTEXITCODE -ne 0) { throw 'docker compose config identity inspection failed' }
    try {
        $config = ($output -join "`n") | ConvertFrom-Json
    } catch {
        throw 'docker compose config identity output was not valid JSON'
    }
    if (
        $config.services.app.image -ne 'museecho-app:local' -or
        $config.services.gateway.image -ne 'museecho-gateway:local'
    ) {
        throw 'docker compose services do not reference the verified local image tags'
    }
}

function Assert-RunningImageIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][string]$Expected
    )
    $containerOutput = @(
        & $DockerCommand compose @composeFiles --profile production ps --quiet $Service
    )
    $containerId = ($containerOutput -join '').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $containerId) {
        throw "no-build smoke could not identify the running $Service container"
    }
    $imageOutput = @(& $DockerCommand container inspect --format '{{.Image}}' $containerId)
    $imageId = ($imageOutput -join '').Trim()
    if ($LASTEXITCODE -ne 0 -or $imageId -ne $Expected) {
        throw "running $Service image identity mismatch: $imageId, expected $Expected"
    }
}

function Assert-RunningReleaseIdentity {
    Assert-RunningImageIdentity -Service 'app' -Expected $ExpectedAppDaemonImageId
    Assert-RunningImageIdentity -Service 'gateway' -Expected $ExpectedGatewayDaemonImageId
}

function Write-SmokeWave {
    param([Parameter(Mandatory = $true)][string]$Path)
    $sampleRate = 8000
    $sampleCount = $sampleRate * 2
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Create)
    $writer = New-Object System.IO.BinaryWriter($stream)
    try {
        $writer.Write([System.Text.Encoding]::ASCII.GetBytes('RIFF'))
        $writer.Write([int](36 + $sampleCount * 2))
        $writer.Write([System.Text.Encoding]::ASCII.GetBytes('WAVEfmt '))
        $writer.Write([int]16)
        $writer.Write([int16]1)
        $writer.Write([int16]1)
        $writer.Write([int]$sampleRate)
        $writer.Write([int]($sampleRate * 2))
        $writer.Write([int16]2)
        $writer.Write([int16]16)
        $writer.Write([System.Text.Encoding]::ASCII.GetBytes('data'))
        $writer.Write([int]($sampleCount * 2))
        for ($index = 0; $index -lt $sampleCount; $index++) {
            $sample = [int16](10000 * [Math]::Sin(2 * [Math]::PI * 261.6256 * $index / $sampleRate))
            $writer.Write($sample)
        }
    } finally {
        $writer.Dispose()
        $stream.Dispose()
    }
}

$locationPushed = $false
$composeCleanupRequired = $false
try {
    New-Item -ItemType Directory -Path $secretRoot | Out-Null
    foreach ($relativePath in $requiredFiles) {
        $candidate = Join-Path $repositoryRoot $relativePath
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "Required distribution file is missing: $relativePath"
        }
    }

    $keyBytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($keyBytes)
    $audioKeyPath = Join-Path $secretRoot 'audio-kek'
    [System.IO.File]::WriteAllText(
        $audioKeyPath,
        [Convert]::ToBase64String($keyBytes),
        [System.Text.Encoding]::ASCII
    )
    Set-ItemProperty -LiteralPath $audioKeyPath -Name IsReadOnly -Value $true
    Write-SmokeWave -Path $audioPath
    $escapedSecretRoot = $secretRoot.Replace("'", "''")
    [System.IO.File]::WriteAllText(
        $composeOverridePath,
        "services:`n  app:`n    volumes:`n      - type: bind`n        source: '$escapedSecretRoot'`n        target: /run/secrets`n        read_only: true`n",
        [System.Text.UTF8Encoding]::new($false)
    )
    $env:COMPOSE_PROJECT_NAME = "museecho-smoke-$PID"
    $env:MUSEECHO_HTTP_PORT = [string](Get-FreeTcpPort)
    do {
        $env:MUSEECHO_HTTPS_PORT = [string](Get-FreeTcpPort)
    } while ($env:MUSEECHO_HTTPS_PORT -eq $env:MUSEECHO_HTTP_PORT)
    $env:MUSEECHO_TRUSTED_ORIGINS = "https://localhost:$($env:MUSEECHO_HTTPS_PORT)"
    $httpsBaseUrl = "https://localhost:$($env:MUSEECHO_HTTPS_PORT)"

    Push-Location $repositoryRoot
    $locationPushed = $true
    $composeCleanupRequired = $true
    Invoke-DockerCompose config --quiet
    if ($NoBuild) {
        Read-TrustedReleaseIdentity
        Assert-ComposeImageConfiguration
        $appImageId = Get-ExistingImageId -Image 'museecho-app:local' `
            -Expected $ExpectedAppDaemonImageIds -Service 'app'
        $gatewayImageId = Get-ExistingImageId -Image 'museecho-gateway:local' `
            -Expected $ExpectedGatewayDaemonImageIds -Service 'gateway'
        $script:ExpectedAppDaemonImageId = $appImageId
        $script:ExpectedGatewayDaemonImageId = $gatewayImageId
        Write-Host "No-build smoke app identity: $appImageId"
        Write-Host "No-build smoke gateway identity: $gatewayImageId"
        Invoke-DockerCompose up --no-build --detach --wait
        Assert-RunningReleaseIdentity
    } else {
        Invoke-DockerCompose build
        Invoke-DockerCompose up --detach --wait
    }

    & $CurlCommand --fail --silent --show-error --insecure `
        --output $healthResponsePath "$httpsBaseUrl/api/health"
    if ($LASTEXITCODE -ne 0) { throw 'container health request failed' }
    $health = Get-Content -Raw -LiteralPath $healthResponsePath | ConvertFrom-Json
    if ($health.status -ne 'ready') { throw 'container health response was not ready' }

    & $CurlCommand --fail --silent --show-error --insecure --cookie-jar $cookiePath `
        --form "file=@$audioPath;type=audio/wav" `
        --output $createResponsePath "$httpsBaseUrl/api/analyses"
    if ($LASTEXITCODE -ne 0) { throw 'container upload failed' }
    $created = Get-Content -Raw -LiteralPath $createResponsePath | ConvertFrom-Json
    if (-not $created.analysis_id) { throw 'container upload returned no analysis id' }

    $statusUri = "$httpsBaseUrl/api/analyses/$($created.analysis_id)/status"
    $deadline = [DateTime]::UtcNow.AddMinutes(2)
    do {
        Start-Sleep -Milliseconds 500
        & $CurlCommand --fail --silent --show-error --insecure --cookie $cookiePath `
            --output $statusResponsePath $statusUri
        if ($LASTEXITCODE -ne 0) { throw 'container status request failed' }
        $status = Get-Content -Raw -LiteralPath $statusResponsePath | ConvertFrom-Json
        if ($status.stage -eq 'failed') { throw "container analysis failed: $($status.error_code)" }
    } while ($status.stage -ne 'complete' -and [DateTime]::UtcNow -lt $deadline)
    if ($status.stage -ne 'complete') { throw 'container analysis timed out' }

    Invoke-DockerCompose restart app
    if ($NoBuild) {
        Invoke-DockerCompose up --no-build --detach --wait
        Assert-RunningReleaseIdentity
    } else {
        Invoke-DockerCompose up --detach --wait
    }
    & $CurlCommand --fail --silent --show-error --insecure --cookie $cookiePath `
        --output $statusResponsePath $statusUri
    if ($LASTEXITCODE -ne 0) { throw 'persisted status was unavailable after restart' }
    $persisted = Get-Content -Raw -LiteralPath $statusResponsePath | ConvertFrom-Json
    if ($persisted.stage -ne 'complete') { throw 'analysis did not persist across restart' }

    & $DockerCommand compose @composeFiles --profile production exec --no-TTY app python -c `
        "import pathlib,sys; files=(p for p in pathlib.Path('/data').rglob('*') if p.is_file()); bad=[str(p) for p in files if p.suffix.lower() in {'.wav','.mp3'} or p.open('rb').read(12).startswith((b'RIFF',b'ID3'))]; print(*bad,sep='\n'); sys.exit(bool(bad))"
    if ($LASTEXITCODE -ne 0) { throw 'plaintext audio remained in the persistent volume' }

    $keyText = Get-Content -Raw -LiteralPath $audioKeyPath
    $imageHistory = & $DockerCommand history --no-trunc museecho-app:local
    if ($LASTEXITCODE -ne 0) { throw 'container image history audit failed' }
    if (($imageHistory -join "`n").Contains($keyText)) {
        throw 'audio key appeared in container image history'
    }
} finally {
    $cleanupFailures = New-Object System.Collections.Generic.List[string]
    if ($composeCleanupRequired) {
        $savedErrorPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & $DockerCommand compose @composeFiles --profile production down `
                --volumes --remove-orphans 2>&1 | Out-Null
            $composeDownExit = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $savedErrorPreference
        }
        if ($composeDownExit -ne 0) {
            $cleanupFailures.Add("docker compose down failed with exit code $composeDownExit")
        }
    }
    if ($locationPushed) {
        Pop-Location
    }
    if (Test-Path -LiteralPath $smokeRoot) {
        try {
            Get-ChildItem -LiteralPath $smokeRoot -Recurse -Force | ForEach-Object {
                if ($_.IsReadOnly) { $_.IsReadOnly = $false }
            }
            [System.IO.Directory]::Delete($smokeRoot, $true)
        } catch {
            $cleanupFailures.Add("task-temp cleanup failed: $($_.Exception.Message)")
        }
    }
    if ($cleanupFailures.Count -gt 0) {
        throw ($cleanupFailures -join '; ')
    }
}

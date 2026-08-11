[CmdletBinding()]
param(
    [string]$TaskTempParent = [System.IO.Path]::GetTempPath(),
    [switch]$NoBuild,
    [string]$DockerCommand = 'docker'
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$requiredFiles = @('Dockerfile', 'compose.yaml', 'Caddyfile')
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

function Get-ExistingImageId {
    param([Parameter(Mandatory = $true)][string]$Image)
    $output = @(& $DockerCommand image inspect --format '{{.Id}}' $Image)
    $inspectExit = $LASTEXITCODE
    $imageId = ($output -join '').Trim()
    if ($inspectExit -ne 0 -or $imageId -notmatch '^sha256:[0-9a-f]{64}$') {
        throw "no-build smoke requires an existing sha256 image identity for $Image"
    }
    return $imageId
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
        $appImageId = Get-ExistingImageId -Image 'museecho-app:local'
        $gatewayImageId = Get-ExistingImageId -Image 'museecho-gateway:local'
        Write-Host "No-build smoke app identity: $appImageId"
        Write-Host "No-build smoke gateway identity: $gatewayImageId"
        Invoke-DockerCompose up --no-build --detach --wait
    } else {
        Invoke-DockerCompose build
        Invoke-DockerCompose up --detach --wait
    }

    & curl.exe --fail --silent --show-error --insecure `
        --output $healthResponsePath "$httpsBaseUrl/api/health"
    if ($LASTEXITCODE -ne 0) { throw 'container health request failed' }
    $health = Get-Content -Raw -LiteralPath $healthResponsePath | ConvertFrom-Json
    if ($health.status -ne 'ready') { throw 'container health response was not ready' }

    & curl.exe --fail --silent --show-error --insecure --cookie-jar $cookiePath `
        --form "file=@$audioPath;type=audio/wav" `
        --output $createResponsePath "$httpsBaseUrl/api/analyses"
    if ($LASTEXITCODE -ne 0) { throw 'container upload failed' }
    $created = Get-Content -Raw -LiteralPath $createResponsePath | ConvertFrom-Json
    if (-not $created.analysis_id) { throw 'container upload returned no analysis id' }

    $statusUri = "$httpsBaseUrl/api/analyses/$($created.analysis_id)/status"
    $deadline = [DateTime]::UtcNow.AddMinutes(2)
    do {
        Start-Sleep -Milliseconds 500
        & curl.exe --fail --silent --show-error --insecure --cookie $cookiePath `
            --output $statusResponsePath $statusUri
        if ($LASTEXITCODE -ne 0) { throw 'container status request failed' }
        $status = Get-Content -Raw -LiteralPath $statusResponsePath | ConvertFrom-Json
        if ($status.stage -eq 'failed') { throw "container analysis failed: $($status.error_code)" }
    } while ($status.stage -ne 'complete' -and [DateTime]::UtcNow -lt $deadline)
    if ($status.stage -ne 'complete') { throw 'container analysis timed out' }

    Invoke-DockerCompose restart app
    Invoke-DockerCompose up --detach --wait
    & curl.exe --fail --silent --show-error --insecure --cookie $cookiePath `
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

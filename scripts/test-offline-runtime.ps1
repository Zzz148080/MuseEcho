[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$receiverSource = Join-Path $repositoryRoot 'release/offline-runtime/offline-runtime.ps1'
$composeSource = Join-Path $repositoryRoot 'release/offline-runtime/compose.yaml'
$taskTempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$fixtureRoot = Join-Path $taskTempParent "museecho-offline-runtime-test-$PID-$([System.IO.Path]::GetRandomFileName())"
$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell.exe' }
$isWindowsPlatform = $env:OS -eq 'Windows_NT'
$savedDockerLog = $env:MUSEECHO_FAKE_DOCKER_LOG
$savedDockerMode = $env:MUSEECHO_FAKE_DOCKER_MODE
$savedAppId = $env:MUSEECHO_EXPECTED_APP_IMAGE_ID
$savedGatewayId = $env:MUSEECHO_EXPECTED_GATEWAY_IMAGE_ID

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )
    [System.IO.File]::WriteAllText($Path, $Value, [System.Text.UTF8Encoding]::new($false))
}

function Invoke-Receiver {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('Verify', 'Import', 'Start', 'Stop')]
        [string]$Action,
        [Parameter(Mandatory = $true)][string]$KitDirectory,
        [Parameter(Mandatory = $true)][string]$SecretDirectory,
        [Parameter(Mandatory = $true)][string]$DockerCommand
    )
    $savedErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $shell -NoProfile -ExecutionPolicy Bypass `
            -File (Join-Path $KitDirectory 'offline-runtime.ps1') `
            -Action $Action -ArtifactDirectory $KitDirectory `
            -SecretsDirectory $SecretDirectory -DockerCommand $DockerCommand 2>&1 | Out-String
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorPreference
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Output = $output }
}

try {
    if (-not (Test-Path -LiteralPath $receiverSource -PathType Leaf)) {
        throw 'offline runtime receiver is missing'
    }
    if (-not (Test-Path -LiteralPath $composeSource -PathType Leaf)) {
        throw 'offline runtime Compose file is missing'
    }

    $kitRoot = Join-Path $fixtureRoot 'kit'
    $secretRoot = Join-Path $fixtureRoot 'secrets'
    $fakeBin = Join-Path $fixtureRoot 'fake-bin'
    $dockerLog = Join-Path $fixtureRoot 'docker.log'
    New-Item -ItemType Directory -Path $kitRoot, $fakeBin | Out-Null
    Copy-Item -LiteralPath $receiverSource -Destination (Join-Path $kitRoot 'offline-runtime.ps1')
    Copy-Item -LiteralPath $composeSource -Destination (Join-Path $kitRoot 'compose.yaml')

    $appTar = Join-Path $kitRoot 'museecho-app.tar'
    $gatewayTar = Join-Path $kitRoot 'museecho-gateway.tar'
    Write-Utf8NoBom -Path $appTar -Value 'literal app archive fixture'
    Write-Utf8NoBom -Path $gatewayTar -Value 'literal gateway archive fixture'
    $appId = 'sha256:' + ('1' * 64)
    $gatewayId = 'sha256:' + ('2' * 64)
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
    Write-Utf8NoBom -Path (Join-Path $kitRoot 'release-images.json') `
        -Value (($manifest | ConvertTo-Json -Depth 4) + "`n")

    $fakeDocker = Join-Path $fakeBin $(if ($isWindowsPlatform) { 'docker.cmd' } else { 'docker' })
    $fakeDockerContents = if ($isWindowsPlatform) {
        @'
@echo off
echo %*>>"%MUSEECHO_FAKE_DOCKER_LOG%"
if "%1"=="load" exit /b 0
if "%1"=="image" if "%2"=="inspect" echo %*| findstr /c:"museecho-app:local" >nul && (
  if "%MUSEECHO_FAKE_DOCKER_MODE%"=="wrong-app-id" echo sha256:9999999999999999999999999999999999999999999999999999999999999999 && exit /b 0
  echo %MUSEECHO_EXPECTED_APP_IMAGE_ID%
  exit /b 0
)
if "%1"=="image" if "%2"=="inspect" echo %MUSEECHO_EXPECTED_GATEWAY_IMAGE_ID% && exit /b 0
if "%1"=="compose" exit /b 0
exit /b 99
'@
    } else {
        @'
#!/bin/sh
printf '%s\n' "$*" >> "$MUSEECHO_FAKE_DOCKER_LOG"
case "$*" in
  load*) exit 0 ;;
  "image inspect"*"museecho-app:local"*)
    if [ "$MUSEECHO_FAKE_DOCKER_MODE" = wrong-app-id ]; then
      echo sha256:9999999999999999999999999999999999999999999999999999999999999999
    else
      echo "$MUSEECHO_EXPECTED_APP_IMAGE_ID"
    fi
    exit 0 ;;
  "image inspect"*"museecho-gateway:local"*) echo "$MUSEECHO_EXPECTED_GATEWAY_IMAGE_ID"; exit 0 ;;
  compose*) exit 0 ;;
esac
exit 99
'@
    }
    Write-Utf8NoBom -Path $fakeDocker -Value $fakeDockerContents
    if (-not $isWindowsPlatform) {
        & chmod 700 $fakeDocker
        if ($LASTEXITCODE -ne 0) { throw 'could not make fake Docker executable' }
    }
    Write-Utf8NoBom -Path $dockerLog -Value ''
    $env:MUSEECHO_FAKE_DOCKER_LOG = $dockerLog
    $env:MUSEECHO_EXPECTED_APP_IMAGE_ID = $appId
    $env:MUSEECHO_EXPECTED_GATEWAY_IMAGE_ID = $gatewayId
    $env:MUSEECHO_FAKE_DOCKER_MODE = 'success'

    $verify = Invoke-Receiver -Action Verify -KitDirectory $kitRoot `
        -SecretDirectory $secretRoot -DockerCommand $fakeDocker
    if ($verify.ExitCode -ne 0) { throw "receiver verify failed`n$($verify.Output)" }
    if ((Get-Content -Raw -LiteralPath $dockerLog).Length -ne 0) {
        throw 'Verify invoked Docker'
    }

    $originalAppBytes = [System.IO.File]::ReadAllBytes($appTar)
    [System.IO.File]::AppendAllText($appTar, 'modified', [System.Text.UTF8Encoding]::new($false))
    $badHash = Invoke-Receiver -Action Verify -KitDirectory $kitRoot `
        -SecretDirectory $secretRoot -DockerCommand $fakeDocker
    if ($badHash.ExitCode -eq 0 -or $badHash.Output -notmatch 'app release tar SHA-256 mismatch') {
        throw "receiver accepted a modified app archive`n$($badHash.Output)"
    }
    if ((Get-Content -Raw -LiteralPath $dockerLog).Length -ne 0) {
        throw 'failed hash verification invoked Docker'
    }
    [System.IO.File]::WriteAllBytes($appTar, $originalAppBytes)

    $env:MUSEECHO_FAKE_DOCKER_MODE = 'wrong-app-id'
    $wrongId = Invoke-Receiver -Action Import -KitDirectory $kitRoot `
        -SecretDirectory $secretRoot -DockerCommand $fakeDocker
    if ($wrongId.ExitCode -eq 0 -or $wrongId.Output -notmatch 'app loaded image identity mismatch') {
        throw "receiver accepted the wrong loaded app identity`n$($wrongId.Output)"
    }
    if ((Get-Content -Raw -LiteralPath $dockerLog) -match '(?m)^compose ') {
        throw 'identity failure reached Compose'
    }

    Write-Utf8NoBom -Path $dockerLog -Value ''
    $env:MUSEECHO_FAKE_DOCKER_MODE = 'success'
    $start = Invoke-Receiver -Action Start -KitDirectory $kitRoot `
        -SecretDirectory $secretRoot -DockerCommand $fakeDocker
    if ($start.ExitCode -ne 0) { throw "receiver start failed`n$($start.Output)" }
    $startLog = Get-Content -Raw -LiteralPath $dockerLog
    if ($startLog -match '(?im)(^|\s)(build|pull)(\s|$)') {
        throw "offline receiver used a build or pull path`n$startLog"
    }
    if ($startLog -notmatch '(?m)^compose .* up .*--no-build') {
        throw "offline receiver omitted --no-build`n$startLog"
    }
    $keyBytes = [Convert]::FromBase64String((Get-Content -Raw -LiteralPath (Join-Path $secretRoot 'audio-kek')))
    if ($keyBytes.Length -ne 32) { throw 'receiver did not generate a 32-byte KEK' }

    Write-Utf8NoBom -Path $dockerLog -Value ''
    $stop = Invoke-Receiver -Action Stop -KitDirectory $kitRoot `
        -SecretDirectory $secretRoot -DockerCommand $fakeDocker
    if ($stop.ExitCode -ne 0) { throw "receiver stop failed`n$($stop.Output)" }
    $stopLog = Get-Content -Raw -LiteralPath $dockerLog
    if ($stopLog -notmatch '(?m)^compose .* down .*--remove-orphans') {
        throw "receiver stop omitted down --remove-orphans`n$stopLog"
    }
    if ($stopLog -match '--volumes') { throw 'receiver stop deleted the data volume' }

    Write-Host 'Offline runtime synthetic tests passed.'
    $global:LASTEXITCODE = 0
} finally {
    $env:MUSEECHO_FAKE_DOCKER_LOG = $savedDockerLog
    $env:MUSEECHO_FAKE_DOCKER_MODE = $savedDockerMode
    $env:MUSEECHO_EXPECTED_APP_IMAGE_ID = $savedAppId
    $env:MUSEECHO_EXPECTED_GATEWAY_IMAGE_ID = $savedGatewayId
    if (Test-Path -LiteralPath $fixtureRoot) {
        [System.IO.Directory]::Delete($fixtureRoot, $true)
    }
}

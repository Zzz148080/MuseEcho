[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$savedSecretsDirectory = $env:MUSEECHO_SECRETS_DIR
$taskTempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$fixtureRoot = Join-Path $taskTempParent "museecho-container-contract-test-$PID-$([System.IO.Path]::GetRandomFileName())"
$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell.exe' }
$isWindowsPlatform = $env:OS -eq 'Windows_NT'
$savedPath = $env:PATH
$savedDockerLog = $env:MUSEECHO_FAKE_DOCKER_LOG
$savedDockerMode = $env:MUSEECHO_FAKE_DOCKER_MODE
$savedAppDaemonId = $env:MUSEECHO_EXPECTED_APP_DAEMON_ID
$savedGatewayDaemonId = $env:MUSEECHO_EXPECTED_GATEWAY_DAEMON_ID
$savedAppConfigId = $env:MUSEECHO_EXPECTED_APP_CONFIG_ID
$savedGatewayConfigId = $env:MUSEECHO_EXPECTED_GATEWAY_CONFIG_ID

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
    $fakeDocker = Join-Path $fakeBin $(if ($isWindowsPlatform) { 'docker.cmd' } else { 'docker' })
    $fakeCurl = Join-Path $fakeBin $(if ($isWindowsPlatform) { 'curl.cmd' } else { 'curl' })
    $appDaemonId = 'sha256:' + ('1' * 64)
    $appConfigId = 'sha256:' + ('2' * 64)
    $gatewayDaemonId = 'sha256:' + ('3' * 64)
    $gatewayConfigId = 'sha256:' + ('4' * 64)
    $releaseManifest = Join-Path $fixtureRoot 'trusted-release.json'
    [System.IO.File]::WriteAllText(
        $releaseManifest,
        ([ordered]@{
            schema_version = 1
            app = [ordered]@{
                daemon_image_id = $appDaemonId
                config_image_id = $appConfigId
            }
            gateway = [ordered]@{
                daemon_image_id = $gatewayDaemonId
                config_image_id = $gatewayConfigId
            }
        } | ConvertTo-Json -Depth 3),
        [Text.UTF8Encoding]::new($false)
    )
    $fakeDockerContents = if ($isWindowsPlatform) {
        @'
@echo off
echo %*>>"%MUSEECHO_FAKE_DOCKER_LOG%"
if "%1"=="image" if "%2"=="inspect" echo %*| findstr /c:"museecho-app:local" >nul && (
  if "%MUSEECHO_FAKE_DOCKER_MODE%"=="wrong-app-tag" echo sha256:5555555555555555555555555555555555555555555555555555555555555555 && exit /b 0
  if "%MUSEECHO_FAKE_DOCKER_MODE%"=="classic-current" echo %MUSEECHO_EXPECTED_APP_CONFIG_ID% && exit /b 0
  echo %MUSEECHO_EXPECTED_APP_DAEMON_ID%
  exit /b 0
)
if "%1"=="image" if "%2"=="inspect" echo %*| findstr /c:"museecho-gateway:local" >nul && (
  if "%MUSEECHO_FAKE_DOCKER_MODE%"=="classic-current" echo %MUSEECHO_EXPECTED_GATEWAY_CONFIG_ID% && exit /b 0
  echo %MUSEECHO_EXPECTED_GATEWAY_DAEMON_ID%
  exit /b 0
)
if "%1"=="container" if "%2"=="inspect" if "%5"=="app-container" (
  if "%MUSEECHO_FAKE_DOCKER_MODE%"=="runtime-drift" echo sha256:6666666666666666666666666666666666666666666666666666666666666666 && exit /b 0
  if "%MUSEECHO_FAKE_DOCKER_MODE%"=="classic-current" echo %MUSEECHO_EXPECTED_APP_CONFIG_ID% && exit /b 0
  echo %MUSEECHO_EXPECTED_APP_DAEMON_ID%
  exit /b 0
)
if "%1"=="container" if "%2"=="inspect" if "%5"=="gateway-container" (
  if "%MUSEECHO_FAKE_DOCKER_MODE%"=="classic-current" echo %MUSEECHO_EXPECTED_GATEWAY_CONFIG_ID% && exit /b 0
  echo %MUSEECHO_EXPECTED_GATEWAY_DAEMON_ID%
  exit /b 0
)
echo %*| findstr /c:" config --format json" >nul && echo {"services":{"app":{"image":"museecho-app:local"},"gateway":{"image":"museecho-gateway:local"}}} && exit /b 0
echo %*| findstr /c:" config --quiet" >nul && exit /b 0
echo %*| findstr /c:" ps --quiet app" >nul && echo app-container && exit /b 0
echo %*| findstr /c:" ps --quiet gateway" >nul && echo gateway-container && exit /b 0
echo %*| findstr /c:" up " >nul && exit /b 0
echo %*| findstr /c:" restart " >nul && exit /b 0
echo %*| findstr /c:" exec " >nul && exit /b 0
echo %*| findstr /c:" down " >nul && exit /b 0
if "%1"=="history" echo safe-history && exit /b 0
exit /b 99
'@
    } else {
        @'
#!/bin/sh
printf '%s\n' "$*" >> "$MUSEECHO_FAKE_DOCKER_LOG"
case "$*" in
  *"image inspect"*"museecho-app:local"*)
    if [ "$MUSEECHO_FAKE_DOCKER_MODE" = wrong-app-tag ]; then
      echo sha256:5555555555555555555555555555555555555555555555555555555555555555
    elif [ "$MUSEECHO_FAKE_DOCKER_MODE" = classic-current ]; then
      echo "$MUSEECHO_EXPECTED_APP_CONFIG_ID"
    else
      echo "$MUSEECHO_EXPECTED_APP_DAEMON_ID"
    fi
    exit 0 ;;
  *"image inspect"*"museecho-gateway:local"*)
    if [ "$MUSEECHO_FAKE_DOCKER_MODE" = classic-current ]; then echo "$MUSEECHO_EXPECTED_GATEWAY_CONFIG_ID"; else echo "$MUSEECHO_EXPECTED_GATEWAY_DAEMON_ID"; fi
    exit 0 ;;
  *"container inspect"*"app-container"*)
    if [ "$MUSEECHO_FAKE_DOCKER_MODE" = runtime-drift ]; then
      echo sha256:6666666666666666666666666666666666666666666666666666666666666666
    elif [ "$MUSEECHO_FAKE_DOCKER_MODE" = classic-current ]; then
      echo "$MUSEECHO_EXPECTED_APP_CONFIG_ID"
    else
      echo "$MUSEECHO_EXPECTED_APP_DAEMON_ID"
    fi
    exit 0 ;;
  *"container inspect"*"gateway-container"*)
    if [ "$MUSEECHO_FAKE_DOCKER_MODE" = classic-current ]; then echo "$MUSEECHO_EXPECTED_GATEWAY_CONFIG_ID"; else echo "$MUSEECHO_EXPECTED_GATEWAY_DAEMON_ID"; fi
    exit 0 ;;
  *" config --format json"*) echo '{"services":{"app":{"image":"museecho-app:local"},"gateway":{"image":"museecho-gateway:local"}}}'; exit 0 ;;
  *" config --quiet"*) exit 0 ;;
  *" ps --quiet app"*) echo app-container; exit 0 ;;
  *" ps --quiet gateway"*) echo gateway-container; exit 0 ;;
  *" up "*|*" restart "*|*" exec "*|*" down "*) exit 0 ;;
  history*) echo safe-history; exit 0 ;;
esac
exit 99
'@
    }
    $fakeCurlContents = if ($isWindowsPlatform) {
        @'
@echo off
set OUT=
:args
if "%~1"=="" goto write
if "%~1"=="--output" set OUT=%~2
shift
goto args
:write
echo %OUT%| findstr /c:"health.json" >nul && echo {"status":"ready"}>"%OUT%" && exit /b 0
echo %OUT%| findstr /c:"create.json" >nul && echo {"analysis_id":"00000000-0000-0000-0000-000000000001"}>"%OUT%" && exit /b 0
echo %OUT%| findstr /c:"status.json" >nul && echo {"stage":"complete"}>"%OUT%" && exit /b 0
exit /b 0
'@
    } else {
        @'
#!/bin/sh
output=''
while [ "$#" -gt 0 ]; do
  if [ "$1" = --output ]; then output="$2"; shift 2; else shift; fi
done
case "$output" in
  *health.json) echo '{"status":"ready"}' > "$output" ;;
  *create.json) echo '{"analysis_id":"00000000-0000-0000-0000-000000000001"}' > "$output" ;;
  *status.json) echo '{"stage":"complete"}' > "$output" ;;
esac
exit 0
'@
    }
    [System.IO.File]::WriteAllText($fakeDocker, $fakeDockerContents, [Text.UTF8Encoding]::new($false))
    [System.IO.File]::WriteAllText($fakeCurl, $fakeCurlContents, [Text.UTF8Encoding]::new($false))
    if (-not $isWindowsPlatform) {
        & chmod 700 $fakeDocker
        if ($LASTEXITCODE -ne 0) { throw 'could not make fake Docker executable' }
        & chmod 700 $fakeCurl
        if ($LASTEXITCODE -ne 0) { throw 'could not make fake curl executable' }
    }
    $env:MUSEECHO_FAKE_DOCKER_LOG = $dockerLog
    $env:MUSEECHO_EXPECTED_APP_DAEMON_ID = $appDaemonId
    $env:MUSEECHO_EXPECTED_GATEWAY_DAEMON_ID = $gatewayDaemonId
    $env:MUSEECHO_EXPECTED_APP_CONFIG_ID = $appConfigId
    $env:MUSEECHO_EXPECTED_GATEWAY_CONFIG_ID = $gatewayConfigId
    $env:PATH = "$fakeBin$([IO.Path]::PathSeparator)$savedPath"

    function Invoke-OfflineNoBuild {
        param(
            [string]$Mode = 'success',
            [string]$Manifest = $releaseManifest,
            [string]$ExpectedAppDaemon = $appDaemonId,
            [string]$ExpectedAppConfig = $appConfigId,
            [string]$ExpectedGatewayDaemon = $gatewayDaemonId,
            [string]$ExpectedGatewayConfig = $gatewayConfigId
        )
        [System.IO.File]::WriteAllText($dockerLog, '', [Text.UTF8Encoding]::new($false))
        $env:MUSEECHO_FAKE_DOCKER_MODE = $Mode
        $savedErrorPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $output = & $shell -NoProfile -ExecutionPolicy Bypass `
                -File (Join-Path $offlineScripts 'container-smoke.ps1') `
                -TaskTempParent $offlineTempParent -NoBuild `
                -DockerCommand $fakeDocker -CurlCommand $fakeCurl `
                -ReleaseManifest $Manifest `
                -ExpectedAppDaemonImageId $ExpectedAppDaemon `
                -ExpectedAppConfigImageId $ExpectedAppConfig `
                -ExpectedGatewayDaemonImageId $ExpectedGatewayDaemon `
                -ExpectedGatewayConfigImageId $ExpectedGatewayConfig 2>&1 | Out-String
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $savedErrorPreference
        }
        return [pscustomobject]@{
            ExitCode = $exitCode
            Output = $output
            DockerLog = if (Test-Path -LiteralPath $dockerLog) {
                Get-Content -Raw -LiteralPath $dockerLog
            } else { '' }
        }
    }

    function Invoke-CurrentReleaseNoBuild {
        param(
            [Parameter(Mandatory = $true)][string]$Manifest,
            [string]$Mode = 'success'
        )
        [System.IO.File]::WriteAllText($dockerLog, '', [Text.UTF8Encoding]::new($false))
        $env:MUSEECHO_FAKE_DOCKER_MODE = $Mode
        $savedErrorPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $output = & $shell -NoProfile -ExecutionPolicy Bypass `
                -File (Join-Path $offlineScripts 'container-smoke.ps1') `
                -TaskTempParent $offlineTempParent -NoBuild `
                -DockerCommand $fakeDocker -CurlCommand $fakeCurl `
                -ReleaseManifest $Manifest 2>&1 | Out-String
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $savedErrorPreference
        }
        return [pscustomobject]@{
            ExitCode = $exitCode
            Output = $output
            DockerLog = if (Test-Path -LiteralPath $dockerLog) {
                Get-Content -Raw -LiteralPath $dockerLog
            } else { '' }
        }
    }

    $offline = Invoke-OfflineNoBuild
    if ($offline.ExitCode -ne 0) {
        throw "trusted no-build smoke contract failed`n$($offline.Output)`n$($offline.DockerLog)"
    }
    if ($offline.DockerLog -match '(?m)^compose .* build(?: |$)') {
        throw "no-build smoke invoked docker compose build`n$($offline.DockerLog)"
    }
    $upLines = @($offline.DockerLog -split "`r?`n" | Where-Object { $_ -match '^compose .* up ' })
    if ($upLines.Count -ne 2 -or @($upLines | Where-Object { $_ -notmatch '--no-build' }).Count) {
        throw "every no-build start must use compose up --no-build`n$($offline.DockerLog)"
    }
    if ([regex]::Matches($offline.DockerLog, '(?m)^container inspect ').Count -ne 4) {
        throw "no-build smoke did not verify both running identities after both starts`n$($offline.DockerLog)"
    }

    $currentReleaseManifest = Join-Path $fixtureRoot 'current-release-images.json'
    [System.IO.File]::WriteAllText(
        $currentReleaseManifest,
        ([ordered]@{
            schema_version = 1
            images = [ordered]@{
                app = [ordered]@{
                    image_id = $appConfigId
                    manifest_digest = $appDaemonId
                    tar_sha256 = ('a' * 64)
                }
                gateway = [ordered]@{
                    image_id = $gatewayConfigId
                    manifest_digest = $gatewayDaemonId
                    tar_sha256 = ('b' * 64)
                }
            }
        } | ConvertTo-Json -Depth 4),
        [Text.UTF8Encoding]::new($false)
    )
    $currentRelease = Invoke-CurrentReleaseNoBuild -Manifest $currentReleaseManifest
    if ($currentRelease.ExitCode -ne 0) {
        throw "current release identity no-build smoke failed`n$($currentRelease.Output)"
    }
    if ($currentRelease.DockerLog -match '(?m)^compose .* build(?: |$)') {
        throw "current release identity smoke invoked a build`n$($currentRelease.DockerLog)"
    }

    $classicCurrent = Invoke-CurrentReleaseNoBuild `
        -Manifest $currentReleaseManifest -Mode 'classic-current'
    if ($classicCurrent.ExitCode -ne 0) {
        throw "current release identity rejected classic Docker config identity`n$($classicCurrent.Output)"
    }

    $legacyCurrentManifest = Join-Path $fixtureRoot 'current-release-images-without-oci.json'
    $legacyCurrentValue = Get-Content -Raw -LiteralPath $currentReleaseManifest | ConvertFrom-Json
    $legacyCurrentValue.images.app.PSObject.Properties.Remove('manifest_digest')
    $legacyCurrentValue.images.gateway.PSObject.Properties.Remove('manifest_digest')
    [System.IO.File]::WriteAllText(
        $legacyCurrentManifest,
        (($legacyCurrentValue | ConvertTo-Json -Depth 4) + "`n"),
        [Text.UTF8Encoding]::new($false)
    )
    $legacyCurrent = Invoke-CurrentReleaseNoBuild `
        -Manifest $legacyCurrentManifest -Mode 'classic-current'
    if ($legacyCurrent.ExitCode -ne 0) {
        throw "current release smoke rejected manifest without OCI digests`n$($legacyCurrent.Output)"
    }

    foreach ($collision in @(
        [pscustomobject]@{ Label = 'cross-service config/manifest'; From = $gatewayDaemonId; To = $appConfigId },
        [pscustomobject]@{ Label = 'duplicate manifest'; From = $gatewayDaemonId; To = $appDaemonId }
    )) {
        $collisionManifest = Join-Path $fixtureRoot "$($collision.Label.Replace('/', '-').Replace(' ', '-')).json"
        [System.IO.File]::WriteAllText(
            $collisionManifest,
            ((Get-Content -Raw -LiteralPath $currentReleaseManifest).Replace(
                $collision.From,
                $collision.To
            )),
            [Text.UTF8Encoding]::new($false)
        )
        $collisionResult = Invoke-CurrentReleaseNoBuild -Manifest $collisionManifest
        if (
            $collisionResult.ExitCode -eq 0 -or
            $collisionResult.Output -notmatch 'must not share image identities'
        ) {
            throw "current release accepted $($collision.Label) collision`n$($collisionResult.Output)"
        }
        if ($collisionResult.DockerLog -match '(?m)^compose .* up ') {
            throw "current release $($collision.Label) collision reached Compose up"
        }
    }

    $malformedCurrentManifest = Join-Path $fixtureRoot 'malformed-release-images.json'
    [System.IO.File]::WriteAllText(
        $malformedCurrentManifest,
        ((Get-Content -Raw -LiteralPath $currentReleaseManifest).Replace($appConfigId, 'not-an-image-id')),
        [Text.UTF8Encoding]::new($false)
    )
    $malformedCurrent = Invoke-CurrentReleaseNoBuild -Manifest $malformedCurrentManifest
    if (
        $malformedCurrent.ExitCode -eq 0 -or
        $malformedCurrent.Output -notmatch 'app release image id'
    ) {
        throw "current release smoke accepted a malformed image identity`n$($malformedCurrent.Output)"
    }
    if ($malformedCurrent.DockerLog -match '(?m)^compose .* up ') {
        throw "malformed current release identity reached Compose up`n$($malformedCurrent.DockerLog)"
    }

    $wrongTag = Invoke-OfflineNoBuild -Mode 'wrong-app-tag'
    if ($wrongTag.ExitCode -eq 0 -or $wrongTag.Output -notmatch 'app daemon image identity mismatch') {
        throw "no-build smoke accepted the wrong app tag identity`n$($wrongTag.Output)"
    }
    $swapped = Invoke-OfflineNoBuild `
        -ExpectedAppDaemon $gatewayDaemonId -ExpectedAppConfig $gatewayConfigId `
        -ExpectedGatewayDaemon $appDaemonId -ExpectedGatewayConfig $appConfigId
    if ($swapped.ExitCode -eq 0 -or $swapped.Output -notmatch 'trusted release identity mismatch') {
        throw "no-build smoke accepted swapped app/gateway identities`n$($swapped.Output)"
    }
    $duplicateManifest = Join-Path $fixtureRoot 'duplicate-release.json'
    [System.IO.File]::WriteAllText(
        $duplicateManifest,
        ((Get-Content -Raw -LiteralPath $releaseManifest).Replace($gatewayDaemonId, $appDaemonId)),
        [Text.UTF8Encoding]::new($false)
    )
    $duplicate = Invoke-OfflineNoBuild `
        -Manifest $duplicateManifest -ExpectedGatewayDaemon $appDaemonId
    if ($duplicate.ExitCode -eq 0 -or $duplicate.Output -notmatch 'must not share image identities') {
        throw "no-build smoke accepted duplicate app/gateway identities`n$($duplicate.Output)"
    }
    $runtimeDrift = Invoke-OfflineNoBuild -Mode 'runtime-drift'
    if ($runtimeDrift.ExitCode -eq 0 -or $runtimeDrift.Output -notmatch 'running app image identity mismatch') {
        throw "no-build smoke accepted runtime image drift`n$($runtimeDrift.Output)"
    }

    Write-Host 'Container contract synthetic tests passed.'
    $global:LASTEXITCODE = 0
} finally {
    $env:PATH = $savedPath
    $env:MUSEECHO_FAKE_DOCKER_LOG = $savedDockerLog
    $env:MUSEECHO_FAKE_DOCKER_MODE = $savedDockerMode
    $env:MUSEECHO_EXPECTED_APP_DAEMON_ID = $savedAppDaemonId
    $env:MUSEECHO_EXPECTED_GATEWAY_DAEMON_ID = $savedGatewayDaemonId
    $env:MUSEECHO_EXPECTED_APP_CONFIG_ID = $savedAppConfigId
    $env:MUSEECHO_EXPECTED_GATEWAY_CONFIG_ID = $savedGatewayConfigId
    $env:MUSEECHO_SECRETS_DIR = $savedSecretsDirectory
    Pop-Location
    if (Test-Path -LiteralPath $fixtureRoot) {
        [System.IO.Directory]::Delete($fixtureRoot, $true)
    }
}

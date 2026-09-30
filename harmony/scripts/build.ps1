[CmdletBinding()]
param(
    [string]$StudioPath = 'C:\Program Files\Huawei\DevEco Studio',
    [string]$TemporaryServiceOrigin = ''
)
$ErrorActionPreference = 'Stop'
$projectSource = Split-Path -Parent $PSScriptRoot
$node = Join-Path $StudioPath 'tools\node\node.exe'
$ohpm = Join-Path $StudioPath 'tools\ohpm\bin\pm-cli.js'
$hvigor = Join-Path $StudioPath 'tools\hvigor\bin\hvigorw.js'
foreach ($tool in @($node, $ohpm, $hvigor)) {
    if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) { throw "Missing tool: $tool" }
}
# Official project tooling rejects Chinese paths. Build an isolated snapshot in an
# ASCII temp directory. Never delete, mirror, or overwrite another work directory.
$buildId = 'MuseEchoHarmony-' + [guid]::NewGuid().ToString('N')
$buildRoot = Join-Path ([IO.Path]::GetTempPath()) $buildId
if ($buildRoot -match '[^\x00-\x7F]') { throw 'An ASCII temporary directory is required.' }
New-Item -ItemType Directory -Path $buildRoot | Out-Null
$excluded = '(^|[\\/])(\.git|\.hvigor|\.idea|oh_modules|node_modules|build|artifacts)([\\/]|$)'
Get-ChildItem -LiteralPath $projectSource -Recurse -File -Force | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($projectSource, $_.FullName)
    if ($relative -notmatch $excluded -and $_.Name -ne 'local.properties' -and
        $_.Extension -notin @('.p12', '.p7b', '.cer', '.csr', '.jks')) {
        $destination = Join-Path $buildRoot $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination
    }
}
if ($TemporaryServiceOrigin -ne '') {
    if ($TemporaryServiceOrigin -cnotmatch '^https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com$') {
        throw 'TemporaryServiceOrigin must be an exact Cloudflare Quick Tunnel HTTPS origin.'
    }
    $configPath = Join-Path $buildRoot 'entry\src\main\ets\config\ServiceConfig.ets'
    $config = [IO.File]::ReadAllText($configPath)
    $settingPattern = "export const SERVICE_ORIGIN: string = '[^']*';"
    if ([regex]::Matches($config, $settingPattern).Count -ne 1) {
        throw 'Expected exactly one ServiceConfig SERVICE_ORIGIN setting.'
    }
    $configuredSetting = "export const SERVICE_ORIGIN: string = '$TemporaryServiceOrigin';"
    [IO.File]::WriteAllText($configPath, [regex]::Replace($config, $settingPattern, $configuredSetting))
}
$artifactRoot = Join-Path $projectSource "artifacts\$buildId"
New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null
Get-ChildItem -LiteralPath $buildRoot -Recurse -File | ForEach-Object {
    [pscustomobject]@{
        Path = [IO.Path]::GetRelativePath($buildRoot, $_.FullName)
        SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
} | ConvertTo-Json | Out-File (Join-Path $artifactRoot 'source-hashes.json') -Encoding utf8
$previousSdk = $env:DEVECO_SDK_HOME
$previousJava = $env:JAVA_HOME
$previousPath = $env:PATH
try {
    $env:DEVECO_SDK_HOME = Join-Path $StudioPath 'sdk'
    $env:JAVA_HOME = Join-Path $StudioPath 'jbr'
    $env:PATH = "$(Join-Path $StudioPath 'tools\node');$(Join-Path $StudioPath 'jbr\bin');$previousPath"
    Push-Location $buildRoot
    try {
        Write-Output "Build snapshot: $buildRoot"
        & $node $ohpm install --all 2>&1 | Tee-Object -FilePath (Join-Path $artifactRoot 'dependencies.log')
        if ($LASTEXITCODE -ne 0) { throw "OHPM failed: $LASTEXITCODE" }
        & $node $hvigor --mode module -p product=default -p module=entry@default -p buildMode=debug assembleHap --no-daemon 2>&1 |
            Tee-Object -FilePath (Join-Path $artifactRoot 'build.log')
        if ($LASTEXITCODE -ne 0) { throw "Hvigor failed: $LASTEXITCODE" }
        $packages = @(Get-ChildItem -LiteralPath (Join-Path $buildRoot 'entry\build') -Recurse -File -Filter '*.hap')
        if ($packages.Count -eq 0) { throw 'Build returned no HAP.' }
        foreach ($package in $packages) {
            Copy-Item -LiteralPath $package.FullName -Destination (Join-Path $artifactRoot $package.Name)
        }
        $copiedPackages = @(Get-ChildItem -LiteralPath $artifactRoot -File -Filter '*.hap')
        Get-FileHash -LiteralPath $copiedPackages.FullName -Algorithm SHA256 |
            Select-Object Hash, Path | ConvertTo-Json | Out-File (Join-Path $artifactRoot 'hashes.json') -Encoding utf8
        Write-Output "Artifacts: $artifactRoot"
        Write-Output 'Unsigned development build only; not a signed release or device verification.'
    } finally { Pop-Location }
} finally {
    $env:DEVECO_SDK_HOME = $previousSdk
    $env:JAVA_HOME = $previousJava
    $env:PATH = $previousPath
}

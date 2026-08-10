[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$savedSecretsDirectory = $env:MUSEECHO_SECRETS_DIR
$taskTempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$fixtureRoot = Join-Path $taskTempParent "museecho-container-contract-test-$PID-$([System.IO.Path]::GetRandomFileName())"
$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell.exe' }

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

    Write-Host 'Container contract synthetic tests passed.'
} finally {
    $env:MUSEECHO_SECRETS_DIR = $savedSecretsDirectory
    Pop-Location
    if (Test-Path -LiteralPath $fixtureRoot) {
        [System.IO.Directory]::Delete($fixtureRoot, $true)
    }
}

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$taskTempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$fixtureRoot = Join-Path $taskTempParent "museecho-development-smoke-$PID-$([Guid]::NewGuid().ToString('N'))"
$fixtureRoot = [System.IO.Path]::GetFullPath($fixtureRoot)
if (-not $fixtureRoot.StartsWith($taskTempParent, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'invalid development smoke task-temp path'
}
$projectName = "museecho-dev-smoke-$PID-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$savedSecretsDirectory = $env:MUSEECHO_SECRETS_DIR
$started = $false

Push-Location $repositoryRoot
try {
    New-Item -ItemType Directory -Path $fixtureRoot | Out-Null
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secretPath = Join-Path $fixtureRoot 'audio-kek'
    [IO.File]::WriteAllText($secretPath, [Convert]::ToBase64String($bytes))
    Set-ItemProperty $secretPath -Name IsReadOnly -Value $true
    $env:MUSEECHO_SECRETS_DIR = $fixtureRoot

    & docker compose --project-name $projectName --profile development up `
        --build --detach --wait app-dev gateway-dev
    if ($LASTEXITCODE -ne 0) { throw 'documented HTTPS development profile failed to start' }
    $started = $true

    $curlCommand = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curlCommand) { $curlCommand = Get-Command curl -ErrorAction Stop }
    $health = & $curlCommand.Source --fail --silent --show-error --insecure `
        https://localhost:4173/api/health
    if ($LASTEXITCODE -ne 0 -or ($health | Out-String) -notmatch '"status":"ready"') {
        throw "development HTTPS API health probe failed: $health"
    }
    $page = & $curlCommand.Source --fail --silent --show-error --insecure `
        https://localhost:4173/
    if ($LASTEXITCODE -ne 0 -or ($page | Out-String) -notmatch '<div id="root">') {
        throw 'development HTTPS same-origin frontend probe failed'
    }
    Write-Host 'Documented HTTPS same-origin development smoke passed at https://localhost:4173.'
} finally {
    if ($started) {
        $savedErrorPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & docker compose --project-name $projectName --profile development down `
                --volumes --remove-orphans 2>&1 | Out-Null
        } finally {
            $ErrorActionPreference = $savedErrorPreference
        }
    }
    $env:MUSEECHO_SECRETS_DIR = $savedSecretsDirectory
    Pop-Location
    if (Test-Path -LiteralPath $fixtureRoot) {
        Get-ChildItem -LiteralPath $fixtureRoot -Recurse -Force -ErrorAction SilentlyContinue |
            ForEach-Object { if ($_.IsReadOnly) { $_.IsReadOnly = $false } }
        [System.IO.Directory]::Delete($fixtureRoot, $true)
    }
}

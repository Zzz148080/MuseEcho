[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$scannerPath = Join-Path $PSScriptRoot 'secret-scan.ps1'
$taskTempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$fixtureRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $taskTempParent "museecho-secret-scan-test-$PID-$([System.IO.Path]::GetRandomFileName())")
)
if (-not $fixtureRoot.StartsWith($taskTempParent, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'invalid Secret scan test task-temp path'
}

$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell.exe' }

function Invoke-Scanner {
    param([Parameter(Mandatory = $true)][int]$ExpectedExit)
    $savedErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $shell -NoProfile -ExecutionPolicy Bypass -File $scannerPath `
            -RepositoryRoot $fixtureRoot 2>&1 | Out-String
        $actualExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorPreference
    }
    if ($actualExit -ne $ExpectedExit) {
        throw "Secret scan expected exit $ExpectedExit, got $actualExit`n$output"
    }
    return $output
}

try {
    New-Item -ItemType Directory -Path $fixtureRoot | Out-Null
    & git -C $fixtureRoot init --quiet
    if ($LASTEXITCODE -ne 0) { throw 'synthetic git init failed' }
    & git -C $fixtureRoot config core.autocrlf false
    if ($LASTEXITCODE -ne 0) { throw 'synthetic git config failed' }

    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot 'README.md'),
        'sha256 = 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
        [System.Text.Encoding]::UTF8
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot 'package-lock.json'),
        '{"integrity":"sha512-0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"}',
        [System.Text.Encoding]::UTF8
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot '.env.example'),
        "OPENAI_API_KEY=<set-outside-repository>`nTOKEN=`${TOKEN_FROM_SECRET_STORE}",
        [System.Text.Encoding]::UTF8
    )
    & git -C $fixtureRoot add README.md package-lock.json .env.example
    if ($LASTEXITCODE -ne 0) { throw 'synthetic safe fixture git add failed' }
    Invoke-Scanner -ExpectedExit 0 | Out-Null

    $providerToken = 'sk-' + 'proj-' + 'Q7mN2vX9cR4tY8pL6wK3sH5dF1aB0uE2'
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot 'untracked-leak.txt'),
        "api_key = `"$providerToken`"",
        [System.Text.Encoding]::UTF8
    )
    $leakOutput = Invoke-Scanner -ExpectedExit 1
    if ($leakOutput -notmatch 'openai|high-entropy') {
        throw "Secret scan did not identify the synthetic provider credential`n$leakOutput"
    }
    [System.IO.File]::Delete((Join-Path $fixtureRoot 'untracked-leak.txt'))

    $missingPath = Join-Path $fixtureRoot 'tracked-then-missing.txt'
    [System.IO.File]::WriteAllText($missingPath, 'safe', [System.Text.Encoding]::UTF8)
    & git -C $fixtureRoot add tracked-then-missing.txt
    if ($LASTEXITCODE -ne 0) { throw 'synthetic missing fixture git add failed' }
    [System.IO.File]::Delete($missingPath)
    $missingOutput = Invoke-Scanner -ExpectedExit 1
    if ($missingOutput -notmatch 'scan-error') {
        throw "Secret scan did not fail closed for a listed missing file`n$missingOutput"
    }

    Write-Host 'Secret scan synthetic tests passed.'
} finally {
    if (Test-Path -LiteralPath $fixtureRoot) {
        Get-ChildItem -LiteralPath $fixtureRoot -Recurse -Force -ErrorAction SilentlyContinue |
            ForEach-Object { if ($_.IsReadOnly) { $_.IsReadOnly = $false } }
        [System.IO.Directory]::Delete($fixtureRoot, $true)
    }
}

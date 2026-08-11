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

    $fineGrainedToken = 'github_pat_' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4P5q6R7s8T9u0V1w2X3y4Z5'
    $fineGrainedPath = Join-Path $fixtureRoot 'fine-grained-token.txt'
    [System.IO.File]::WriteAllText(
        $fineGrainedPath,
        $fineGrainedToken,
        [System.Text.Encoding]::UTF8
    )
    $fineGrainedOutput = Invoke-Scanner -ExpectedExit 1
    if ($fineGrainedOutput -notmatch 'github-token') {
        throw "Secret scan did not identify the fine-grained GitHub token`n$fineGrainedOutput"
    }
    [System.IO.File]::Delete($fineGrainedPath)

    $hexCredentialPath = Join-Path $fixtureRoot 'hex-credential.txt'
    $hexValue = '0f4a9c7e2b6d1a8f3c5e9b0d7a4f2c8e' +
        '6b1d9a5f3e7c0b4d8a2f6c1e9b5d3a7f'
    [System.IO.File]::WriteAllText(
        $hexCredentialPath,
        "password = `"$hexValue`"",
        [System.Text.Encoding]::UTF8
    )
    $hexOutput = Invoke-Scanner -ExpectedExit 1
    if ($hexOutput -notmatch 'high-entropy credential') {
        throw "Secret scan did not identify the explicit hex credential`n$hexOutput"
    }
    [System.IO.File]::Delete($hexCredentialPath)

    $lowercaseCredentialPath = Join-Path $fixtureRoot 'lowercase-credential.txt'
    $lowercaseValue = 'qwertyuiopasdfghjklzxcvbnm' + 'qazwsxedcrfvtgbyhnujmikolp'
    [System.IO.File]::WriteAllText(
        $lowercaseCredentialPath,
        "access_token = `"$lowercaseValue`"",
        [System.Text.Encoding]::UTF8
    )
    $lowercaseOutput = Invoke-Scanner -ExpectedExit 1
    if ($lowercaseOutput -notmatch 'high-entropy credential') {
        throw "Secret scan did not identify the explicit lowercase credential`n$lowercaseOutput"
    }
    [System.IO.File]::Delete($lowercaseCredentialPath)

    $unreadablePath = Join-Path $fixtureRoot 'tracked-unreadable.txt'
    [System.IO.File]::WriteAllText($unreadablePath, 'safe', [System.Text.Encoding]::UTF8)
    & git -C $fixtureRoot add tracked-unreadable.txt
    if ($LASTEXITCODE -ne 0) { throw 'synthetic unreadable fixture git add failed' }
    $lockedStream = [System.IO.File]::Open(
        $unreadablePath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    try {
        $unreadableOutput = Invoke-Scanner -ExpectedExit 1
        if (
            $unreadableOutput -notmatch 'scan-error' -or
            $unreadableOutput -notmatch 'tracked-unrea'
        ) {
            throw "Secret scan did not fail closed for an unreadable file`n$unreadableOutput"
        }
    } finally {
        $lockedStream.Dispose()
    }

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

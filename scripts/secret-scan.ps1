[CmdletBinding()]
param(
    [string]$RepositoryRoot = '',
    [switch]$RequireFrontendDist
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = Split-Path -Parent $PSScriptRoot
}
$repositoryRoot = [System.IO.Path]::GetFullPath($RepositoryRoot)
$findings = New-Object System.Collections.Generic.List[string]
$patterns = @(
    @{ Name = 'private-key'; Regex = '-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----' },
    @{ Name = 'github-token'; Regex = '\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b' },
    @{ Name = 'openai-key'; Regex = '\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b' },
    @{ Name = 'aws-access-key'; Regex = '\b(?:AKIA|ASIA)[0-9A-Z]{16}\b' },
    @{ Name = 'google-api-key'; Regex = '\bAIza[0-9A-Za-z_-]{35}\b' },
    @{ Name = 'stripe-live-key'; Regex = '\bsk_live_[0-9A-Za-z]{16,}\b' },
    @{ Name = 'slack-token'; Regex = '\bxox[baprs]-[0-9A-Za-z-]{20,}\b' }
)
$assignmentPattern = '(?im)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|secret)\b\s*[:=]\s*["''`]?([A-Za-z0-9+/_=-]{24,})'
$forbiddenPaths = @(
    '(^|/)\.env($|\.)',
    '(^|/)secrets?/',
    '\.(?:pem|p12|pfx|key)$'
)

function Get-ShannonEntropy {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ($Value.Length -eq 0) { return 0.0 }
    $counts = @{}
    foreach ($character in $Value.ToCharArray()) {
        $key = [string]$character
        $counts[$key] = 1 + [int]($counts[$key])
    }
    $entropy = 0.0
    foreach ($count in $counts.Values) {
        $probability = [double]$count / $Value.Length
        $entropy -= $probability * [Math]::Log($probability, 2)
    }
    return $entropy
}

function Test-HighEntropyCredential {
    param([Parameter(Mandatory = $true)][string]$Value)
    $lower = $Value.ToLowerInvariant()
    if (
        $lower.Contains('example') -or
        $lower.Contains('placeholder') -or
        $lower.Contains('changeme') -or
        $Value -match '^(?:x+|0+|1+|a+)$'
    ) {
        return $false
    }
    $entropy = Get-ShannonEntropy -Value $Value
    if ($Value -cmatch '^[0-9a-f]{32,}$') {
        return $entropy -ge 3.5
    }
    if ($Value -cmatch '^[a-z0-9]{32,}$') {
        return $entropy -ge 4.0
    }
    $classes = 0
    if ($Value -cmatch '[a-z]') { $classes++ }
    if ($Value -cmatch '[A-Z]') { $classes++ }
    if ($Value -match '[0-9]') { $classes++ }
    if ($Value -match '[+/_=-]') { $classes++ }
    return $classes -ge 3 -and $entropy -ge 4.0
}

function Test-FileContent {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$DisplayPath
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        $findings.Add("scan-error: missing tracked or untracked file: $DisplayPath")
        return
    }
    try {
        $content = Get-Content -Raw -LiteralPath $Path -ErrorAction Stop
    } catch {
        $findings.Add("scan-error: unreadable file: $DisplayPath ($($_.Exception.Message))")
        return
    }
    if ($null -eq $content) { $content = '' }
    foreach ($pattern in $patterns) {
        if ($content -match $pattern.Regex) {
            $findings.Add("$($pattern.Name) pattern: $DisplayPath")
        }
    }
    foreach ($match in [regex]::Matches($content, $assignmentPattern)) {
        $candidate = $match.Groups[1].Value
        if (Test-HighEntropyCredential -Value $candidate) {
            $findings.Add("high-entropy credential assignment: $DisplayPath")
        }
    }
}

Push-Location $repositoryRoot
try {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $candidateFiles = @(
            & git -c "safe.directory=$repositoryRoot" -c core.quotepath=false `
                ls-files --cached --others --exclude-standard
        )
        if ($LASTEXITCODE -ne 0) { throw 'git ls-files failed' }
    } else {
        $candidateFiles = @(
            Get-ChildItem -LiteralPath $repositoryRoot -Recurse -File -Force |
                Where-Object { $_.FullName -notmatch '[\\/]\.git[\\/]' } |
                ForEach-Object {
                    $_.FullName.Substring($repositoryRoot.Length).TrimStart('\', '/')
                }
        )
    }
    $candidateFiles = @($candidateFiles | Where-Object { $_ })
    foreach ($relativePath in $candidateFiles) {
        $normalized = $relativePath -replace '\\', '/'
        foreach ($pathPattern in $forbiddenPaths) {
            if ($normalized -match $pathPattern -and $normalized -ne '.env.example') {
                $findings.Add("forbidden credential path: $normalized")
            }
        }
        Test-FileContent -Path (Join-Path $repositoryRoot $relativePath) -DisplayPath $normalized
    }

    $frontendDist = Join-Path $repositoryRoot 'frontend\dist'
    if (-not (Test-Path -LiteralPath $frontendDist -PathType Container)) {
        if ($RequireFrontendDist) {
            $findings.Add('scan-error: required release bundle is missing: frontend/dist')
        }
    } else {
        foreach ($asset in Get-ChildItem -LiteralPath $frontendDist -Recurse -File) {
            $relativeAsset = $asset.FullName.Substring($repositoryRoot.Length).TrimStart('\', '/')
            Test-FileContent -Path $asset.FullName -DisplayPath ($relativeAsset -replace '\\', '/')
        }
    }
} finally {
    Pop-Location
}

if ($findings.Count -gt 0) {
    $findings | Sort-Object -Unique | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "Secret scan passed: $($candidateFiles.Count) tracked/non-ignored files checked."

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$findings = New-Object System.Collections.Generic.List[string]
$patterns = @(
    @{ Name = 'private-key'; Regex = '-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----' },
    @{ Name = 'github-token'; Regex = 'gh[pousr]_[A-Za-z0-9]{30,}' },
    @{ Name = 'openai-style-key'; Regex = 'sk-[A-Za-z0-9_-]{20,}' },
    @{ Name = 'aws-access-key'; Regex = 'AKIA[0-9A-Z]{16}' }
)
$forbiddenPaths = @(
    '(^|/)\.env($|\.)',
    '(^|/)secrets?/',
    '\.(?:pem|p12|pfx|key)$'
)

Push-Location $repositoryRoot
try {
    $trackedFiles = @(& git -c "safe.directory=$repositoryRoot" ls-files)
    if ($LASTEXITCODE -ne 0) { throw 'git ls-files failed' }
    foreach ($relativePath in $trackedFiles) {
        $normalized = $relativePath -replace '\\', '/'
        if ($normalized -eq '.env.example') { continue }
        foreach ($pathPattern in $forbiddenPaths) {
            if ($normalized -match $pathPattern) {
                $findings.Add("forbidden credential path: $normalized")
            }
        }
        $candidate = Join-Path $repositoryRoot $relativePath
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        try {
            $content = Get-Content -Raw -LiteralPath $candidate -ErrorAction Stop
        } catch {
            continue
        }
        foreach ($pattern in $patterns) {
            if ($content -match $pattern.Regex) {
                $findings.Add("$($pattern.Name) pattern: $normalized")
            }
        }
    }

    $frontendDist = Join-Path $repositoryRoot 'frontend\dist'
    if (Test-Path -LiteralPath $frontendDist -PathType Container) {
        foreach ($asset in Get-ChildItem -LiteralPath $frontendDist -Recurse -File) {
            $content = Get-Content -Raw -LiteralPath $asset.FullName -ErrorAction SilentlyContinue
            foreach ($pattern in $patterns) {
                if ($content -and $content -match $pattern.Regex) {
                    $findings.Add("$($pattern.Name) in frontend build: $($asset.Name)")
                }
            }
        }
    }
} finally {
    Pop-Location
}

if ($findings.Count -gt 0) {
    $findings | Sort-Object -Unique | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "Secret scan passed: $($trackedFiles.Count) tracked files checked."

[CmdletBinding()]
param(
    [string]$OutputRoot = 'release\competition-submission',
    [string]$AppPackagePath = '',
    [string]$AndroidPackagePath = '',
    [string]$VideoDirectory = ''
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$resolvedOutputRoot = if ([IO.Path]::IsPathRooted($OutputRoot)) {
    [IO.Path]::GetFullPath($OutputRoot)
} else {
    [IO.Path]::GetFullPath((Join-Path $repositoryRoot $OutputRoot))
}

$submissionId = 'MuseEcho-Submission-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$submissionRoot = Join-Path $resolvedOutputRoot $submissionId
if (Test-Path -LiteralPath $submissionRoot) {
    throw "Refusing to overwrite an existing submission: $submissionRoot"
}

$sourceOutput = Join-Path $submissionRoot 'source'
$appOutput = Join-Path $submissionRoot 'app'
$videoOutput = Join-Path $submissionRoot 'videos'
New-Item -ItemType Directory -Path $sourceOutput, $appOutput, $videoOutput | Out-Null

$includedDirectories = @(
    '.github',
    'android',
    'deploy',
    'docs',
    'e2e',
    'frontend/public',
    'frontend/src',
    'harmony',
    'migrations',
    'ml/configs',
    'ml/src',
    'ml/tests',
    'models',
    'scripts',
    'src',
    'tests'
)
$includedRootFiles = @(
    '.dockerignore',
    '.env.example',
    '.gitattributes',
    '.gitignore',
    '.gitlab-ci.yml',
    '.nvmrc',
    '.python-version',
    'alembic.ini',
    'Caddyfile',
    'compose.yaml',
    'Dockerfile',
    'frontend/index.html',
    'frontend/package.json',
    'frontend/package-lock.json',
    'frontend/tsconfig.json',
    'frontend/vite.config.ts',
    'ml/pyproject.toml',
    'ml/README.md',
    'ml/uv.lock',
    'package.json',
    'package-lock.json',
    'playwright.config.ts',
    'pyproject.toml',
    'README.md',
    'RELEASE_REPRODUCTION.md',
    'THIRD_PARTY_NOTICES.md',
    'tsconfig.e2e.json',
    'uv.lock'
)
$excludedSegments = @(
    '.git', '.hvigor', '.idea', '.mypy_cache', '.npm-cache', '.pytest_cache',
    '.ruff_cache', '.venv', '.vscode', '.worktrees', '__pycache__', 'artifacts',
    'build', 'coverage', 'data', 'dist', 'node_modules', 'oh_modules', 'outputs',
    'playwright-report', 'release', 'runs', 'secrets', 'storage', 'test-results', 'tmp'
)
$excludedExtensions = @(
    '.aab', '.apk', '.app', '.cer', '.ckpt', '.db', '.hap', '.jks', '.key', '.keystore',
    '.log', '.onnx', '.p12', '.p7b', '.pem', '.pfx', '.pt', '.pth', '.sqlite',
    '.sqlite3', '.tar', '.zip'
)

function Get-CompatibleRelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$BasePath,
        [Parameter(Mandatory = $true)][string]$TargetPath
    )

    $base = [IO.Path]::GetFullPath($BasePath).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $target = [IO.Path]::GetFullPath($TargetPath)
    $baseUri = New-Object System.Uri($base)
    $targetUri = New-Object System.Uri($target)
    return [Uri]::UnescapeDataString($baseUri.MakeRelativeUri($targetUri).ToString()).Replace(
        '/', [IO.Path]::DirectorySeparatorChar
    )
}

function Test-ExcludedSourcePath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $normalized = $RelativePath.Replace('\', '/')
    if ([IO.Path]::GetFileName($normalized) -eq 'local.properties') { return $true }
    $segments = @($normalized.Split('/') | Where-Object { $_ })
    foreach ($segment in $segments) {
        if ($segment -in $excludedSegments -or $segment -like '.pytest-*') {
            return $true
        }
    }
    if ($normalized -match '(^|/)docs/(?:evidence|audits/evidence)(/|$)') { return $true }
    if ($normalized -match '(^|/)ml/(?:cache|checkpoints|data|runs)(/|$)') { return $true }
    if ($normalized -match '(^|/)\.env($|\.)' -and $normalized -ne '.env.example') { return $true }
    return [IO.Path]::GetExtension($normalized).ToLowerInvariant() -in $excludedExtensions
}

$sourceFiles = New-Object System.Collections.Generic.List[System.IO.FileInfo]
foreach ($directory in $includedDirectories) {
    $path = Join-Path $repositoryRoot $directory
    if (-not (Test-Path -LiteralPath $path -PathType Container)) { continue }
    foreach ($file in Get-ChildItem -LiteralPath $path -Recurse -File -Force) {
        $relative = Get-CompatibleRelativePath -BasePath $repositoryRoot -TargetPath $file.FullName
        if (-not (Test-ExcludedSourcePath -RelativePath $relative)) {
            $sourceFiles.Add($file)
        }
    }
}
foreach ($name in $includedRootFiles) {
    $path = Join-Path $repositoryRoot $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required source file is missing: $name"
    }
    $sourceFiles.Add((Get-Item -LiteralPath $path))
}

$sourceFiles = @($sourceFiles | Sort-Object FullName -Unique)
$manifestEntries = @(
    foreach ($file in $sourceFiles) {
        $relative = (Get-CompatibleRelativePath -BasePath $repositoryRoot -TargetPath $file.FullName).Replace('\', '/')
        [ordered]@{
            path = $relative
            bytes = $file.Length
            sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
)

$gitBranch = (& git -C $repositoryRoot branch --show-current 2>$null)
$gitCommit = (& git -C $repositoryRoot rev-parse HEAD 2>$null)
$gitDirty = [bool](& git -C $repositoryRoot status --porcelain 2>$null)
$manifest = [ordered]@{
    schema_version = 1
    generated_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    source_root_name = 'MuseEcho-source'
    git_branch = ($gitBranch | Select-Object -First 1)
    git_commit = ($gitCommit | Select-Object -First 1)
    git_worktree_dirty = $gitDirty
    file_count = $manifestEntries.Count
    files = $manifestEntries
}
$manifestPath = Join-Path $submissionRoot 'SOURCE_MANIFEST.json'
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding utf8

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$sourceZip = Join-Path $sourceOutput 'MuseEcho-source.zip'
$archive = [IO.Compression.ZipFile]::Open(
    $sourceZip,
    [System.IO.Compression.ZipArchiveMode]::Create
)
try {
    foreach ($file in $sourceFiles) {
        $relative = (Get-CompatibleRelativePath -BasePath $repositoryRoot -TargetPath $file.FullName).Replace('\', '/')
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,
            $file.FullName,
            "MuseEcho-source/$relative",
            [IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
    [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
        $archive,
        $manifestPath,
        'MuseEcho-source/SOURCE_MANIFEST.json',
        [IO.Compression.CompressionLevel]::Optimal
    ) | Out-Null
} finally {
    $archive.Dispose()
}

if (-not [string]::IsNullOrWhiteSpace($AppPackagePath)) {
    $resolvedAppPackage = [IO.Path]::GetFullPath($AppPackagePath)
    if (-not (Test-Path -LiteralPath $resolvedAppPackage -PathType Leaf)) {
        throw "Application package does not exist: $resolvedAppPackage"
    }
    if ([IO.Path]::GetExtension($resolvedAppPackage).ToLowerInvariant() -notin @('.hap', '.app')) {
        throw 'Application package must be a .hap or .app file.'
    }
    Copy-Item -LiteralPath $resolvedAppPackage -Destination $appOutput
}

if (-not [string]::IsNullOrWhiteSpace($AndroidPackagePath)) {
    $resolvedAndroidPackage = [IO.Path]::GetFullPath($AndroidPackagePath)
    if (-not (Test-Path -LiteralPath $resolvedAndroidPackage -PathType Leaf)) {
        throw "Android package does not exist: $resolvedAndroidPackage"
    }
    if ([IO.Path]::GetExtension($resolvedAndroidPackage).ToLowerInvariant() -ne '.apk') {
        throw 'Android package must be an .apk file.'
    }
    Copy-Item -LiteralPath $resolvedAndroidPackage -Destination $appOutput
}

$installationReadme = Join-Path $repositoryRoot 'docs\submission\INSTALLATION_README.md'
if (-not (Test-Path -LiteralPath $installationReadme -PathType Leaf)) {
    throw "Installation README is missing: $installationReadme"
}
Copy-Item -LiteralPath $installationReadme -Destination (Join-Path $submissionRoot 'INSTALLATION_README.md')

if (-not [string]::IsNullOrWhiteSpace($VideoDirectory)) {
    $resolvedVideoDirectory = [IO.Path]::GetFullPath($VideoDirectory)
    if (-not (Test-Path -LiteralPath $resolvedVideoDirectory -PathType Container)) {
        throw "Video directory does not exist: $resolvedVideoDirectory"
    }
    $videos = @(Get-ChildItem -LiteralPath $resolvedVideoDirectory -File -Filter '*.mp4')
    if ($videos.Count -eq 0) { throw 'Video directory contains no MP4 files.' }
    foreach ($video in $videos) {
        Copy-Item -LiteralPath $video.FullName -Destination $videoOutput
    }
}

$deliverables = @(
    Get-ChildItem -LiteralPath $submissionRoot -Recurse -File |
        Where-Object { $_.Name -ne 'SHA256SUMS.txt' }
)
$checksumLines = @(
    foreach ($file in $deliverables | Sort-Object FullName) {
        $relative = (Get-CompatibleRelativePath -BasePath $submissionRoot -TargetPath $file.FullName).Replace('\', '/')
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $relative"
    }
)
$checksumLines | Set-Content -LiteralPath (Join-Path $submissionRoot 'SHA256SUMS.txt') -Encoding ascii

Write-Host "Submission prepared: $submissionRoot"
Write-Host "Source files: $($sourceFiles.Count)"
Write-Host "Source archive: $sourceZip"

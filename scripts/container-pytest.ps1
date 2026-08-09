[CmdletBinding()]
param(
    [string]$Image = 'museecho-app:local'
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$taskTempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$dependencyRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $taskTempParent "museecho-container-pytest-$PID-$([System.IO.Path]::GetRandomFileName())")
)
if (-not $dependencyRoot.StartsWith($taskTempParent, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'invalid container pytest task-temp path'
}
if ($dependencyRoot.StartsWith($repositoryRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'container pytest fixtures must be outside the repository'
}

$sitePackages = @(
    (Join-Path $repositoryRoot '.venv\Lib\site-packages'),
    (Join-Path $repositoryRoot '.venv/lib/python3.12/site-packages')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Container } | Select-Object -First 1
if (-not $sitePackages) {
    throw 'an existing project .venv with pytest is required; no dependency installation is performed'
}
$requiredModules = @('pytest', '_pytest', 'pluggy', 'iniconfig', 'pygments')
foreach ($module in $requiredModules) {
    if (-not (Test-Path -LiteralPath (Join-Path $sitePackages $module))) {
        throw "existing pytest module is unavailable: $module"
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $sitePackages 'py.py') -PathType Leaf)) {
    throw 'existing pytest compatibility module is unavailable: py.py'
}

$containerName = "museecho-container-pytest-$PID"
try {
    New-Item -ItemType Directory -Path $dependencyRoot | Out-Null
    foreach ($module in $requiredModules) {
        Copy-Item -LiteralPath (Join-Path $sitePackages $module) `
            -Destination (Join-Path $dependencyRoot $module) -Recurse
    }
    Copy-Item -LiteralPath (Join-Path $sitePackages 'py.py') `
        -Destination (Join-Path $dependencyRoot 'py.py')

    & docker image inspect $Image 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "required local image is unavailable: $Image" }
    & docker create --name $containerName --network none --read-only `
        --tmpfs /tmp:rw,nosuid,nodev,size=1g `
        --workdir /workspace `
        --env PYTHONPATH=/workspace/src:/testdeps `
        --mount "type=bind,source=$repositoryRoot,target=/workspace,readonly" `
        --mount "type=bind,source=$dependencyRoot,target=/testdeps,readonly" `
        --entrypoint /app/.venv/bin/python `
        $Image -m pytest -q -o cache_dir=/tmp/pytest-cache --basetemp /tmp/pytest
    if ($LASTEXITCODE -ne 0) { throw 'container pytest create failed' }
    & docker start --attach $containerName
    if ($LASTEXITCODE -ne 0) { throw "container pytest failed with exit code $LASTEXITCODE" }
} finally {
    $savedErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker rm --force $containerName 2>&1 | Out-Null
    } finally {
        $ErrorActionPreference = $savedErrorPreference
    }
    if (Test-Path -LiteralPath $dependencyRoot) {
        Get-ChildItem -LiteralPath $dependencyRoot -Recurse -Force | ForEach-Object {
            if ($_.IsReadOnly) { $_.IsReadOnly = $false }
        }
        [System.IO.Directory]::Delete($dependencyRoot, $true)
    }
}

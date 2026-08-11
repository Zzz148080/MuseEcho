[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$SkipE2E
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$existingPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = if ($existingPythonPath) {
    "$repositoryRoot$([IO.Path]::PathSeparator)$existingPythonPath"
} else {
    $repositoryRoot
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Host "==> $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit code $LASTEXITCODE" }
}

function Invoke-Uv {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv @Arguments
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m uv @Arguments
    } elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
        & python3 -m uv @Arguments
    } else {
        throw 'uv is unavailable; install uv 0.11.29 before verification'
    }
}

$npmCommand = if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { 'npm.cmd' } else { 'npm' }
$powershellCommand = if (Get-Command powershell.exe -ErrorAction SilentlyContinue) {
    'powershell.exe'
} else {
    'pwsh'
}

Push-Location $repositoryRoot
try {
    if (-not $SkipInstall) {
        Invoke-Checked 'Python locked environment' { Invoke-Uv sync --frozen --extra dev }
        Invoke-Checked 'Root Node locked environment' { & $npmCommand ci }
        Invoke-Checked 'Frontend locked environment' { & $npmCommand --prefix frontend ci }
    }
    Invoke-Checked 'uv lock' { Invoke-Uv lock --check }
    Invoke-Checked 'Ruff format' { Invoke-Uv run ruff format --check src tests }
    Invoke-Checked 'Ruff lint' { Invoke-Uv run ruff check . }
    Invoke-Checked 'mypy' { Invoke-Uv run mypy src }
    Invoke-Checked 'Backend tests' {
        $pytestRoot = "tmp/pytest-verify-$PID"
        New-Item -ItemType Directory -Force -Path $pytestRoot | Out-Null
        $pytestArguments = @(
            'run',
            'pytest',
            '-q',
            '-o',
            "cache_dir=$pytestRoot/cache",
            '--basetemp',
            "$pytestRoot/base"
        )
        Invoke-Uv @pytestArguments
    }
    Invoke-Checked 'Frontend tests' { & $npmCommand --prefix frontend test }
    Invoke-Checked 'Frontend typecheck' { & $npmCommand --prefix frontend run typecheck }
    Invoke-Checked 'Frontend build' { & $npmCommand --prefix frontend run build }
    Invoke-Checked 'E2E typecheck' { & $npmCommand run typecheck }
    if (-not $SkipE2E) {
        $venvPython = if ($IsWindows -or $env:OS -eq 'Windows_NT') {
            Join-Path $repositoryRoot '.venv\Scripts\python.exe'
        } else {
            Join-Path $repositoryRoot '.venv/bin/python'
        }
        if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
            throw 'project virtual-environment Python is unavailable for E2E'
        }
        $env:MUSEECHO_E2E_PYTHON = $venvPython
        Invoke-Checked 'HTTPS browser E2E' { & $npmCommand run e2e }
    }
    Invoke-Checked 'Dependency license policy' {
        Invoke-Uv run python scripts/license_audit.py
    }
    Invoke-Checked 'Root dependency audit' { & $npmCommand audit --audit-level=high }
    Invoke-Checked 'Frontend dependency audit' {
        & $npmCommand --prefix frontend audit --audit-level=high
    }
    Invoke-Checked 'Secret audit' {
        & $powershellCommand -NoProfile -ExecutionPolicy Bypass -File scripts/secret-scan.ps1
    }
    Invoke-Checked 'Secret audit synthetic coverage' {
        & $powershellCommand -NoProfile -ExecutionPolicy Bypass -File scripts/test-secret-scan.ps1
    }
    Invoke-Checked 'Container test-runner cleanup coverage' {
        & $powershellCommand -NoProfile -ExecutionPolicy Bypass -File scripts/test-container-pytest.ps1
    }
    Invoke-Checked 'Development smoke lifecycle coverage' {
        & $powershellCommand -NoProfile -ExecutionPolicy Bypass -File scripts/test-development-smoke.ps1
    }
    Invoke-Checked 'Container smoke no-build coverage' {
        & $powershellCommand -NoProfile -ExecutionPolicy Bypass -File scripts/test-container-contract.ps1
    }
    Invoke-Checked 'Fresh-checkout shell parse coverage' {
        & $powershellCommand -NoProfile -ExecutionPolicy Bypass `
            -File tests/deploy/test_shell_line_endings.ps1
    }
} finally {
    Pop-Location
    if ($null -eq $existingPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $existingPythonPath
    }
}

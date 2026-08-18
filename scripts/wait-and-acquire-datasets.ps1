param(
    [int]$WaitForProcessId = 0
)

$ErrorActionPreference = 'Stop'

if ($WaitForProcessId -gt 0) {
    $existing = Get-Process -Id $WaitForProcessId -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        Wait-Process -Id $WaitForProcessId
    }
}

& uv run --project ml python scripts/acquire_verified_chord_datasets.py `
    --download-root ml/data/downloads
exit $LASTEXITCODE

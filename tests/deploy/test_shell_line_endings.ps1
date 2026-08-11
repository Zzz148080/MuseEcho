$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (& git rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    throw 'Unable to locate the repository root.'
}

$shellFiles = @(& git -C $repoRoot ls-files -- '*.sh')
if ($LASTEXITCODE -ne 0 -or $shellFiles.Count -eq 0) {
    throw 'Unable to enumerate tracked shell files.'
}

$requiredTask21Files = @(
    'deploy/tencent-cloud/backup.sh'
    'deploy/tencent-cloud/deploy.sh'
    'deploy/tencent-cloud/install.sh'
    'deploy/tencent-cloud/lib.sh'
    'deploy/tencent-cloud/rollback.sh'
    'tests/deploy/test_shellcheck_evidence.sh'
    'tests/deploy/test_shellcheck_evidence_mutations.sh'
    'tests/deploy/test_tencent_cloud.sh'
)

$failures = [System.Collections.Generic.List[string]]::new()
foreach ($requiredFile in $requiredTask21Files) {
    if ($requiredFile -notin $shellFiles) {
        $failures.Add("required Task 21 shell file is not tracked: $requiredFile")
    }
}

foreach ($shellFile in $shellFiles) {
    $attribute = (& git -C $repoRoot check-attr eol -- $shellFile).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "git check-attr failed for $shellFile"
    }
    $expectedAttribute = "${shellFile}: eol: lf"
    if ($attribute -ne $expectedAttribute) {
        $failures.Add("expected '$expectedAttribute', got '$attribute'")
    }
}

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$checkoutRoot = Join-Path $tempBase ("museecho-task21-line-endings-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $checkoutRoot | Out-Null

try {
    $checkoutPrefix = $checkoutRoot.Replace([IO.Path]::DirectorySeparatorChar, '/') + '/'
    & git -C $repoRoot -c core.autocrlf=true checkout-index --all --force --prefix=$checkoutPrefix
    if ($LASTEXITCODE -ne 0) {
        throw 'git checkout-index failed.'
    }

    foreach ($shellFile in $shellFiles) {
        $checkoutFile = Join-Path $checkoutRoot $shellFile
        $bytes = [IO.File]::ReadAllBytes($checkoutFile)
        $crlfCount = 0
        for ($index = 1; $index -lt $bytes.Length; $index++) {
            if ($bytes[$index - 1] -eq 13 -and $bytes[$index] -eq 10) {
                $crlfCount++
            }
        }
        if ($crlfCount -ne 0) {
            $failures.Add("fresh checkout contains $crlfCount CRLF sequence(s): $shellFile")
        }
    }

    $mutationTarget = $shellFiles[-1]
    $mutationPath = Join-Path $checkoutRoot $mutationTarget
    $originalMutationBytes = [IO.File]::ReadAllBytes($mutationPath)
    try {
        [IO.File]::AppendAllText(
            $mutationPath,
            "`nif then`n",
            [Text.UTF8Encoding]::new($false)
        )
        Push-Location $checkoutRoot
        try {
            $mutationRejected = $false
            foreach ($shellFile in $shellFiles) {
                & bash -n -- $shellFile
                if ($LASTEXITCODE -ne 0) {
                    $mutationRejected = $true
                    break
                }
            }
            if (-not $mutationRejected) {
                $failures.Add(
                    "bash syntax harness accepted a later-file mutation: $mutationTarget"
                )
            }
        }
        finally {
            Pop-Location
        }
    }
    finally {
        [IO.File]::WriteAllBytes($mutationPath, $originalMutationBytes)
    }

    Push-Location $checkoutRoot
    try {
        foreach ($shellFile in $shellFiles) {
            & bash -n -- $shellFile
            if ($LASTEXITCODE -ne 0) {
                $failures.Add(
                    "bash -n rejected fresh-checkout file $shellFile (exit $LASTEXITCODE)"
                )
            }
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    $resolvedCheckout = [IO.Path]::GetFullPath($checkoutRoot)
    if (-not $resolvedCheckout.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing unsafe temporary cleanup path: $resolvedCheckout"
    }
    if ([IO.Directory]::Exists($resolvedCheckout)) {
        [IO.Directory]::Delete($resolvedCheckout, $true)
    }
}

if ($failures.Count -ne 0) {
    foreach ($failure in $failures) {
        [Console]::Error.WriteLine("FAIL: $failure")
    }
    throw "$($failures.Count) shell line-ending contract failure(s)."
}

Write-Output "PASS: eol=lf for $($shellFiles.Count) tracked shell files."
Write-Output 'PASS: core.autocrlf=true fresh checkout contains no CRLF shell content.'
Write-Output "PASS: bash -n independently parsed $($shellFiles.Count) fresh-checkout shell files."

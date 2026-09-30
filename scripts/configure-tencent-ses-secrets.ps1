[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'MuseEcho\secrets')
)

$ErrorActionPreference = 'Stop'

function Read-RequiredSecret {
    param([Parameter(Mandatory)][string]$Prompt)

    $secureValue = Read-Host -Prompt $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    if ([string]::IsNullOrWhiteSpace($value) -or $value.Length -gt 4096 -or $value.Contains("`n") -or $value.Contains("`r")) {
        throw 'The credential must be a non-empty single line of at most 4096 characters.'
    }
    return $value
}

$resolvedDestination = [IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Path $resolvedDestination -Force | Out-Null

$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$directoryAcl = New-Object Security.AccessControl.DirectorySecurity
$directoryAcl.SetAccessRuleProtection($true, $false)
$directoryRule = New-Object Security.AccessControl.FileSystemAccessRule(
    $identity,
    [Security.AccessControl.FileSystemRights]::FullControl,
    [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit',
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow
)
$directoryAcl.AddAccessRule($directoryRule)
Set-Acl -LiteralPath $resolvedDestination -AclObject $directoryAcl

$secretId = Read-RequiredSecret 'Tencent CAM SecretId'
$secretKey = Read-RequiredSecret 'Tencent CAM SecretKey'
$encoding = New-Object Text.UTF8Encoding($false)
$secretPaths = @(
    @{ Path = (Join-Path $resolvedDestination 'tencent-ses-secret-id'); Value = $secretId },
    @{ Path = (Join-Path $resolvedDestination 'tencent-ses-secret-key'); Value = $secretKey }
)

foreach ($secret in $secretPaths) {
    if (Test-Path -LiteralPath $secret.Path) {
        (Get-Item -LiteralPath $secret.Path).IsReadOnly = $false
    }
    [IO.File]::WriteAllText($secret.Path, $secret.Value, $encoding)
    (Get-Item -LiteralPath $secret.Path).IsReadOnly = $true
    $secret.Value = $null
}

$secretId = $null
$secretKey = $null
[GC]::Collect()

Write-Host 'Tencent SES credentials were stored outside the repository.'
Write-Host "SecretId file: $($secretPaths[0].Path)"
Write-Host "SecretKey file: $($secretPaths[1].Path)"

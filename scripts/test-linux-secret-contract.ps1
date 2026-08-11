[CmdletBinding()]
param(
    [string]$AppImage = 'museecho-app:local'
)

$ErrorActionPreference = 'Stop'
$volumeName = "museecho-secret-contract-$PID-$([Guid]::NewGuid().ToString('N'))"
if ($volumeName -notmatch '^museecho-secret-contract-[0-9]+-[0-9a-f]{32}$') {
    throw 'invalid task-scoped Secret contract volume name'
}

$setup = @'
import base64
import os
from pathlib import Path

root = Path("/fixture")
os.chown(root, 0, 10001)
os.chmod(root, 0o750)
values = {
    "audio-kek": base64.b64encode(bytes(range(32))).decode(),
    "provider-key": "contract-provider-key",
}
for name, value in values.items():
    path = root / name
    path.write_text(value, encoding="utf-8")
    os.chown(path, 10001, 10001)
    os.chmod(path, 0o400)
'@

$probe = @'
import errno
import os
from pathlib import Path

from museecho.infrastructure.secrets import FileSecretStore

root = Path("/run/secrets")
root_stat = root.stat()
assert (root_stat.st_uid, root_stat.st_gid, root_stat.st_mode & 0o777) == (0, 10001, 0o750)
expected = {
    "audio-kek": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
    "provider-key": "contract-provider-key",
}
for name, value in expected.items():
    path = root / name
    stat = path.stat()
    assert (stat.st_uid, stat.st_gid, stat.st_mode & 0o777) == (10001, 10001, 0o400)
    assert FileSecretStore(path, repository_root=Path("/app")).get() == value
    try:
        path.write_text("must-not-write", encoding="utf-8")
    except OSError as error:
        assert error.errno in {errno.EACCES, errno.EROFS}
    else:
        raise AssertionError(f"read-only Secret mount allowed a write: {path}")
'@

try {
    & docker volume create $volumeName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'task-scoped Secret contract volume creation failed' }
    $setup | & docker run --rm --network none --user 0:0 `
        --mount "type=volume,source=$volumeName,target=/fixture" `
        --entrypoint /app/.venv/bin/python $AppImage -
    if ($LASTEXITCODE -ne 0) { throw 'Linux Secret ownership/mode fixture setup failed' }
    $probe | & docker run --rm --network none --read-only --cap-drop ALL `
        --security-opt no-new-privileges --user 10001:10001 `
        --mount "type=volume,source=$volumeName,target=/run/secrets,readonly" `
        --entrypoint /app/.venv/bin/python $AppImage -
    if ($LASTEXITCODE -ne 0) { throw 'Linux Secret ownership/mode/read-only probe failed' }
    Write-Host 'Linux Secret contract passed: root:10001/0750 traversal, 10001:10001/0400 files, and read-only production mount behavior.'
} finally {
    & docker volume rm --force $volumeName 2>&1 | Out-Null
}

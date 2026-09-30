#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091 # SCRIPT_DIR resolves this sibling at runtime.
source "$SCRIPT_DIR/lib.sh"

archive=''
confirmed=0
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --archive) archive="${2:-}"; shift 2 ;;
        --confirm-restore) confirmed=1; shift ;;
        *) fail 'usage: restore.sh --archive /srv/museecho/backups/museecho-<timestamp>.tar.gz[.age] --confirm-restore' ;;
    esac
done
[[ -n "$archive" && "$confirmed" -eq 1 ]] \
    || fail 'an exact archive path and --confirm-restore are required'
require_root
backup_dir="$MUSEECHO_BASE/backups"
[[ -f "$archive" && ! -L "$archive" ]] || fail 'backup archive must be a regular, non-symlink file'
archive="$(readlink -f "$archive")"
case "$archive" in
    "$backup_dir"/museecho-*.tar.gz|"$backup_dir"/museecho-*.tar.gz.age) ;;
    *) fail "backup archive must be inside $backup_dir" ;;
esac
command -v python3 >/dev/null || fail 'python3 with the standard sqlite3 module is required'
work="$(mktemp -d "$backup_dir/.restore.XXXXXX")"
trap 'rm -rf "$work"' EXIT
plain_archive="$archive"
if [[ "$archive" == *.age ]]; then
    identity_file="$(read_runtime_value MUSEECHO_BACKUP_AGE_IDENTITY_FILE)"
    [[ -n "$identity_file" && -r "$identity_file" ]] \
        || fail 'MUSEECHO_BACKUP_AGE_IDENTITY_FILE must name a readable age identity file'
    command -v age >/dev/null || fail 'age is required to restore this encrypted backup'
    plain_archive="$work/archive.tar.gz"
    age --decrypt --identity "$identity_file" --output "$plain_archive" "$archive"
fi

while IFS= read -r member; do
    case "$member" in
        ./|./museecho.db|./SHA256SUMS|./BACKUP-METADATA.txt|./runtime.env|./release.env) ;;
        *) fail "backup contains an unexpected archive member: $member" ;;
    esac
done < <(tar -tzf "$plain_archive")
mkdir "$work/extracted"
tar -xzf "$plain_archive" -C "$work/extracted" --no-same-owner --no-same-permissions
for required in museecho.db SHA256SUMS BACKUP-METADATA.txt; do
    [[ -f "$work/extracted/$required" && ! -L "$work/extracted/$required" ]] \
        || fail "backup is missing required file: $required"
done
(cd "$work/extracted" && sha256sum -c SHA256SUMS >/dev/null) \
    || fail 'backup checksum verification failed'
python3 - "$work/extracted/museecho.db" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
try:
    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {result}")
finally:
    connection.close()
PY

domain="$(read_domain)"
database="$MUSEECHO_DATA_DIR/museecho.db"
rollback="$work/live-before-restore.db"
systemctl stop museecho.service
had_database=0
if [[ -f "$database" ]]; then
    cp "$database" "$rollback"
    had_database=1
fi
pending="$MUSEECHO_DATA_DIR/.museecho.restore.$$"
install -m 0640 "$work/extracted/museecho.db" "$pending"
if [[ -z "$MUSEECHO_ROOT_PREFIX" ]]; then chown 10001:10001 "$pending"; fi
mv -f "$pending" "$database"
rm -f -- "${database}-wal" "${database}-shm"
if restart_service && health_check "$domain"; then
    printf 'Restore verified: %s\n' "$archive"
    exit 0
fi

printf 'ERROR: restored database failed health check; reverting database\n' >&2
systemctl stop museecho.service || true
if [[ "$had_database" -eq 1 ]]; then
    install -m 0640 "$rollback" "$pending"
    if [[ -z "$MUSEECHO_ROOT_PREFIX" ]]; then chown 10001:10001 "$pending"; fi
    mv -f "$pending" "$database"
else
    rm -f -- "$database"
fi
rm -f -- "${database}-wal" "${database}-shm"
restart_service || true
exit 1

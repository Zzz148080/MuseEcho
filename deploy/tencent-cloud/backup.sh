#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091 # SCRIPT_DIR resolves this sibling at runtime.
source "$SCRIPT_DIR/lib.sh"

[[ "$#" -eq 0 ]] || fail 'usage: backup.sh'
require_root
database="$MUSEECHO_DATA_DIR/museecho.db"
[[ -r "$database" ]] || fail "database is not readable: $database"
command -v python3 >/dev/null || fail 'python3 with the standard sqlite3 module is required for an online database backup'
backup_dir="$MUSEECHO_BASE/backups"
if [[ -n "$MUSEECHO_ROOT_PREFIX" ]]; then
    install -d -m 0700 "$backup_dir"
else
    install -d -o root -g root -m 0700 "$backup_dir"
fi
work="$(mktemp -d "$backup_dir/.backup.XXXXXX")"
trap 'rm -rf "$work"' EXIT
python3 - "$database" "$work/museecho.db" <<'PY'
import sqlite3
import sys

source_path, target_path = sys.argv[1:]
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
target = sqlite3.connect(target_path)
try:
    source.backup(target)
    integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError("SQLite online backup integrity check failed")
finally:
    target.close()
    source.close()
PY
if [[ -z "$MUSEECHO_ROOT_PREFIX" ]]; then chown root:root "$work/museecho.db"; fi
chmod 0600 "$work/museecho.db"
if [[ -r "$MUSEECHO_RUNTIME_ENV" ]]; then
    install_owned_file 0600 "$MUSEECHO_RUNTIME_ENV" "$work/runtime.env"
fi
if [[ -L "$MUSEECHO_CURRENT_LINK" ]]; then
    current="$(readlink -f "$MUSEECHO_CURRENT_LINK")"
    if release_is_verified "$current"; then
        install_owned_file 0600 "$current/release.env" "$work/release.env"
    fi
fi
cat > "$work/BACKUP-METADATA.txt" <<'EOF'
MuseEcho backup scope: SQLite database and non-secret deployment metadata only.
Database consistency: the SQLite online backup API produces a standalone, integrity-checked database snapshot while WAL writes may continue; no WAL sidecar is needed for this snapshot.
Encryption boundary: encrypted audio ciphertext and per-analysis wrapped-key material are deliberately excluded; recovery of audio requires a separately protected data backup and the root-readable KEK outside this archive.
Secrets are never copied into this archive.
EOF
checksum_files=(museecho.db BACKUP-METADATA.txt)
[[ -f "$work/runtime.env" ]] && checksum_files+=(runtime.env)
[[ -f "$work/release.env" ]] && checksum_files+=(release.env)
(cd "$work" && sha256sum "${checksum_files[@]}" > SHA256SUMS)
archive="$backup_dir/museecho-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
tar -C "$work" --sort=name --mtime='UTC 1970-01-01' -czf "$archive" .
chmod 0600 "$archive"
printf 'Backup created: %s\n' "$archive"

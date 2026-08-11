#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

[[ "$#" -eq 0 ]] || fail 'usage: backup.sh'
require_root
database="$MUSEECHO_DATA_DIR/museecho.db"
[[ -r "$database" ]] || fail "database is not readable: $database"
backup_dir="$MUSEECHO_BASE/backups"
if [[ -n "$MUSEECHO_ROOT_PREFIX" ]]; then
    install -d -m 0700 "$backup_dir"
else
    install -d -o root -g root -m 0700 "$backup_dir"
fi
work="$(mktemp -d "$backup_dir/.backup.XXXXXX")"
trap 'rm -rf "$work"' EXIT
install_owned_file 0600 "$database" "$work/museecho.db"
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
Encryption boundary: encrypted audio ciphertext and per-analysis wrapped-key material are deliberately excluded; recovery of audio requires a separately protected data backup and the root-readable KEK outside this archive.
Secrets are never copied into this archive.
EOF
(cd "$work" && sha256sum museecho.db runtime.env release.env BACKUP-METADATA.txt 2>/dev/null > SHA256SUMS || sha256sum museecho.db BACKUP-METADATA.txt > SHA256SUMS)
archive="$backup_dir/museecho-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
tar -C "$work" --sort=name --mtime='UTC 1970-01-01' -czf "$archive" .
chmod 0600 "$archive"
printf 'Backup created: %s\n' "$archive"

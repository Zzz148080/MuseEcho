#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

[[ "$#" -eq 0 ]] || fail 'usage: rollback.sh'
require_root
domain="$(read_domain)"
[[ -L "$MUSEECHO_CURRENT_LINK" ]] || fail 'no active release to roll back'
current="$(readlink -f "$MUSEECHO_CURRENT_LINK")"
candidate=''
while IFS= read -r release; do
    [[ "$release" == "$current" ]] && continue
    if release_is_verified "$release"; then candidate="$release"; break; fi
done < <(find "$MUSEECHO_RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)
[[ -n "$candidate" ]] || fail 'no verified prior release is available'
switch_current_to "$candidate"
if ! restart_service || ! health_check "$domain"; then
    printf 'ERROR: rollback target failed health check; restoring current release\n' >&2
    switch_current_to "$current"
    restart_service || true
    exit 1
fi
printf 'Rollback activated: %s\n' "$(basename "$candidate")"

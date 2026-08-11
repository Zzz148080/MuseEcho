#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

app_image=''
gateway_image=''
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --app-image) app_image="${2:-}"; shift 2 ;;
        --gateway-image) gateway_image="${2:-}"; shift 2 ;;
        *) fail 'usage: deploy.sh --app-image name@sha256:<digest> --gateway-image name@sha256:<digest>' ;;
    esac
done
[[ -n "$app_image" && -n "$gateway_image" ]] || fail 'both app and gateway images are required'
require_digest_reference "$app_image"
require_digest_reference "$gateway_image"
require_root
domain="$(read_domain)"
[[ -f "$MUSEECHO_SECRETS_DIR/audio-kek" ]] || fail "required secret file is missing: $MUSEECHO_SECRETS_DIR/audio-kek"

release_id="$(date -u +%Y%m%dT%H%M%SZ)-${app_image##*@sha256:}"
release_id="${release_id:0:32}"
stage="$(mktemp -d "$MUSEECHO_RELEASES_DIR/.stage.XXXXXX")"
cleanup_stage=1
trap 'if [[ "$cleanup_stage" -eq 1 ]]; then rm -rf "$stage"; fi' EXIT

docker pull "$app_image" >/dev/null
docker pull "$gateway_image" >/dev/null

cat > "$stage/release.env" <<EOF
MUSEECHO_APP_IMAGE=$app_image
MUSEECHO_GATEWAY_IMAGE=$gateway_image
MUSEECHO_DOMAIN=$domain
EOF
for setting in MUSEECHO_PROVIDER_BASE_URL MUSEECHO_PROVIDER_MODEL MUSEECHO_PROVIDER_SECRET_FILE; do
    value="$(sed -n "s/^${setting}=//p" "$MUSEECHO_RUNTIME_ENV" | tail -n 1)"
    printf '%s=%s\n' "$setting" "$value" >> "$stage/release.env"
done
cat > "$stage/Caddyfile" <<EOF
{
    admin off
}

https://$domain:8443 {
    encode zstd gzip
    handle /api/* {
        reverse_proxy app:8000
    }
    handle {
        root * /srv
        try_files {path} /index.html
        file_server
    }
}

http://:8080 {
    redir https://{host}{uri} 308
}
EOF
cat > "$stage/compose.yaml" <<'EOF'
name: museecho
services:
  app:
    image: ${MUSEECHO_APP_IMAGE:?digest-qualified app image required}
    restart: unless-stopped
    environment:
      MUSEECHO_DATA_ROOT: /data
      MUSEECHO_AUDIO_KEK_FILE: /run/secrets/audio-kek
      MUSEECHO_TRUSTED_ORIGINS: https://${MUSEECHO_DOMAIN}
      MUSEECHO_PROVIDER_BASE_URL: ${MUSEECHO_PROVIDER_BASE_URL:-}
      MUSEECHO_PROVIDER_MODEL: ${MUSEECHO_PROVIDER_MODEL:-}
      MUSEECHO_PROVIDER_SECRET_FILE: ${MUSEECHO_PROVIDER_SECRET_FILE:-}
    volumes:
      - /srv/museecho/data:/data
      - /etc/museecho/secrets:/run/secrets:ro
    read_only: true
    tmpfs: [/tmp:size=256m,mode=1777]
    security_opt: [no-new-privileges:true]
    cap_drop: [ALL]
  gateway:
    image: ${MUSEECHO_GATEWAY_IMAGE:?digest-qualified gateway image required}
    restart: unless-stopped
    depends_on: [app]
    environment:
      HTTPS_EXTERNAL_PORT: "443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
    ports: ["80:8080", "443:8443"]
    read_only: true
    tmpfs: [/tmp:size=64m,mode=1777]
    security_opt: [no-new-privileges:true]
    cap_drop: [ALL]
EOF
chmod 0640 "$stage/release.env"
final_release="$MUSEECHO_RELEASES_DIR/$release_id"
[[ ! -e "$final_release" ]] || fail "release already exists: $release_id"
mv "$stage" "$final_release"
cleanup_stage=0
printf 'verified\n' > "$final_release/.verified"
chmod 0640 "$final_release/release.env" "$final_release/.verified"

previous=''
if [[ -L "$MUSEECHO_CURRENT_LINK" ]]; then previous="$(readlink -f "$MUSEECHO_CURRENT_LINK")"; fi
switch_current_to "$final_release"
if ! restart_service || ! health_check "$domain"; then
    printf 'ERROR: new release failed health check; rolling back\n' >&2
    if [[ -n "$previous" ]] && release_is_verified "$previous"; then
        switch_current_to "$previous"
        restart_service || true
    else
        rm -f "$MUSEECHO_CURRENT_LINK"
        systemctl stop museecho.service || true
    fi
    exit 1
fi
printf 'Deployment activated: %s\n' "$release_id"

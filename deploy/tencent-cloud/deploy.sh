#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091 # SCRIPT_DIR resolves this sibling at runtime.
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
tunnel_mode="$(read_tunnel_mode)"
validate_provider_configuration
validate_smtp_configuration
validate_tencent_ses_configuration
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
MUSEECHO_TUNNEL_MODE=$tunnel_mode
EOF
for setting in MUSEECHO_PROVIDER_BASE_URL MUSEECHO_PROVIDER_MODEL MUSEECHO_PROVIDER_SECRET_FILE; do
    value="$(read_runtime_value "$setting")"
    printf '%s=%s\n' "$setting" "$value" >> "$stage/release.env"
done
for setting in MUSEECHO_SMTP_HOST MUSEECHO_SMTP_PORT MUSEECHO_SMTP_USER MUSEECHO_SMTP_PASSWORD_FILE MUSEECHO_SMTP_SENDER; do
    value="$(read_runtime_value "$setting")"
    printf '%s=%s\n' "$setting" "$value" >> "$stage/release.env"
done
for setting in MUSEECHO_TENCENT_SES_REGION MUSEECHO_TENCENT_SES_SENDER MUSEECHO_TENCENT_SES_SECRET_ID_FILE MUSEECHO_TENCENT_SES_SECRET_KEY_FILE MUSEECHO_TENCENT_SES_VERIFY_TEMPLATE_ID MUSEECHO_TENCENT_SES_RESET_TEMPLATE_ID; do
    value="$(read_runtime_value "$setting")"
    printf '%s=%s\n' "$setting" "$value" >> "$stage/release.env"
done
if [[ "$tunnel_mode" == 1 ]]; then
    caddy_tls='    tls internal'
else
    caddy_tls=''
fi
cat > "$stage/Caddyfile" <<EOF
{
    admin off
}

https://$domain:8443 {
${caddy_tls}
    encode zstd gzip
    handle /api/* {
        reverse_proxy app:8000 {
            header_up X-MuseEcho-Client-IP {remote_host}
        }
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
  migrate:
    profiles: [migration]
    image: ${MUSEECHO_APP_IMAGE:?digest-qualified app image required}
    command: [python, -m, museecho.infrastructure.migrate]
    environment:
      MUSEECHO_DATA_ROOT: /data
    volumes:
      - /srv/museecho/data:/data
    read_only: true
    tmpfs:
      - "/tmp:size=64m,mode=1777"
    security_opt: [no-new-privileges:true]
    cap_drop: [ALL]
  app:
    image: ${MUSEECHO_APP_IMAGE:?digest-qualified app image required}
    restart: unless-stopped
    environment:
      MUSEECHO_DATA_ROOT: /data
      MUSEECHO_AUDIO_KEK_FILE: /run/secrets/audio-kek
      MUSEECHO_TRUSTED_ORIGINS: https://${MUSEECHO_DOMAIN}
      MUSEECHO_PUBLIC_ORIGIN: https://${MUSEECHO_DOMAIN}
      MUSEECHO_TRUSTED_PROXY_CIDRS: 172.16.0.0/12
      MUSEECHO_SMTP_HOST: ${MUSEECHO_SMTP_HOST:-}
      MUSEECHO_SMTP_PORT: ${MUSEECHO_SMTP_PORT:-587}
      MUSEECHO_SMTP_USER: ${MUSEECHO_SMTP_USER:-}
      MUSEECHO_SMTP_PASSWORD_FILE: ${MUSEECHO_SMTP_PASSWORD_FILE:-}
      MUSEECHO_SMTP_SENDER: ${MUSEECHO_SMTP_SENDER:-}
      MUSEECHO_TENCENT_SES_REGION: ${MUSEECHO_TENCENT_SES_REGION:-}
      MUSEECHO_TENCENT_SES_SENDER: ${MUSEECHO_TENCENT_SES_SENDER:-}
      MUSEECHO_TENCENT_SES_SECRET_ID_FILE: ${MUSEECHO_TENCENT_SES_SECRET_ID_FILE:-}
      MUSEECHO_TENCENT_SES_SECRET_KEY_FILE: ${MUSEECHO_TENCENT_SES_SECRET_KEY_FILE:-}
      MUSEECHO_TENCENT_SES_VERIFY_TEMPLATE_ID: ${MUSEECHO_TENCENT_SES_VERIFY_TEMPLATE_ID:-}
      MUSEECHO_TENCENT_SES_RESET_TEMPLATE_ID: ${MUSEECHO_TENCENT_SES_RESET_TEMPLATE_ID:-}
      MUSEECHO_PROVIDER_BASE_URL: ${MUSEECHO_PROVIDER_BASE_URL:-}
      MUSEECHO_PROVIDER_MODEL: ${MUSEECHO_PROVIDER_MODEL:-}
      MUSEECHO_PROVIDER_SECRET_FILE: ${MUSEECHO_PROVIDER_SECRET_FILE:-}
    volumes:
      - /srv/museecho/data:/data
      - /etc/museecho/secrets:/run/secrets:ro
    read_only: true
    tmpfs:
      - "/tmp:size=256m,mode=1777"
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
    tmpfs:
      - "/tmp:size=64m,mode=1777"
    security_opt: [no-new-privileges:true]
    cap_drop: [ALL]
EOF
chmod 0640 "$stage/release.env"
final_release="$MUSEECHO_RELEASES_DIR/$release_id"
[[ ! -e "$final_release" ]] || fail "release already exists: $release_id"
mv "$stage" "$final_release"
cleanup_stage=0
if [[ -z "$MUSEECHO_ROOT_PREFIX" ]]; then
    chown root:10001 "$final_release"
    chown root:10001 "$final_release/Caddyfile" "$final_release/compose.yaml" "$final_release/release.env"
fi
chmod 0750 "$final_release"
chmod 0640 "$final_release/Caddyfile" "$final_release/compose.yaml"
chmod 0640 "$final_release/release.env"

previous=''
if [[ -L "$MUSEECHO_CURRENT_LINK" ]]; then previous="$(readlink -f "$MUSEECHO_CURRENT_LINK")"; fi
migration_rollback=''
if [[ -r "$MUSEECHO_DATA_DIR/museecho.db" ]]; then
    bash "$SCRIPT_DIR/backup.sh"
fi
systemctl stop museecho.service || true
if [[ -r "$MUSEECHO_DATA_DIR/museecho.db" ]]; then
    migration_rollback="$MUSEECHO_DATA_DIR/.pre-migrate-${release_id}.db"
    python3 - "$MUSEECHO_DATA_DIR/museecho.db" "$migration_rollback" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
target = sqlite3.connect(sys.argv[2])
try:
    source.backup(target)
finally:
    target.close()
    source.close()
PY
    chmod 0600 "$migration_rollback"
fi
switch_current_to "$final_release"
if ! (
    cd "$final_release"
    docker compose --project-name museecho --env-file release.env -f compose.yaml \
        --profile migration run --rm migrate
); then
    printf 'ERROR: database migration failed; restoring prior release\n' >&2
    if [[ -n "$migration_rollback" && -f "$migration_rollback" ]]; then
        mv -f "$migration_rollback" "$MUSEECHO_DATA_DIR/museecho.db"
        if [[ -z "$MUSEECHO_ROOT_PREFIX" ]]; then
            chown 10001:10001 "$MUSEECHO_DATA_DIR/museecho.db"
        fi
        rm -f -- "$MUSEECHO_DATA_DIR/museecho.db-wal" "$MUSEECHO_DATA_DIR/museecho.db-shm"
    fi
    if [[ -n "$previous" ]] && release_is_verified "$previous"; then
        switch_current_to "$previous"
        if ! restart_service || ! health_check "$domain"; then
            systemctl stop museecho.service || true
            rm -f "$MUSEECHO_CURRENT_LINK"
        fi
    else
        systemctl stop museecho.service || true
        rm -f "$MUSEECHO_CURRENT_LINK"
    fi
    exit 1
fi
if [[ -n "$migration_rollback" ]]; then rm -f "$migration_rollback"; fi
if restart_service && health_check "$domain"; then
    printf 'verified\n' > "$final_release/.verified"
    chmod 0640 "$final_release/.verified"
    printf 'Deployment activated: %s\n' "$release_id"
    exit 0
fi

printf 'ERROR: new release failed health check; rolling back\n' >&2
if [[ -n "$previous" ]] && release_is_verified "$previous"; then
    switch_current_to "$previous"
    if restart_service && health_check "$domain"; then
        printf 'ERROR: new release failed health check; verified prior release restored\n' >&2
        exit 1
    fi
    printf 'ERROR: previous release failed health check; stopping service\n' >&2
else
    printf 'ERROR: no verified prior release is available; stopping service\n' >&2
fi
systemctl stop museecho.service || true
rm -f "$MUSEECHO_CURRENT_LINK"
exit 1

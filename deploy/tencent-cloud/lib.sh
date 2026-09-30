#!/usr/bin/env bash
# Shared, non-secret deployment contract.  Scripts intentionally never source
# a secrets file and never accept a secret on their command line.
set -eu

MUSEECHO_ROOT_PREFIX="${MUSEECHO_TEST_ROOT:-}"

root_path() {
    if [[ -n "$MUSEECHO_ROOT_PREFIX" ]]; then
        printf '%s%s\n' "$MUSEECHO_ROOT_PREFIX" "$1"
    else
        printf '%s\n' "$1"
    fi
}

MUSEECHO_BASE="$(root_path /srv/museecho)"
# shellcheck disable=SC2034 # Consumed by scripts that source this shared contract.
MUSEECHO_DATA_DIR="$MUSEECHO_BASE/data"
# shellcheck disable=SC2034 # Consumed by scripts that source this shared contract.
MUSEECHO_RELEASES_DIR="$MUSEECHO_BASE/releases"
MUSEECHO_CONFIG_DIR="$MUSEECHO_BASE/config"
MUSEECHO_RUNTIME_ENV="$MUSEECHO_CONFIG_DIR/runtime.env"
MUSEECHO_CURRENT_LINK="$MUSEECHO_BASE/current"
# shellcheck disable=SC2034 # Consumed by scripts that source this shared contract.
MUSEECHO_SECRETS_DIR="$(root_path /etc/museecho/secrets)"
# shellcheck disable=SC2034 # Consumed by scripts that source this shared contract.
MUSEECHO_UNIT_PATH="$(root_path /etc/systemd/system/museecho.service)"

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_root() {
    if [[ -z "$MUSEECHO_ROOT_PREFIX" && "${EUID}" -ne 0 ]]; then
        fail 'run this production operation as root (for example: sudo deploy/tencent-cloud/install.sh)'
    fi
}

require_digest_reference() {
    local reference="$1"
    [[ "$reference" =~ ^[^[:space:]@]+@sha256:[a-f0-9]{64}$ ]] \
        || fail 'image references must be digest-qualified (name@sha256:<64 lowercase hex>)'
}

read_domain() {
    [[ -r "$MUSEECHO_RUNTIME_ENV" ]] || fail "missing runtime configuration: $MUSEECHO_RUNTIME_ENV"
    local domain
    domain="$(sed -n 's/^MUSEECHO_DOMAIN=//p' "$MUSEECHO_RUNTIME_ENV" | tail -n 1)"
    [[ "$domain" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$ ]] \
        || fail 'MUSEECHO_DOMAIN must be a DNS hostname in runtime.env'
    printf '%s\n' "$domain"
}

read_runtime_value() {
    local setting="$1"
    sed -n "s/^${setting}=//p" "$MUSEECHO_RUNTIME_ENV" | tail -n 1
}

read_tunnel_mode() {
    local value
    value="$(read_runtime_value MUSEECHO_TUNNEL_MODE)"
    [[ -z "$value" ]] && value=0
    [[ "$value" == 0 || "$value" == 1 ]] \
        || fail 'MUSEECHO_TUNNEL_MODE must be 0 or 1'
    printf '%s\n' "$value"
}

validate_provider_configuration() {
    local setting value configured=0
    for setting in MUSEECHO_PROVIDER_BASE_URL MUSEECHO_PROVIDER_MODEL MUSEECHO_PROVIDER_SECRET_FILE; do
        value="$(read_runtime_value "$setting")"
        [[ -z "$value" ]] || configured=$((configured + 1))
    done
    [[ "$configured" -eq 0 || "$configured" -eq 3 ]] \
        || fail 'provider configuration must set all three values or none'
}

validate_smtp_configuration() {
    local setting value configured=0
    for setting in MUSEECHO_SMTP_HOST MUSEECHO_SMTP_USER MUSEECHO_SMTP_PASSWORD_FILE MUSEECHO_SMTP_SENDER; do
        value="$(read_runtime_value "$setting")"
        [[ -z "$value" ]] || configured=$((configured + 1))
    done
    [[ "$configured" -eq 0 || "$configured" -eq 4 ]] \
        || fail 'SMTP configuration must set host, user, password file and sender, or leave all empty'
    value="$(read_runtime_value MUSEECHO_SMTP_PORT)"
    [[ -z "$value" || "$value" =~ ^[0-9]+$ ]] || fail 'MUSEECHO_SMTP_PORT must be numeric'
    if [[ -n "$value" ]]; then
        [[ "$value" -ge 1 && "$value" -le 65535 ]] || fail 'MUSEECHO_SMTP_PORT is outside the valid range'
    fi
}

validate_tencent_ses_configuration() {
    local setting value configured=0 smtp_configured=0
    for setting in MUSEECHO_TENCENT_SES_REGION MUSEECHO_TENCENT_SES_SENDER MUSEECHO_TENCENT_SES_SECRET_ID_FILE MUSEECHO_TENCENT_SES_SECRET_KEY_FILE MUSEECHO_TENCENT_SES_VERIFY_TEMPLATE_ID MUSEECHO_TENCENT_SES_RESET_TEMPLATE_ID; do
        value="$(read_runtime_value "$setting")"
        [[ -z "$value" ]] || configured=$((configured + 1))
    done
    [[ "$configured" -eq 0 || "$configured" -eq 6 ]] \
        || fail 'Tencent SES API configuration must set region, sender, both template IDs and both credential files, or leave all empty'
    for setting in MUSEECHO_TENCENT_SES_VERIFY_TEMPLATE_ID MUSEECHO_TENCENT_SES_RESET_TEMPLATE_ID; do
        value="$(read_runtime_value "$setting")"
        [[ -z "$value" || "$value" =~ ^[1-9][0-9]*$ ]] \
            || fail "$setting must be a positive integer"
    done
    for setting in MUSEECHO_SMTP_HOST MUSEECHO_SMTP_USER MUSEECHO_SMTP_PASSWORD_FILE MUSEECHO_SMTP_SENDER; do
        value="$(read_runtime_value "$setting")"
        [[ -z "$value" ]] || smtp_configured=$((smtp_configured + 1))
    done
    [[ "$configured" -eq 0 || "$smtp_configured" -eq 0 ]] \
        || fail 'configure either Tencent SES API or SMTP, not both'
}

release_is_verified() {
    local release="$1"
    [[ -d "$release" && -f "$release/.verified" && -f "$release/release.env" && -f "$release/compose.yaml" && -f "$release/Caddyfile" ]] \
        || return 1
    local app_image gateway_image
    app_image="$(sed -n 's/^MUSEECHO_APP_IMAGE=//p' "$release/release.env" | tail -n 1)"
    gateway_image="$(sed -n 's/^MUSEECHO_GATEWAY_IMAGE=//p' "$release/release.env" | tail -n 1)"
    [[ "$app_image" =~ ^[^[:space:]@]+@sha256:[a-f0-9]{64}$ ]] && \
        [[ "$gateway_image" =~ ^[^[:space:]@]+@sha256:[a-f0-9]{64}$ ]]
}

switch_current_to() {
    local target="$1"
    [[ ! -e "$MUSEECHO_CURRENT_LINK" || -L "$MUSEECHO_CURRENT_LINK" ]] \
        || fail "current release path is not a symbolic link: $MUSEECHO_CURRENT_LINK"
    ln -s "$target" "$MUSEECHO_BASE/current.next"
    mv -Tf "$MUSEECHO_BASE/current.next" "$MUSEECHO_CURRENT_LINK"
}

restart_service() {
    systemctl restart museecho.service
}

health_check() {
    local domain="$1"
    local attempts=45
    local -a curl_args=(--fail --silent --show-error --connect-timeout 5 --max-time 20)
    if [[ "$(read_tunnel_mode)" == 1 ]]; then
        # In Tunnel mode Caddy uses a private internal CA. Cloudflare connects
        # to this origin over HTTPS, while the local deployment gate accepts
        # that private certificate explicitly.
        curl_args+=(--insecure)
    fi
    while (( attempts > 0 )); do
        if curl "${curl_args[@]}" \
            --resolve "$domain:443:127.0.0.1" "https://$domain/api/health" >/dev/null 2>&1; then
            return 0
        fi
        attempts=$((attempts - 1))
        (( attempts > 0 )) && sleep 2
    done
    return 1
}

install_owned_dir() {
    local mode="$1"; shift
    if [[ -n "$MUSEECHO_ROOT_PREFIX" ]]; then
        install -d -m "$mode" "$@"
    else
        install -d -o root -g 10001 -m "$mode" "$@"
    fi
}

install_owned_file() {
    local mode="$1" source_file="$2" target_file="$3"
    if [[ -n "$MUSEECHO_ROOT_PREFIX" ]]; then
        install -m "$mode" "$source_file" "$target_file"
    else
        install -o root -g root -m "$mode" "$source_file" "$target_file"
    fi
}

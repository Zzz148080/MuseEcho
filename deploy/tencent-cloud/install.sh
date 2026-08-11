#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

check_only=0
if [[ "${1:-}" == "--check-only" ]]; then
    check_only=1
    shift
fi
[[ "$#" -eq 0 ]] || fail 'usage: install.sh [--check-only]'

check_requirements() {
    [[ "$(uname -s)" == Linux ]] || fail 'Tencent Cloud installation requires Linux'
    if [[ "${MUSEECHO_SKIP_CAPACITY_CHECK:-0}" != 1 ]]; then
        [[ "$(getconf _NPROCESSORS_ONLN)" -ge 2 ]] || fail 'at least 2 CPU cores are required'
        [[ "$(awk '/MemTotal:/ { print $2 }' /proc/meminfo)" -ge 4194304 ]] || fail 'at least 4 GiB RAM is required'
        local available_kib min_disk_kib
        min_disk_kib="${MUSEECHO_MIN_DISK_KIB:-20971520}"
        available_kib="$(df -Pk "$(dirname "$MUSEECHO_BASE")" | awk 'NR == 2 { print $4 }')"
        [[ "$available_kib" -ge "$min_disk_kib" ]] || fail 'insufficient disk for release, data, and backup budget'
    fi
    command -v docker >/dev/null || fail 'Docker Engine is required'
    local docker_version compose_version docker_major compose_major
    docker_version="$(docker --version)"
    [[ "$docker_version" =~ ([0-9]+)\. ]] || fail 'cannot determine Docker Engine version'
    docker_major="${BASH_REMATCH[1]}"
    [[ "$docker_major" -ge 24 ]] || fail 'Docker Engine 24 or newer is required'
    compose_version="$(docker compose version)" || fail 'Docker Compose v2 is required'
    [[ "$compose_version" =~ v?([0-9]+)\. ]] || fail 'cannot determine Docker Compose version'
    compose_major="${BASH_REMATCH[1]}"
    [[ "$compose_major" -ge 2 ]] || fail 'Docker Compose v2 is required'
    command -v curl >/dev/null || fail 'curl is required for health checks'
    command -v systemctl >/dev/null || fail 'systemd/systemctl is required'
    command -v install >/dev/null || fail 'install is required'
    if [[ -n "$MUSEECHO_ROOT_PREFIX" ]]; then
        [[ -d "$MUSEECHO_ROOT_PREFIX" ]] || fail 'test deployment root does not exist'
    else
        [[ -d "$(dirname "$MUSEECHO_BASE")" ]] || fail 'deployment layout assumptions are not met'
    fi
    [[ -d "$SCRIPT_DIR" && -f "$SCRIPT_DIR/museecho.service" ]] || fail 'deployment bundle is incomplete'
    printf 'requirements: Linux, CPU/RAM/disk, Docker/Compose, curl, systemd, and layout verified\n'
}

install_firewall_rules() {
    if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q '^Status: active'; then
        ufw allow 22/tcp
        ufw allow 80/tcp
        ufw allow 443/tcp
    else
        printf 'NOTICE: no active UFW detected; allow only TCP 22, 80, and 443 in Lighthouse security groups/firewall.\n'
    fi
}

install_layout() {
    require_root
    if [[ -n "$MUSEECHO_ROOT_PREFIX" ]]; then
        install -d -m 0755 "$MUSEECHO_BASE"
    else
        install -d -o root -g root -m 0755 "$MUSEECHO_BASE"
    fi
    install_owned_dir 0750 "$MUSEECHO_DATA_DIR" "$MUSEECHO_RELEASES_DIR" "$MUSEECHO_CONFIG_DIR"
    install_owned_dir 0750 "$(dirname "$MUSEECHO_SECRETS_DIR")" "$MUSEECHO_SECRETS_DIR"
    : > "$MUSEECHO_DATA_DIR/.keep"
    : > "$MUSEECHO_RELEASES_DIR/.keep"
    chmod 0640 "$MUSEECHO_DATA_DIR/.keep" "$MUSEECHO_RELEASES_DIR/.keep"
    [[ ! -L "$MUSEECHO_RUNTIME_ENV" ]] || fail "runtime configuration must not be a symlink: $MUSEECHO_RUNTIME_ENV"
    if [[ ! -e "$MUSEECHO_RUNTIME_ENV" ]]; then
        umask 077
        printf '%s\n' \
            '# Non-secret deployment settings. Set MUSEECHO_DOMAIN before deploy.' \
            'MUSEECHO_DOMAIN=' \
            '# Optional provider mode: set all three provider variables, or leave all empty.' \
            'MUSEECHO_PROVIDER_BASE_URL=' \
            'MUSEECHO_PROVIDER_MODEL=' \
            'MUSEECHO_PROVIDER_SECRET_FILE=' > "$MUSEECHO_RUNTIME_ENV"
    fi
    if [[ -z "$MUSEECHO_ROOT_PREFIX" ]]; then chown root:10001 "$MUSEECHO_RUNTIME_ENV"; fi
    chmod 0640 "$MUSEECHO_RUNTIME_ENV"
    if [[ -e "$MUSEECHO_UNIT_PATH" ]] && ! grep -q 'MuseEcho Tencent Cloud deployment' "$MUSEECHO_UNIT_PATH"; then
        fail "refusing to overwrite unrelated systemd unit: $MUSEECHO_UNIT_PATH"
    fi
    if [[ -n "$MUSEECHO_ROOT_PREFIX" ]]; then
        install -D -m 0644 "$SCRIPT_DIR/museecho.service" "$MUSEECHO_UNIT_PATH"
    else
        install -D -o root -g root -m 0644 "$SCRIPT_DIR/museecho.service" "$MUSEECHO_UNIT_PATH"
    fi
    install_firewall_rules
    systemctl daemon-reload
    systemctl enable museecho.service
    printf 'Install complete. Configure SSH key authentication and set PasswordAuthentication no after confirming key login.\n'
    printf 'Place audio-kek (and optional provider-key) as 10001:10001 mode 0400 files in %s.\n' "$MUSEECHO_SECRETS_DIR"
}

check_requirements
if [[ "$check_only" -eq 1 ]]; then
    printf 'check-only: no host changes made\n'
    exit 0
fi
install_layout

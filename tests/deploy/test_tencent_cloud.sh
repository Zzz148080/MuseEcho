#!/usr/bin/env bash
# Contract tests for the Tencent Cloud delivery scripts.  They execute scripts
# against a disposable filesystem root and command doubles; no host service,
# firewall, Docker daemon, or secret is mutated.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEPLOY_DIR="$ROOT_DIR/deploy/tencent-cloud"
TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

failures=0

fail() { printf 'FAIL: %s\n' "$*" >&2; failures=$((failures + 1)); }
pass() { printf 'PASS: %s\n' "$*"; }

assert_contains() {
    local needle="$1" haystack="$2"
    [[ "$haystack" == *"$needle"* ]] || fail "expected output to contain: $needle"
}

assert_not_contains() {
    local needle="$1" haystack="$2"
    [[ "$haystack" != *"$needle"* ]] || fail "output leaked: $needle"
}

assert_file() { [[ -f "$1" ]] || fail "missing file: $1"; }
assert_no_file() { [[ ! -e "$1" ]] || fail "unexpected file: $1"; }

make_fake_bin() {
    local bin="$1"
    mkdir -p "$bin"
    cat > "$bin/docker" <<'EOF'
#!/usr/bin/env bash
set -eu
printf 'docker %s\n' "$*" >> "$MUSEECHO_TEST_LOG"
case "${1:-}" in
  --version) echo 'Docker version 29.1.3' ;;
  compose) shift; case "${1:-}" in version) echo 'Docker Compose version v2.36.0' ;; *) exit 0;; esac ;;
  image) exit 0 ;;
  pull) exit 0 ;;
  *) exit 0 ;;
esac
EOF
    cat > "$bin/systemctl" <<'EOF'
#!/usr/bin/env bash
set -eu
printf 'systemctl %s\n' "$*" >> "$MUSEECHO_TEST_LOG"
exit 0
EOF
    cat > "$bin/ufw" <<'EOF'
#!/usr/bin/env bash
set -eu
printf 'ufw %s\n' "$*" >> "$MUSEECHO_TEST_LOG"
if [[ "${1:-}" == status ]]; then echo 'Status: active'; fi
EOF
    cat > "$bin/curl" <<'EOF'
#!/usr/bin/env bash
set -eu
printf 'curl %s\n' "$*" >> "$MUSEECHO_TEST_LOG"
[[ "${MUSEECHO_TEST_HEALTH_FAIL:-0}" != 1 ]]
EOF
    chmod +x "$bin"/*
}

test_syntax_and_required_artifacts() {
    local script
    for script in install.sh deploy.sh rollback.sh backup.sh lib.sh; do
        bash -n "$DEPLOY_DIR/$script"
    done
    assert_file "$DEPLOY_DIR/museecho.service"
    assert_file "$DEPLOY_DIR/README.md"
    pass "delivery artifacts parse"
}

test_check_only_is_non_mutating() {
    local root="$TEST_TMP/check-root" bin="$TEST_TMP/check-bin" log="$TEST_TMP/check.log" output
    mkdir -p "$root" "$bin"
    make_fake_bin "$bin"
    output="$(PATH="$bin:$PATH" MUSEECHO_TEST_ROOT="$root" MUSEECHO_TEST_LOG="$log" \
        MUSEECHO_SKIP_CAPACITY_CHECK=1 bash "$DEPLOY_DIR/install.sh" --check-only 2>&1)" || fail "check-only should pass with controlled prerequisites: $output"
    assert_contains 'check-only: no host changes made' "$output"
    assert_no_file "$root/srv/museecho"
    assert_no_file "$root/etc/museecho"
    assert_no_file "$root/etc/systemd/system/museecho.service"
    [[ ! -e "$log" ]] || {
        assert_not_contains 'systemctl ' "$(<"$log")"
        assert_not_contains 'ufw ' "$(<"$log")"
    }
    pass "check-only has no host mutation"
}

test_install_layout_firewall_and_systemd() {
    local root="$TEST_TMP/install-root" bin="$TEST_TMP/install-bin" log="$TEST_TMP/install.log" output
    mkdir -p "$root" "$bin"; : > "$log"; make_fake_bin "$bin"
    output="$(PATH="$bin:$PATH" MUSEECHO_TEST_ROOT="$root" MUSEECHO_TEST_LOG="$log" \
        MUSEECHO_SKIP_CAPACITY_CHECK=1 bash "$DEPLOY_DIR/install.sh" 2>&1)" || fail "install should pass: $output"
    output="$(PATH="$bin:$PATH" MUSEECHO_TEST_ROOT="$root" MUSEECHO_TEST_LOG="$log" \
        MUSEECHO_SKIP_CAPACITY_CHECK=1 bash "$DEPLOY_DIR/install.sh" 2>&1)" || fail "repeat install should be idempotent: $output"
    assert_file "$root/srv/museecho/data/.keep"
    assert_file "$root/srv/museecho/releases/.keep"
    assert_file "$root/srv/museecho/config/runtime.env"
    assert_file "$root/etc/systemd/system/museecho.service"
    [[ "$(stat -c %a "$root/etc/museecho/secrets")" == 750 ]] || fail "secret directory mode is not 0750"
    [[ "$(stat -c %a "$root/srv/museecho/config/runtime.env")" == 640 ]] || fail "runtime env mode is not 0640"
    assert_contains 'ufw allow 22/tcp' "$(<"$log")"
    assert_contains 'ufw allow 80/tcp' "$(<"$log")"
    assert_contains 'ufw allow 443/tcp' "$(<"$log")"
    assert_not_contains 'ufw allow 8080' "$(<"$log")"
    assert_contains 'systemctl enable museecho.service' "$(<"$log")"
    pass "install provisions documented paths, firewall, and systemd"
}

test_digest_only_and_secret_safe_deploy() {
    local root="$TEST_TMP/deploy-root" bin="$TEST_TMP/deploy-bin" log="$TEST_TMP/deploy.log" output secret='not-a-real-provider-secret'
    mkdir -p "$root/srv/museecho/releases" "$root/srv/museecho/config" "$root/etc/museecho/secrets" "$bin"; : > "$log"; make_fake_bin "$bin"
    printf 'MUSEECHO_DOMAIN=example.test\n' > "$root/srv/museecho/config/runtime.env"
    printf 'test-kek' > "$root/etc/museecho/secrets/audio-kek"
    printf '%s' "$secret" > "$root/etc/museecho/secrets/provider-key"
    output="$(PATH="$bin:$PATH" MUSEECHO_TEST_ROOT="$root" MUSEECHO_TEST_LOG="$log" \
        bash "$DEPLOY_DIR/deploy.sh" --app-image 'registry.example/museecho-app:latest' \
        --gateway-image 'registry.example/museecho-gateway@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' 2>&1 || true)"
    assert_contains 'digest-qualified' "$output"
    output="$(PATH="$bin:$PATH" MUSEECHO_TEST_ROOT="$root" MUSEECHO_TEST_LOG="$log" \
        bash "$DEPLOY_DIR/deploy.sh" --app-image 'registry.example/museecho-app@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
        --gateway-image 'registry.example/museecho-gateway@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' 2>&1)" || fail "digest deploy should pass: $output"
    assert_not_contains "$secret" "$output"
    assert_not_contains "$secret" "$(<"$log")"
    [[ -L "$root/srv/museecho/current" ]] || fail "successful deployment did not switch current release"
    grep -R --fixed-strings -- "$secret" "$root/srv/museecho/releases" >/dev/null && fail "release staged a secret" || true
    pass "deploy rejects tags and never logs or stages secrets"
}

test_failed_health_restores_previous_release() {
    local root="$TEST_TMP/rollback-root" bin="$TEST_TMP/rollback-bin" log="$TEST_TMP/rollback.log" old="$TEST_TMP/rollback-root/srv/museecho/releases/old" output
    mkdir -p "$old" "$root/srv/museecho/config" "$root/etc/museecho/secrets" "$bin"; : > "$log"; make_fake_bin "$bin"
    printf 'MUSEECHO_DOMAIN=example.test\n' > "$root/srv/museecho/config/runtime.env"
    printf 'test-kek' > "$root/etc/museecho/secrets/audio-kek"
    printf 'verified\n' > "$old/.verified"
    cat > "$old/release.env" <<'EOF'
MUSEECHO_APP_IMAGE=registry.example/museecho-app@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
MUSEECHO_GATEWAY_IMAGE=registry.example/museecho-gateway@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
EOF
    : > "$old/compose.yaml"; : > "$old/Caddyfile"
    ln -s "$old" "$root/srv/museecho/current"
    output="$(PATH="$bin:$PATH" MUSEECHO_TEST_ROOT="$root" MUSEECHO_TEST_LOG="$log" MUSEECHO_TEST_HEALTH_FAIL=1 \
        bash "$DEPLOY_DIR/deploy.sh" --app-image 'registry.example/museecho-app@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
        --gateway-image 'registry.example/museecho-gateway@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' 2>&1 || true)"
    assert_contains 'rolling back' "$output"
    [[ "$(readlink "$root/srv/museecho/current")" == "$old" ]] || fail "health failure did not restore previous release"
    pass "failed health check rolls back atomically"
}

test_default_release_keeps_provider_mode_disabled() {
    local root="$TEST_TMP/provider-root" bin="$TEST_TMP/provider-bin" log="$TEST_TMP/provider.log" release configured
    mkdir -p "$root/srv/museecho/releases" "$root/srv/museecho/config" "$root/etc/museecho/secrets" "$bin"; : > "$log"; make_fake_bin "$bin"
    printf 'MUSEECHO_DOMAIN=example.test\n' > "$root/srv/museecho/config/runtime.env"
    printf 'test-kek' > "$root/etc/museecho/secrets/audio-kek"
    PATH="$bin:$PATH" MUSEECHO_TEST_ROOT="$root" MUSEECHO_TEST_LOG="$log" \
        bash "$DEPLOY_DIR/deploy.sh" --app-image 'registry.example/museecho-app@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
        --gateway-image 'registry.example/museecho-gateway@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' >/dev/null
    release="$(readlink -f "$root/srv/museecho/current")"
    configured="$(docker compose --env-file "$release/release.env" -f "$release/compose.yaml" config)" \
        || fail "compose config should validate KEK-only release"
    assert_not_contains 'MUSEECHO_PROVIDER_SECRET_FILE: /run/secrets/provider-key' "$configured"
    pass "default release leaves optional provider mode disabled"
}

test_backup_excludes_ciphertext_and_has_integrity_metadata() {
    local root="$TEST_TMP/backup-root" bin="$TEST_TMP/backup-bin" log="$TEST_TMP/backup.log" output archive listing
    mkdir -p "$root/srv/museecho/data/audio" "$root/srv/museecho/config" "$bin"; : > "$log"; make_fake_bin "$bin"
    printf 'sqlite-data' > "$root/srv/museecho/data/museecho.db"
    printf 'encrypted-audio' > "$root/srv/museecho/data/audio/opaque.enc"
    printf 'MUSEECHO_DOMAIN=example.test\n' > "$root/srv/museecho/config/runtime.env"
    output="$(PATH="$bin:$PATH" MUSEECHO_TEST_ROOT="$root" MUSEECHO_TEST_LOG="$log" bash "$DEPLOY_DIR/backup.sh" 2>&1)" || fail "backup should pass: $output"
    archive="$(find "$root/srv/museecho/backups" -name '*.tar.gz' -print -quit)"
    assert_file "$archive"
    listing="$(tar -tzf "$archive")"
    assert_contains 'museecho.db' "$listing"
    assert_contains 'SHA256SUMS' "$listing"
    assert_contains 'BACKUP-METADATA.txt' "$listing"
    assert_not_contains 'opaque.enc' "$listing"
    pass "backup excludes encrypted audio and records integrity"
}

test_evidence_is_truthful() {
    local evidence
    evidence="$(<"$ROOT_DIR/DEPLOYMENT_EVIDENCE.md")"
    assert_contains 'No public URL is claimed' "$evidence"
    assert_contains 'Pending real-server evidence' "$evidence"
    pass "deployment evidence distinguishes local and remote status"
}

test_syntax_and_required_artifacts
test_check_only_is_non_mutating
test_install_layout_firewall_and_systemd
test_digest_only_and_secret_safe_deploy
test_failed_health_restores_previous_release
test_default_release_keeps_provider_mode_disabled
test_backup_excludes_ciphertext_and_has_integrity_metadata
test_evidence_is_truthful

if (( failures > 0 )); then
    printf '%s deployment contract test(s) failed\n' "$failures" >&2
    exit 1
fi
printf 'All Tencent Cloud delivery contract tests passed.\n'

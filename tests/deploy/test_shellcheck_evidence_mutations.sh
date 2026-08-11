#!/usr/bin/env bash
# Each required pinned-container fact must be load-bearing in the evidence
# checker.  The copies preserve tracked evidence while exercising mutations.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHECKER="$ROOT_DIR/tests/deploy/test_shellcheck_evidence.sh"
TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

failures=0
fail() { printf 'FAIL: %s\n' "$*" >&2; failures=$((failures + 1)); }

copy_evidence() {
    local destination="$1"
    mkdir -p "$destination/.superpowers/sdd/PLAN"
    cp "$ROOT_DIR/DEPLOYMENT_EVIDENCE.md" "$destination/DEPLOYMENT_EVIDENCE.md"
    cp "$ROOT_DIR/.superpowers/sdd/PLAN/task-21-report.md" "$destination/.superpowers/sdd/PLAN/task-21-report.md"
}

expect_rejected() {
    local label="$1" destination="$2" output
    if output="$(MUSEECHO_EVIDENCE_ROOT="$destination" bash "$CHECKER" 2>&1)"; then
        fail "mutation was accepted: $label"
    else
        printf 'PASS: rejected mutation: %s\n' "$label"
    fi
}

expect_legacy_accepted() {
    local label="$1" destination="$2" legacy_checker="$TEST_TMP/legacy-shellcheck-evidence.sh" output
    cp "$CHECKER" "$legacy_checker"
    sed -i "/assert_contains '--pull=never'/d" "$legacy_checker"
    sed -i '/    for script_path in /,/    done/d' "$legacy_checker"
    if output="$(MUSEECHO_EVIDENCE_ROOT="$destination" bash "$legacy_checker" 2>&1)"; then
        printf 'PASS: legacy checker accepted missing %s evidence\n' "$label"
    else
        fail "legacy checker unexpectedly rejected $label mutation: $output"
    fi
}

mutation_root="$TEST_TMP/pull-never"; copy_evidence "$mutation_root"
sed -i 's/--pull=never/REMOVED-PULL-POLICY/g' "$mutation_root/DEPLOYMENT_EVIDENCE.md"
expect_legacy_accepted '--pull=never' "$mutation_root"
expect_rejected '--pull=never' "$mutation_root"

for script_path in \
    deploy/tencent-cloud/lib.sh \
    deploy/tencent-cloud/install.sh \
    deploy/tencent-cloud/deploy.sh \
    deploy/tencent-cloud/rollback.sh \
    deploy/tencent-cloud/backup.sh; do
    mutation_root="$TEST_TMP/$(basename "$script_path")"; copy_evidence "$mutation_root"
    escaped_path="${script_path//\//\\/}"
    sed -i "0,/$escaped_path/s//REMOVED-SCRIPT-PATH/" "$mutation_root/DEPLOYMENT_EVIDENCE.md"
    expect_legacy_accepted "$script_path" "$mutation_root"
    expect_rejected "$script_path" "$mutation_root"
done

if (( failures > 0 )); then
    printf '%s ShellCheck evidence mutation(s) accepted\n' "$failures" >&2
    exit 1
fi
printf 'ShellCheck evidence mutations rejected.\n'

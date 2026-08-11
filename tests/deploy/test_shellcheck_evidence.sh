#!/usr/bin/env bash
# Evidence contract: the mandatory lint gate must be independently auditable
# from both deployment evidence and the Task 21 implementation report.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE='koalaman/shellcheck-alpine:v0.10.0@sha256:7c6a5115899d99323b22fc84b29e924aef5b6fa985612e450a8c356969ebb577'
VERSION_BANNER='ShellCheck - shell script analysis tool'
VERSION_LINE='version: 0.10.0'

failures=0
fail() { printf 'FAIL: %s\n' "$*" >&2; failures=$((failures + 1)); }
assert_contains() {
    local needle="$1" haystack="$2" label="$3"
    [[ "$haystack" == *"$needle"* ]] || fail "$label is missing: $needle"
}

for evidence_file in DEPLOYMENT_EVIDENCE.md .superpowers/sdd/PLAN/task-21-report.md; do
    evidence="$(<"$ROOT_DIR/$evidence_file")"
    assert_contains "$IMAGE" "$evidence" "$evidence_file"
    assert_contains '--network none' "$evidence" "$evidence_file"
    assert_contains "$VERSION_BANNER" "$evidence" "$evidence_file"
    assert_contains "$VERSION_LINE" "$evidence" "$evidence_file"
    assert_contains 'shellcheck --version' "$evidence" "$evidence_file"
    assert_contains 'lint exit 0' "$evidence" "$evidence_file"
done

if (( failures > 0 )); then
    printf '%s ShellCheck evidence contract failure(s)\n' "$failures" >&2
    exit 1
fi
printf 'ShellCheck evidence contract passed.\n'

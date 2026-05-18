#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SCRIPT="$REPO_ROOT/install.sh"
TEST_TMP=""
LAST_STATUS=0

fail(){
  printf 'not ok - %s\n' "$*" >&2
  if [[ -n "${TEST_TMP:-}" && -f "$TEST_TMP/output.log" ]]; then
    sed 's/^/# /' "$TEST_TMP/output.log" >&2 || true
  fi
  exit 1
}

setup_case(){
  TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-install-test.XXXXXX")"
}

teardown_case(){
  [[ -n "${TEST_TMP:-}" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
  TEST_TMP=""
}

run_install(){
  local bin_dir="$TEST_TMP/bin"
  local docker_base="$TEST_TMP/docker"
  LAST_STATUS=0
  BIN_DIR="$bin_dir" \
    DOCKER_BASE="$docker_base" \
    WUD_SCRIPTS_LINK="$docker_base/wud/scripts" \
    WUD_OUT_DIR="$docker_base/wud/out" \
    "$SCRIPT" > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
}

assert_status(){
  local expected="$1"
  [[ "$LAST_STATUS" == "$expected" ]] || fail "expected status $expected, got $LAST_STATUS"
}

assert_symlink_to(){
  local path="$1" expected="$2" actual
  [[ -L "$path" ]] || fail "expected symlink: $path"
  actual="$(readlink "$path")"
  [[ "$actual" == "$expected" ]] || fail "expected $path -> $expected, got $actual"
}

test_install_creates_expected_links(){
  setup_case
  run_install

  assert_status 0
  assert_symlink_to "$TEST_TMP/bin/updates" "$REPO_ROOT/bin/updates"
  assert_symlink_to "$TEST_TMP/bin/docker-update-from-wud" "$REPO_ROOT/bin/docker-update-from-wud"
  assert_symlink_to "$TEST_TMP/bin/docker-update-from-wud-legacy" "$REPO_ROOT/bin/docker-update-from-wud-legacy"
  assert_symlink_to "$TEST_TMP/docker/wud/scripts" "$REPO_ROOT/wud"
  [[ -d "$TEST_TMP/docker/wud/out" ]] || fail "expected WUD output directory"
  teardown_case
}

test_install_refuses_existing_non_symlink(){
  setup_case
  mkdir -p "$TEST_TMP/bin"
  printf 'do not replace\n' > "$TEST_TMP/bin/updates"

  run_install

  assert_status 1
  [[ ! -L "$TEST_TMP/bin/updates" ]] || fail "non-symlink target was replaced"
  grep -q 'Refusing to replace existing non-symlink' "$TEST_TMP/output.log" || fail "missing refusal message"
  teardown_case
}

run_test(){
  local name="$1"
  printf 'running %s\n' "$name"
  "$name"
  printf 'ok - %s\n' "$name"
}

main(){
  run_test test_install_creates_expected_links
  run_test test_install_refuses_existing_non_symlink
}

trap teardown_case EXIT
main "$@"

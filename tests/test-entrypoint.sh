#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SCRIPT="$REPO_ROOT/entrypoint.sh"
TEST_TMP=""
APP_DIR=""
LAST_STATUS=0

fail(){
  printf 'not ok - %s\n' "$*" >&2
  if [[ -n "${TEST_TMP:-}" && -f "$TEST_TMP/output.log" ]]; then
    sed 's/^/# /' "$TEST_TMP/output.log" >&2 || true
  fi
  exit 1
}

setup_case(){
  TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-entrypoint-test.XXXXXX")"
  APP_DIR="$TEST_TMP/app"
  mkdir -p "$APP_DIR/bin" "$APP_DIR/wud/nested"

  cat > "$APP_DIR/bin/updates" <<'FAKE_UPDATES'
#!/usr/bin/env bash
printf 'updates'
for arg in "$@"; do
  printf ' [%s]' "$arg"
done
printf '\n'
FAKE_UPDATES
  chmod +x "$APP_DIR/bin/updates"

  cat > "$APP_DIR/bin/docker-update-from-wud" <<'FAKE_UPDATER'
#!/usr/bin/env bash
printf 'docker-update-from-wud'
for arg in "$@"; do
  printf ' [%s]' "$arg"
done
printf '\n'
FAKE_UPDATER
  chmod +x "$APP_DIR/bin/docker-update-from-wud"

  cat > "$APP_DIR/bin/docker-update-from-wud-legacy" <<'FAKE_LEGACY_UPDATER'
#!/usr/bin/env bash
printf 'docker-update-from-wud-legacy'
for arg in "$@"; do
  printf ' [%s]' "$arg"
done
printf '\n'
FAKE_LEGACY_UPDATER
  chmod +x "$APP_DIR/bin/docker-update-from-wud-legacy"

  cat > "$APP_DIR/wud/on-update.sh" <<'FAKE_WUD_SCRIPT'
#!/bin/sh
echo on-update
FAKE_WUD_SCRIPT
  cat > "$APP_DIR/wud/append-updates.sh" <<'FAKE_WUD_SCRIPT'
#!/bin/sh
echo append-updates
FAKE_WUD_SCRIPT
  printf 'linuxserver/example|example/example\n' > "$APP_DIR/wud/upstreams.txt"
  printf 'nested file\n' > "$APP_DIR/wud/nested/example.txt"
}

teardown_case(){
  [[ -n "${TEST_TMP:-}" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
  TEST_TMP=""
}

run_entrypoint(){
  LAST_STATUS=0
  WUD_APP_DIR="$APP_DIR" \
    DOCKER_BASE="$TEST_TMP/docker" \
    WUD_OUT_FILE="$TEST_TMP/images.todo" \
    WUD_SCRIPTS_DIR="${WUD_SCRIPTS_DIR-$TEST_TMP/managed-wud}" \
    WUD_SYNC_SCRIPTS="${WUD_SYNC_SCRIPTS:-}" \
    "$SCRIPT" "$@" > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
}

assert_status(){
  local expected="$1"
  [[ "$LAST_STATUS" == "$expected" ]] || fail "expected status $expected, got $LAST_STATUS"
}

assert_output(){
  local expected="$1" actual
  actual="$(cat "$TEST_TMP/output.log")"
  [[ "$actual" == "$expected" ]] || fail "expected output [$expected], got [$actual]"
}

assert_synced_scripts(){
  local dst="${WUD_SCRIPTS_DIR:-$TEST_TMP/managed-wud}"
  [[ -x "$dst/on-update.sh" ]] || fail "expected executable synced on-update.sh"
  [[ -x "$dst/append-updates.sh" ]] || fail "expected executable synced append-updates.sh"
  [[ -f "$dst/upstreams.txt" ]] || fail "expected synced upstreams.txt"
  [[ -f "$dst/nested/example.txt" ]] || fail "expected synced nested file"
}

test_default_runs_updates_dry_run(){
  setup_case
  run_entrypoint
  assert_status 0
  assert_output 'updates [--dry-run]'
  teardown_case
}

test_leading_flag_runs_updates(){
  setup_case
  run_entrypoint --dry-run --file /out/images.todo
  assert_status 0
  assert_output 'updates [--dry-run] [--file] [/out/images.todo]'
  teardown_case
}

test_updates_dispatch_passes_arguments(){
  setup_case
  run_entrypoint updates --yes --allow-tag-updates
  assert_status 0
  assert_output 'updates [--yes] [--allow-tag-updates]'
  teardown_case
}

test_updater_dispatch_injects_missing_paths(){
  setup_case
  run_entrypoint docker-update-from-wud --yes
  assert_status 0
  assert_output "docker-update-from-wud [--base] [$TEST_TMP/docker] [--file] [$TEST_TMP/images.todo] [--yes]"
  teardown_case
}

test_updater_dispatch_preserves_explicit_paths(){
  setup_case
  run_entrypoint docker-update-from-wud --dry-run --base /custom/docker --file /custom/images.todo
  assert_status 0
  assert_output 'docker-update-from-wud [--dry-run] [--base] [/custom/docker] [--file] [/custom/images.todo]'
  teardown_case
}

test_legacy_updater_dispatch_injects_missing_paths(){
  setup_case
  run_entrypoint docker-update-from-wud-legacy --yes
  assert_status 0
  assert_output "docker-update-from-wud-legacy [--base] [$TEST_TMP/docker] [--file] [$TEST_TMP/images.todo] [--yes]"
  teardown_case
}

test_debug_command_executes_directly(){
  setup_case
  run_entrypoint /bin/sh -c "printf 'debug [%s]\n' \"\$1\"" shell arg
  assert_status 0
  assert_output 'debug [arg]'
  teardown_case
}

test_sync_command_copies_scripts_and_exits(){
  setup_case
  run_entrypoint sync-wud-scripts
  assert_status 0
  assert_output "Synced WUD scripts to $TEST_TMP/managed-wud"
  assert_synced_scripts
  teardown_case
}

test_startup_sync_runs_before_command(){
  setup_case
  WUD_SYNC_SCRIPTS=1 run_entrypoint updates --yes
  assert_status 0
  assert_output "Synced WUD scripts to $TEST_TMP/managed-wud
updates [--yes]"
  assert_synced_scripts
  teardown_case
}

test_sync_removes_stale_files(){
  setup_case
  mkdir -p "$TEST_TMP/managed-wud"
  printf 'stale\n' > "$TEST_TMP/managed-wud/stale.txt"
  run_entrypoint sync-wud-scripts
  assert_status 0
  [[ ! -e "$TEST_TMP/managed-wud/stale.txt" ]] || fail "stale file was not removed"
  assert_synced_scripts
  teardown_case
}

test_sync_refuses_unsafe_destination(){
  setup_case
  WUD_SCRIPTS_DIR="$APP_DIR/wud" run_entrypoint sync-wud-scripts
  assert_status 1
  grep -q 'Refusing unsafe WUD_SCRIPTS_DIR' "$TEST_TMP/output.log" || fail "missing unsafe destination message"
  teardown_case
}

test_sync_refuses_empty_destination(){
  setup_case
  WUD_SCRIPTS_DIR="" run_entrypoint sync-wud-scripts
  assert_status 1
  grep -q 'Refusing unsafe WUD_SCRIPTS_DIR: <empty>' "$TEST_TMP/output.log" || fail "missing empty destination message"
  teardown_case
}

run_test(){
  local name="$1"
  printf 'running %s\n' "$name"
  "$name"
  printf 'ok - %s\n' "$name"
}

main(){
  run_test test_default_runs_updates_dry_run
  run_test test_leading_flag_runs_updates
  run_test test_updates_dispatch_passes_arguments
  run_test test_updater_dispatch_injects_missing_paths
  run_test test_updater_dispatch_preserves_explicit_paths
  run_test test_legacy_updater_dispatch_injects_missing_paths
  run_test test_debug_command_executes_directly
  run_test test_sync_command_copies_scripts_and_exits
  run_test test_startup_sync_runs_before_command
  run_test test_sync_removes_stale_files
  run_test test_sync_refuses_unsafe_destination
  run_test test_sync_refuses_empty_destination
}

trap teardown_case EXIT
main "$@"

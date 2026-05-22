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
  mkdir -p "$APP_DIR/bin" "$APP_DIR/wud/nested" "$TEST_TMP/docker" "$TEST_TMP/out"

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

  cat > "$TEST_TMP/python" <<'FAKE_PYTHON'
#!/usr/bin/env bash
printf 'python'
for arg in "$@"; do
  printf ' [%s]' "$arg"
done
printf '\n'
FAKE_PYTHON
  chmod +x "$TEST_TMP/python"

  cat > "$APP_DIR/wud/on-update.sh" <<'FAKE_WUD_SCRIPT'
#!/bin/sh
echo on-update
FAKE_WUD_SCRIPT
  cat > "$APP_DIR/wud/append-updates.sh" <<'FAKE_WUD_SCRIPT'
#!/bin/sh
echo append-updates
FAKE_WUD_SCRIPT
  cat > "$APP_DIR/wud/github-release-embed.sh" <<'FAKE_WUD_SCRIPT'
#!/usr/bin/env bash
echo github-release-embed
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
    WUD_OUT_FILE="$TEST_TMP/out/images.todo" \
    WUD_SCRIPTS_DIR="${WUD_SCRIPTS_DIR-$TEST_TMP/managed-wud}" \
    WUD_SYNC_SCRIPTS="${WUD_SYNC_SCRIPTS:-}" \
    PYTHON_BIN="${PYTHON_BIN:-}" \
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
  [[ -f "$dst/.wud-updater-managed" ]] || fail "expected synced marker file"
  [[ -x "$dst/on-update.sh" ]] || fail "expected executable synced on-update.sh"
  [[ -x "$dst/append-updates.sh" ]] || fail "expected executable synced append-updates.sh"
  [[ -x "$dst/github-release-embed.sh" ]] || fail "expected executable synced github-release-embed.sh"
  [[ -f "$dst/upstreams.txt" ]] || fail "expected synced upstreams.txt"
  [[ -f "$dst/nested/example.txt" ]] || fail "expected synced nested file"
}

assert_refuses_sync_dir(){
  local dir="$1"

  WUD_SCRIPTS_DIR="$dir" run_entrypoint sync-wud-scripts
  assert_status 1
  grep -q 'Refusing unsafe WUD_SCRIPTS_DIR' "$TEST_TMP/output.log" || fail "missing unsafe destination message for $dir"
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

test_truenas_status_export_dispatches_python_cli(){
  setup_case
  PYTHON_BIN="$TEST_TMP/python" run_entrypoint truenas-status-export
  assert_status 0
  assert_output 'python [-m] [wud_updater.cli] [truenas-status-export]'
  teardown_case
}

test_updater_dispatch_injects_missing_paths(){
  setup_case
  run_entrypoint docker-update-from-wud --yes
  assert_status 0
  assert_output "docker-update-from-wud [--base] [$TEST_TMP/docker] [--file] [$TEST_TMP/out/images.todo] [--log-dir] [/logs] [--yes]"
  teardown_case
}

test_updater_dispatch_preserves_explicit_paths(){
  setup_case
  run_entrypoint docker-update-from-wud --dry-run --base /custom/docker --file /custom/images.todo
  assert_status 0
  assert_output 'docker-update-from-wud [--log-dir] [/logs] [--dry-run] [--base] [/custom/docker] [--file] [/custom/images.todo]'
  teardown_case
}

test_updater_dispatch_preserves_explicit_log_dir(){
  setup_case
  WUD_LOG_DIR=/env/logs run_entrypoint docker-update-from-wud --dry-run --log-dir /custom/logs
  assert_status 0
  assert_output "docker-update-from-wud [--base] [$TEST_TMP/docker] [--file] [$TEST_TMP/out/images.todo] [--dry-run] [--log-dir] [/custom/logs]"
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
  WUD_SYNC_SCRIPTS=true run_entrypoint updates --yes
  assert_status 0
  assert_output "Synced WUD scripts to $TEST_TMP/managed-wud
updates [--yes]"
  assert_synced_scripts
  teardown_case
}

test_startup_sync_accepts_legacy_one(){
  setup_case
  WUD_SYNC_SCRIPTS=1 run_entrypoint updates --yes
  assert_status 0
  assert_output "Synced WUD scripts to $TEST_TMP/managed-wud
updates [--yes]"
  assert_synced_scripts
  teardown_case
}

test_startup_sync_accepts_legacy_zero_as_disabled(){
  setup_case
  WUD_SYNC_SCRIPTS=0 run_entrypoint updates --yes
  assert_status 0
  assert_output 'updates [--yes]'
  [[ ! -e "$TEST_TMP/managed-wud/.wud-updater-managed" ]] || fail "legacy zero enabled sync"
  teardown_case
}

test_sync_removes_stale_files(){
  setup_case
  mkdir -p "$TEST_TMP/managed-wud"
  printf 'managed\n' > "$TEST_TMP/managed-wud/.wud-updater-managed"
  printf 'stale\n' > "$TEST_TMP/managed-wud/stale.txt"
  run_entrypoint sync-wud-scripts
  assert_status 0
  [[ ! -e "$TEST_TMP/managed-wud/stale.txt" ]] || fail "stale file was not removed"
  assert_synced_scripts
  teardown_case
}

test_sync_refuses_non_empty_unmanaged_destination(){
  setup_case
  mkdir -p "$TEST_TMP/unmanaged"
  printf 'keep\n' > "$TEST_TMP/unmanaged/existing.txt"
  WUD_SCRIPTS_DIR="$TEST_TMP/unmanaged" run_entrypoint sync-wud-scripts
  assert_status 1
  grep -q 'Refusing to sync into non-empty unmanaged WUD_SCRIPTS_DIR' "$TEST_TMP/output.log" || fail "missing unmanaged destination message"
  [[ -f "$TEST_TMP/unmanaged/existing.txt" ]] || fail "unmanaged file was removed"
  [[ ! -e "$TEST_TMP/unmanaged/on-update.sh" ]] || fail "scripts were copied to unmanaged directory"
  teardown_case
}

test_sync_refuses_empty_destination(){
  setup_case
  WUD_SCRIPTS_DIR="" run_entrypoint sync-wud-scripts
  assert_status 1
  grep -q 'Refusing unsafe WUD_SCRIPTS_DIR: <empty>' "$TEST_TMP/output.log" || fail "missing empty destination message"
  teardown_case
}

test_sync_refuses_reserved_destinations(){
  setup_case
  mkdir -p "$APP_DIR/subdir" "$TEST_TMP/docker/subdir" "$TEST_TMP/out/subdir" "$TEST_TMP/managed-wud"
  assert_refuses_sync_dir /
  assert_refuses_sync_dir "$APP_DIR"
  assert_refuses_sync_dir "$APP_DIR/subdir"
  assert_refuses_sync_dir "$TEST_TMP/docker"
  assert_refuses_sync_dir "$TEST_TMP/docker/subdir"
  assert_refuses_sync_dir "$TEST_TMP/out"
  assert_refuses_sync_dir "$TEST_TMP/out/subdir"
  assert_refuses_sync_dir "$APP_DIR/../out"
  assert_refuses_sync_dir "$TEST_TMP/managed-wud/../out"
  teardown_case
}

test_sync_refuses_symlinked_reserved_destination(){
  setup_case
  ln -s "$TEST_TMP/out" "$TEST_TMP/out-link"
  assert_refuses_sync_dir "$TEST_TMP/out-link"
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
  run_test test_truenas_status_export_dispatches_python_cli
  run_test test_updater_dispatch_injects_missing_paths
  run_test test_updater_dispatch_preserves_explicit_paths
  run_test test_updater_dispatch_preserves_explicit_log_dir
  run_test test_debug_command_executes_directly
  run_test test_sync_command_copies_scripts_and_exits
  run_test test_startup_sync_runs_before_command
  run_test test_startup_sync_accepts_legacy_one
  run_test test_startup_sync_accepts_legacy_zero_as_disabled
  run_test test_sync_removes_stale_files
  run_test test_sync_refuses_non_empty_unmanaged_destination
  run_test test_sync_refuses_empty_destination
  run_test test_sync_refuses_reserved_destinations
  run_test test_sync_refuses_symlinked_reserved_destination
}

trap teardown_case EXIT
main "$@"

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
  mkdir -p "$APP_DIR/bin"

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

test_debug_command_executes_directly(){
  setup_case
  run_entrypoint /bin/sh -c "printf 'debug [%s]\n' \"\$1\"" shell arg
  assert_status 0
  assert_output 'debug [arg]'
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
  run_test test_debug_command_executes_directly
}

trap teardown_case EXIT
main "$@"

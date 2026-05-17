#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SCRIPT="$REPO_ROOT/bin/updates"
TEST_TMP=""
FAKE_BIN=""
WUD_FILE=""
LAST_STATUS=0

fail(){
  printf 'not ok - %s\n' "$*" >&2
  if [[ -n "${TEST_TMP:-}" && -f "$TEST_TMP/output.log" ]]; then
    sed 's/^/# /' "$TEST_TMP/output.log" >&2 || true
  fi
  exit 1
}

setup_case(){
  TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-updates-wrapper-test.XXXXXX")"
  FAKE_BIN="$TEST_TMP/bin"
  WUD_FILE="$TEST_TMP/images.todo"
  mkdir -p "$FAKE_BIN"

  cat > "$FAKE_BIN/column" <<'FAKE_COLUMN'
#!/usr/bin/env bash
if [[ -n "${FAKE_COLUMN_LOCK_LOG:-}" ]]; then
  if [[ -d "${FAKE_WUD_FILE:?FAKE_WUD_FILE is required}.lock" ]]; then
    printf 'present\n' >> "$FAKE_COLUMN_LOCK_LOG"
  else
    printf 'missing\n' >> "$FAKE_COLUMN_LOCK_LOG"
  fi
fi
cat
if [[ -n "${FAKE_COLUMN_HOOK:-}" ]]; then
  "$FAKE_COLUMN_HOOK"
fi
FAKE_COLUMN
  chmod +x "$FAKE_BIN/column"

  cat > "$FAKE_BIN/sudo" <<'FAKE_SUDO'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${FAKE_SUDO_LOG:?FAKE_SUDO_LOG is required}"
"$@"
FAKE_SUDO
  chmod +x "$FAKE_BIN/sudo"

  cat > "$TEST_TMP/updater" <<'FAKE_UPDATER'
#!/usr/bin/env bash
args=("$@")
wud_file=""
while (($#)); do
  case "$1" in
    --file)
      wud_file="${2:-}"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
printf 'OUT_UID=%s OUT_GID=%s OUT_GUID=%s WUD_LOCK_TIMEOUT=%s WUD_LOCK_HELD_BY_PARENT=%s\n' "${OUT_UID:-}" "${OUT_GID:-}" "${OUT_GUID:-}" "${WUD_LOCK_TIMEOUT:-}" "${WUD_LOCK_HELD_BY_PARENT:-}" >> "${FAKE_UPDATER_LOG:?FAKE_UPDATER_LOG is required}"
if [[ "${FAKE_UPDATER_ASSERT_LOCK:-}" = "1" ]]; then
  if [[ "${WUD_LOCK_HELD_BY_PARENT:-}" != "1" ]]; then
    printf 'missing WUD_LOCK_HELD_BY_PARENT\n' >> "$FAKE_UPDATER_LOG"
    exit 21
  fi
  if [[ -z "$wud_file" || ! -d "${wud_file}.lock" ]]; then
    printf 'missing WUD file lock\n' >> "$FAKE_UPDATER_LOG"
    exit 22
  fi
fi
printf '%s\n' "${args[*]}" >> "${FAKE_UPDATER_LOG:?FAKE_UPDATER_LOG is required}"
exit 0
FAKE_UPDATER
  chmod +x "$TEST_TMP/updater"
}

teardown_case(){
  [[ -n "${TEST_TMP:-}" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
  TEST_TMP=""
}

run_updates(){
  local env_args=()
  while [[ "$#" -gt 0 && "$1" == *=* ]]; do
    env_args+=("$1")
    shift
  done

  LAST_STATUS=0
  if ((${#env_args[@]})); then
    PATH="$FAKE_BIN:$PATH" \
      WUD_UPDATER="$TEST_TMP/updater" \
      FAKE_SUDO_LOG="$TEST_TMP/sudo.log" \
      FAKE_UPDATER_LOG="$TEST_TMP/updater.log" \
      FAKE_WUD_FILE="$WUD_FILE" \
      env "${env_args[@]}" "$SCRIPT" --file "$WUD_FILE" "$@" > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
  else
    PATH="$FAKE_BIN:$PATH" \
      WUD_UPDATER="$TEST_TMP/updater" \
      FAKE_SUDO_LOG="$TEST_TMP/sudo.log" \
      FAKE_UPDATER_LOG="$TEST_TMP/updater.log" \
      FAKE_WUD_FILE="$WUD_FILE" \
      "$SCRIPT" --file "$WUD_FILE" "$@" > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
  fi
}

run_updates_with_input(){
  local input="$1"
  shift
  local env_args=()
  while [[ "$#" -gt 0 && "$1" == *=* ]]; do
    env_args+=("$1")
    shift
  done

  LAST_STATUS=0
  if ((${#env_args[@]})); then
    printf '%b' "$input" | PATH="$FAKE_BIN:$PATH" \
      WUD_UPDATER="$TEST_TMP/updater" \
      FAKE_SUDO_LOG="$TEST_TMP/sudo.log" \
      FAKE_UPDATER_LOG="$TEST_TMP/updater.log" \
      FAKE_WUD_FILE="$WUD_FILE" \
      env "${env_args[@]}" "$SCRIPT" --file "$WUD_FILE" "$@" > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
  else
    printf '%b' "$input" | PATH="$FAKE_BIN:$PATH" \
      WUD_UPDATER="$TEST_TMP/updater" \
      FAKE_SUDO_LOG="$TEST_TMP/sudo.log" \
      FAKE_UPDATER_LOG="$TEST_TMP/updater.log" \
      FAKE_WUD_FILE="$WUD_FILE" \
      "$SCRIPT" --file "$WUD_FILE" "$@" > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
  fi
}

assert_status(){
  local expected="$1"
  [[ "$LAST_STATUS" == "$expected" ]] || fail "expected status $expected, got $LAST_STATUS"
}

test_dry_run_does_not_invoke_updater(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"

  run_updates --dry-run

  assert_status 0
  [[ ! -e "$TEST_TMP/sudo.log" ]] || fail "sudo was invoked during dry-run"
  [[ ! -e "$TEST_TMP/updater.log" ]] || fail "updater was invoked during dry-run"
  grep -q 'Dry-run mode: not running updates' "$TEST_TMP/output.log" || fail "missing dry-run message"
  teardown_case
}

test_yes_invokes_configured_updater_through_sudo(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"

  run_updates --yes --base "$TEST_TMP/docker" --mode live --max-wait 7

  assert_status 0
  grep -q -- "$TEST_TMP/updater --base $TEST_TMP/docker --file $WUD_FILE --mode live --max-wait 7 --yes" "$TEST_TMP/sudo.log" || fail "sudo did not receive expected updater command"
  grep -q -- "--base $TEST_TMP/docker --file $WUD_FILE --mode live --max-wait 7 --yes" "$TEST_TMP/updater.log" || fail "updater did not receive expected arguments"
  teardown_case
}

test_yes_passes_owner_config_through_sudo_env(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"

  run_updates OUT_UID=1000 OUT_GUID=1000 --yes --base "$TEST_TMP/docker"

  assert_status 0
  grep -q -- "env OUT_UID=1000 OUT_GID=1000 $TEST_TMP/updater --base $TEST_TMP/docker --file $WUD_FILE --mode stop --max-wait 180 --yes" "$TEST_TMP/sudo.log" || fail "sudo did not receive expected owner env"
  grep -q -- "OUT_UID=1000 OUT_GID=1000 OUT_GUID=" "$TEST_TMP/updater.log" || fail "updater did not receive owner env"
  teardown_case
}

test_yes_passes_lock_timeout_through_sudo_env(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"

  run_updates WUD_LOCK_TIMEOUT=0 --yes --base "$TEST_TMP/docker"

  assert_status 0
  grep -q -- "env WUD_LOCK_TIMEOUT=0 $TEST_TMP/updater --base $TEST_TMP/docker --file $WUD_FILE --mode stop --max-wait 180 --yes" "$TEST_TMP/sudo.log" || fail "sudo did not receive expected lock timeout env"
  grep -q -- "WUD_LOCK_TIMEOUT=0" "$TEST_TMP/updater.log" || fail "updater did not receive lock timeout env"
  teardown_case
}

test_interactive_all_preserves_default_updater_args(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"

  run_updates_with_input 'a\n' --base "$TEST_TMP/docker"

  assert_status 0
  grep -q -- "$TEST_TMP/updater --base $TEST_TMP/docker --file $WUD_FILE --mode stop --max-wait 180 --yes" "$TEST_TMP/sudo.log" || fail "sudo did not receive default all-selection updater command"
  grep -q -- "--base $TEST_TMP/docker --file $WUD_FILE --mode stop --max-wait 180 --yes" "$TEST_TMP/updater.log" || fail "updater did not receive default all-selection arguments"
  teardown_case
}

test_interactive_display_uses_snapshot_without_holding_wud_lock(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"

  run_updates_with_input 'n\n' FAKE_COLUMN_LOCK_LOG="$TEST_TMP/column-lock.log" --base "$TEST_TMP/docker"

  assert_status 0
  grep -qx 'missing' "$TEST_TMP/column-lock.log" || fail "pending updates were displayed while holding the WUD lock"
  [[ ! -d "$WUD_FILE.lock" ]] || fail "WUD lock was not released after skip"
  teardown_case
}

test_interactive_display_hides_legacy_sha_suffix(){
  setup_case
  printf 'repo/app:latest sha256=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' > "$WUD_FILE"

  run_updates_with_input 'n\n' --base "$TEST_TMP/docker"

  assert_status 0
  grep -q 'repo/app:latest' "$TEST_TMP/output.log" || fail "pending update was not displayed"
  ! grep -q 'sha256=' "$TEST_TMP/output.log" || fail "legacy sha suffix was displayed"
  teardown_case
}

test_interactive_holds_wud_lock_for_updater_handoff(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"

  run_updates_with_input 's\n1\nn\n' FAKE_UPDATER_ASSERT_LOCK=1 --base "$TEST_TMP/docker"

  assert_status 0
  grep -q -- "WUD_LOCK_HELD_BY_PARENT=1" "$TEST_TMP/updater.log" || fail "updater did not receive parent lock marker"
  [[ ! -d "$WUD_FILE.lock" ]] || fail "WUD lock was not released after updater handoff"
  teardown_case
}

test_interactive_select_passes_original_line_numbers(){
  setup_case
  {
    printf '# comment\n'
    printf 'repo/app:one\n'
    printf '\n'
    printf 'repo/app:two\n'
    printf 'repo/app:three\n'
  } > "$WUD_FILE"

  run_updates_with_input 's\n1,3\nn\n' --base "$TEST_TMP/docker"

  assert_status 0
  grep -q -- "--only-lines 2,5 --yes" "$TEST_TMP/sudo.log" || fail "sudo did not receive selected original line numbers"
  grep -q -- "--only-lines 2,5" "$TEST_TMP/updater.log" || fail "updater did not receive selected original line numbers"
  teardown_case
}

test_interactive_exclude_passes_complement_line_numbers(){
  setup_case
  {
    printf 'repo/app:one\n'
    printf '# comment\n'
    printf 'repo/app:two\n'
    printf 'repo/app:three\n'
  } > "$WUD_FILE"

  run_updates_with_input 'x\n2\nn\n' --base "$TEST_TMP/docker"

  assert_status 0
  grep -q -- "--only-lines 1,4 --yes" "$TEST_TMP/sudo.log" || fail "sudo did not receive complement line numbers"
  grep -q -- "--only-lines 1,4" "$TEST_TMP/updater.log" || fail "updater did not receive complement line numbers"
  teardown_case
}

test_interactive_remove_unselected_passes_remove_lines(){
  setup_case
  {
    printf 'repo/app:one\n'
    printf 'repo/app:two\n'
    printf 'repo/app:three\n'
  } > "$WUD_FILE"

  run_updates_with_input 's\n2\ny\n' --base "$TEST_TMP/docker"

  assert_status 0
  grep -q -- "--only-lines 2 --remove-lines-before-run 1,3 --yes" "$TEST_TMP/sudo.log" || fail "sudo did not receive remove-lines arguments"
  grep -q -- "--remove-lines-before-run 1,3" "$TEST_TMP/updater.log" || fail "updater did not receive remove-lines arguments"
  teardown_case
}

test_interactive_select_aborts_when_snapshot_lines_change(){
  setup_case
  {
    printf 'repo/app:one\n'
    printf 'repo/app:two\n'
  } > "$WUD_FILE"
  cat > "$TEST_TMP/change-wud-file" <<HOOK
#!/usr/bin/env bash
printf 'repo/app:changed\nrepo/app:two\n' > "$WUD_FILE"
HOOK
  chmod +x "$TEST_TMP/change-wud-file"

  run_updates_with_input 's\n1\nn\n' FAKE_COLUMN_HOOK="$TEST_TMP/change-wud-file" --base "$TEST_TMP/docker"

  assert_status 1
  grep -q 'WUD file changed while selecting updates; please rerun updates.' "$TEST_TMP/output.log" || fail "missing changed-file validation message"
  [[ ! -e "$TEST_TMP/sudo.log" ]] || fail "sudo was invoked after selected line changed"
  [[ ! -d "$WUD_FILE.lock" ]] || fail "WUD lock was not released after validation failure"
  teardown_case
}

run_test(){
  local name="$1"
  printf 'running %s\n' "$name"
  "$name"
  printf 'ok - %s\n' "$name"
}

main(){
  run_test test_dry_run_does_not_invoke_updater
  run_test test_yes_invokes_configured_updater_through_sudo
  run_test test_yes_passes_owner_config_through_sudo_env
  run_test test_yes_passes_lock_timeout_through_sudo_env
  run_test test_interactive_all_preserves_default_updater_args
  run_test test_interactive_display_uses_snapshot_without_holding_wud_lock
  run_test test_interactive_display_hides_legacy_sha_suffix
  run_test test_interactive_holds_wud_lock_for_updater_handoff
  run_test test_interactive_select_passes_original_line_numbers
  run_test test_interactive_exclude_passes_complement_line_numbers
  run_test test_interactive_remove_unselected_passes_remove_lines
  run_test test_interactive_select_aborts_when_snapshot_lines_change
}

trap teardown_case EXIT
main "$@"

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
cat
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
printf '%s\n' "$*" >> "${FAKE_UPDATER_LOG:?FAKE_UPDATER_LOG is required}"
exit 0
FAKE_UPDATER
  chmod +x "$TEST_TMP/updater"
}

teardown_case(){
  [[ -n "${TEST_TMP:-}" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
  TEST_TMP=""
}

run_updates(){
  LAST_STATUS=0
  PATH="$FAKE_BIN:$PATH" \
    WUD_UPDATER="$TEST_TMP/updater" \
    FAKE_SUDO_LOG="$TEST_TMP/sudo.log" \
    FAKE_UPDATER_LOG="$TEST_TMP/updater.log" \
    "$SCRIPT" --file "$WUD_FILE" "$@" > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
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

run_test(){
  local name="$1"
  printf 'running %s\n' "$name"
  "$name"
  printf 'ok - %s\n' "$name"
}

main(){
  run_test test_dry_run_does_not_invoke_updater
  run_test test_yes_invokes_configured_updater_through_sudo
}

trap teardown_case EXIT
main "$@"

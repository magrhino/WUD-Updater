#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SCRIPT="$REPO_ROOT/bin/updates"
TEST_TMP=""
LAST_STATUS=0

fail(){
  printf 'not ok - %s\n' "$*" >&2
  if [[ -n "${TEST_TMP:-}" && -f "$TEST_TMP/output.log" ]]; then
    sed 's/^/# /' "$TEST_TMP/output.log" >&2 || true
  fi
  if [[ -n "${TEST_TMP:-}" && -f "$TEST_TMP/python.log" ]]; then
    sed 's/^/# python: /' "$TEST_TMP/python.log" >&2 || true
  fi
  exit 1
}

setup_case(){
  TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-updates-launcher-test.XXXXXX")"
  mkdir -p "$TEST_TMP/bin" "$TEST_TMP/venv/bin"
}

teardown_case(){
  [[ -n "${TEST_TMP:-}" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
  TEST_TMP=""
}

write_fake_python(){
  local path="$1"
  cat > "$path" <<'FAKE_PYTHON'
#!/usr/bin/env bash
if [[ "${1:-}" == "-" ]]; then
  exit "${FAKE_PYTHON_PROBE_STATUS:-0}"
fi
{
  printf 'python=%s\n' "$0"
  printf 'argv=%s\n' "$*"
  printf 'PYTHONPATH=%s\n' "${PYTHONPATH:-}"
  printf 'CONFIG_SENTINEL=%s\n' "${CONFIG_SENTINEL:-}"
} >> "${FAKE_PYTHON_LOG:?FAKE_PYTHON_LOG is required}"
exit "${FAKE_PYTHON_STATUS:-0}"
FAKE_PYTHON
  chmod +x "$path"
}

run_script(){
  LAST_STATUS=0
  "$@" > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
}

assert_status(){
  local expected="$1"
  [[ "$LAST_STATUS" == "$expected" ]] || fail "expected status $expected, got $LAST_STATUS"
}

test_dispatches_python_cli(){
  setup_case
  local fake_python="$TEST_TMP/bin/python"
  write_fake_python "$fake_python"

  run_script env \
    PYTHON_BIN="$fake_python" \
    WUDUP_CONFIG="$TEST_TMP/missing-env" \
    FAKE_PYTHON_LOG="$TEST_TMP/python.log" \
    "$SCRIPT" --dry-run

  assert_status 0
  grep -q '^argv=-m wudup.cli updates --dry-run$' "$TEST_TMP/python.log" || fail "launcher did not dispatch updates subcommand"
  grep -q "^PYTHONPATH=$REPO_ROOT/src$" "$TEST_TMP/python.log" || fail "launcher did not add repo src to PYTHONPATH"
  teardown_case
}

test_sources_config_before_dispatch(){
  setup_case
  local config_python="$TEST_TMP/bin/config-python"
  write_fake_python "$config_python"
  {
    printf 'PYTHON_BIN="%s"\n' "$config_python"
    printf 'export CONFIG_SENTINEL="from-config"\n'
  } > "$TEST_TMP/env"

  run_script env \
    WUDUP_CONFIG="$TEST_TMP/env" \
    FAKE_PYTHON_LOG="$TEST_TMP/python.log" \
    "$SCRIPT" --dry-run

  assert_status 0
  grep -q "^python=$config_python$" "$TEST_TMP/python.log" || fail "config PYTHON_BIN was not used"
  grep -q '^CONFIG_SENTINEL=from-config$' "$TEST_TMP/python.log" || fail "config variables were not exported to Python"
  teardown_case
}

test_config_file_argument_sources_explicit_config_before_dispatch(){
  setup_case
  local default_python="$TEST_TMP/bin/default-python"
  local explicit_python="$TEST_TMP/bin/explicit-python"
  write_fake_python "$default_python"
  write_fake_python "$explicit_python"
  {
    printf 'PYTHON_BIN="%s"\n' "$default_python"
    printf 'export CONFIG_SENTINEL="from-default"\n'
  } > "$TEST_TMP/default-env"
  {
    printf 'PYTHON_BIN="%s"\n' "$explicit_python"
    printf 'export CONFIG_SENTINEL="from-explicit"\n'
  } > "$TEST_TMP/explicit-env"

  run_script env \
    WUDUP_CONFIG="$TEST_TMP/default-env" \
    FAKE_PYTHON_LOG="$TEST_TMP/python.log" \
    "$SCRIPT" --config-file "$TEST_TMP/explicit-env" --dry-run

  assert_status 0
  grep -q "^python=$explicit_python$" "$TEST_TMP/python.log" || fail "--config-file did not choose explicit config before dispatch"
  grep -q '^CONFIG_SENTINEL=from-explicit$' "$TEST_TMP/python.log" || fail "explicit config variables were not exported to Python"
  grep -q "^argv=-m wudup.cli updates --config-file $TEST_TMP/explicit-env --dry-run$" "$TEST_TMP/python.log" || fail "launcher did not preserve --config-file arguments"
  teardown_case
}

test_installed_symlink_resolves_repo_src(){
  setup_case
  local fake_python="$TEST_TMP/bin/python"
  local installed_bin="$TEST_TMP/installed-bin"
  write_fake_python "$fake_python"
  mkdir -p "$installed_bin"
  ln -s "$SCRIPT" "$installed_bin/updates"

  run_script env \
    PYTHON_BIN="$fake_python" \
    PYTHONPATH="$TEST_TMP/existing-pythonpath" \
    WUDUP_CONFIG="$TEST_TMP/missing-env" \
    FAKE_PYTHON_LOG="$TEST_TMP/python.log" \
    "$installed_bin/updates" --dry-run

  assert_status 0
  grep -q "^PYTHONPATH=$REPO_ROOT/src:$TEST_TMP/existing-pythonpath$" "$TEST_TMP/python.log" || fail "symlinked launcher did not prepend repo src"
  teardown_case
}

test_legacy_python_false_does_not_disable_python_dispatch(){
  setup_case
  local fake_python="$TEST_TMP/bin/python"
  write_fake_python "$fake_python"

  run_script env \
    PYTHON_BIN="$fake_python" \
    WUDUP_CONFIG="$TEST_TMP/missing-env" \
    WUDUP_PYTHON=false \
    FAKE_PYTHON_LOG="$TEST_TMP/python.log" \
    "$SCRIPT" --dry-run --no-updater-sudo

  assert_status 0
  grep -q '^argv=-m wudup.cli updates --dry-run --no-updater-sudo$' "$TEST_TMP/python.log" || fail "legacy env var disabled or altered Python dispatch"
  teardown_case
}

test_uses_configured_venv_when_python3_lacks_runtime_deps(){
  setup_case
  local system_python="$TEST_TMP/bin/python3"
  local venv_python="$TEST_TMP/venv/bin/python"
  write_fake_python "$system_python"
  write_fake_python "$venv_python"

  run_script env \
    PATH="$TEST_TMP/bin:$PATH" \
    PYTHON_BIN= \
    WUDUP_CONFIG="$TEST_TMP/missing-env" \
    WUDUP_VENV="$TEST_TMP/venv" \
    FAKE_PYTHON_LOG="$TEST_TMP/python.log" \
    FAKE_PYTHON_PROBE_STATUS=1 \
    "$SCRIPT" --dry-run

  assert_status 0
  grep -q "^python=$venv_python$" "$TEST_TMP/python.log" || fail "venv python was not used when python3 lacked deps"
  teardown_case
}

run_test(){
  local name="$1"
  printf 'running %s\n' "$name"
  "$name"
  printf 'ok - %s\n' "$name"
}

main(){
  run_test test_dispatches_python_cli
  run_test test_sources_config_before_dispatch
  run_test test_config_file_argument_sources_explicit_config_before_dispatch
  run_test test_installed_symlink_resolves_repo_src
  run_test test_legacy_python_false_does_not_disable_python_dispatch
  run_test test_uses_configured_venv_when_python3_lacks_runtime_deps
}

trap teardown_case EXIT
main "$@"

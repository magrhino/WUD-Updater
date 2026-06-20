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
  local python_bin="${PYTHON_BIN:-$TEST_TMP/python-with-deps}"
  if [[ ! -e "$python_bin" ]]; then
    write_python_with_runtime_deps "$python_bin"
  fi
  LAST_STATUS=0
  BIN_DIR="$bin_dir" \
    DOCKER_BASE="$docker_base" \
    WUD_SCRIPTS_LINK="$docker_base/wud/scripts" \
    WUD_OUT_DIR="$docker_base/wud/out" \
    WUDUP_VENV="$TEST_TMP/.venv" \
    PYTHON_BIN="$python_bin" \
    FAKE_PYTHON_LOG="$TEST_TMP/python.log" \
    "$SCRIPT" > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
}

write_python_with_runtime_deps(){
  local path="$1"
  cat > "$path" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$path"
}

write_python_creates_venv(){
  local path="$1"
  cat > "$path" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'host:%s\n' "$*" >> "${FAKE_PYTHON_LOG:?}"
if [[ "${1:-}" == "-" ]]; then
  probe="$(cat)"
  if [[ "$probe" == *"import rich"* ]]; then
    exit 1
  fi
  exit 0
fi
if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then
  venv_dir="${3:?}"
  mkdir -p "$venv_dir/bin"
  cat > "$venv_dir/bin/python" <<'VENVEOF'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'venv:%s\n' "$*" >> "${FAKE_PYTHON_LOG:?}"
if [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then
  exit 0
fi
exit 0
VENVEOF
  chmod +x "$venv_dir/bin/python"
  exit 0
fi
exit 1
EOF
  chmod +x "$path"
}

write_python_missing_runtime_deps(){
  local path="$1"
  cat > "$path" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'host:%s\n' "$*" >> "${FAKE_PYTHON_LOG:?}"
exit 1
EOF
  chmod +x "$path"
}

write_python_runtime_venv_probe(){
  local path="$1"
  cat > "$path" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'venv:%s\n' "$*" >> "${FAKE_PYTHON_LOG:?}"
if (($# == 0)); then
  exit 0
fi
exit 42
EOF
  chmod +x "$path"
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
  assert_symlink_to "$TEST_TMP/docker/wud/scripts" "$REPO_ROOT/wud"
  [[ -d "$TEST_TMP/docker/wud/out" ]] || fail "expected WUD output directory"
  teardown_case
}

test_install_creates_local_venv_when_runtime_deps_missing(){
  setup_case
  local fake_python="$TEST_TMP/python-missing-deps"
  write_python_creates_venv "$fake_python"

  PYTHON_BIN="$fake_python" run_install

  assert_status 0
  [[ -x "$TEST_TMP/.venv/bin/python" ]] || fail "expected installer-created venv python"
  grep -q -- "Installing Python runtime dependencies into: $TEST_TMP/.venv" "$TEST_TMP/output.log" || fail "missing venv install message"
  grep -q -- "host:-m venv $TEST_TMP/.venv" "$TEST_TMP/python.log" || fail "venv command was not run"
  grep -q -- "venv:-m pip install -e $REPO_ROOT" "$TEST_TMP/python.log" || fail "pip install was not run"
  teardown_case
}

test_dispatchers_use_local_venv_when_host_python_lacks_deps(){
  setup_case
  local fake_bin="$TEST_TMP/fake-bin"
  local venv_dir="$TEST_TMP/.venv"
  mkdir -p "$fake_bin" "$venv_dir/bin"
  write_python_missing_runtime_deps "$fake_bin/python3"
  write_python_runtime_venv_probe "$venv_dir/bin/python"

  LAST_STATUS=0
  (
    unset PYTHON_BIN
    PATH="$fake_bin:$PATH" \
      WUDUP_VENV="$venv_dir" \
      FAKE_PYTHON_LOG="$TEST_TMP/python.log" \
      "$REPO_ROOT/bin/docker-update-from-wud" --dry-run
  ) > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
  [[ "$LAST_STATUS" == "42" ]] || fail "expected docker-update-from-wud to use fake venv python"
  grep -q -- "host:" "$TEST_TMP/python.log" || fail "host python dependency probe was not run"
  grep -q -- "venv:-m wudup.cli update-from-wud --dry-run" "$TEST_TMP/python.log" || fail "updater wrapper did not use venv python"

  : > "$TEST_TMP/python.log"
  LAST_STATUS=0
  (
    unset PYTHON_BIN
    PATH="$fake_bin:$PATH" \
      WUDUP_VENV="$venv_dir" \
      WUDUP_CONFIG="$TEST_TMP/missing-config" \
      FAKE_PYTHON_LOG="$TEST_TMP/python.log" \
      "$REPO_ROOT/bin/updates" --dry-run
  ) > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
  [[ "$LAST_STATUS" == "42" ]] || fail "expected updates to use fake venv python"
  grep -q -- "host:" "$TEST_TMP/python.log" || fail "updates host python dependency probe was not run"
  grep -q -- "venv:-m wudup.cli updates --dry-run" "$TEST_TMP/python.log" || fail "updates wrapper did not use venv python"
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
  run_test test_install_creates_local_venv_when_runtime_deps_missing
  run_test test_dispatchers_use_local_venv_when_host_python_lacks_deps
  run_test test_install_refuses_existing_non_symlink
}

trap teardown_case EXIT
main "$@"

#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$REPO_ROOT"

run(){
  printf '==> %s\n' "$*"
  "$@"
}

python_bin="${PYTHON_BIN:-}"
if [ -z "$python_bin" ]; then
  if command -v python3.14 >/dev/null 2>&1; then
    python_bin="python3.14"
  elif command -v python3.13 >/dev/null 2>&1; then
    python_bin="python3.13"
  elif command -v python3.12 >/dev/null 2>&1; then
    python_bin="python3.12"
  elif command -v python3.11 >/dev/null 2>&1; then
    python_bin="python3.11"
  elif command -v python3.10 >/dev/null 2>&1; then
    python_bin="python3.10"
  elif command -v python3 >/dev/null 2>&1; then
    python_bin="python3"
  else
    cat >&2 <<'EOF'
Python 3.10 or newer is required to run the Python package tests.
EOF
    exit 127
  fi
fi

run "$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else "Python 3.10 or newer is required")'

if ! command -v shellcheck >/dev/null 2>&1; then
  cat >&2 <<'EOF'
shellcheck is required to run the full test suite.
Install it with your package manager, for example:
  brew install shellcheck
  sudo apt-get install shellcheck
EOF
  exit 127
fi

run bash -n \
  entrypoint.sh \
  install.sh \
  bin/updates \
  bin/docker-update-from-wud \
  wud/tag-manager.sh \
  wud/lsio-release-embed.sh \
  wud/release-notes-to-discord.sh \
  tests/run-all.sh \
  tests/test-docker-update-from-wud.sh \
  tests/container-build.sh \
  tests/test-entrypoint.sh \
  tests/test-release-notes-to-discord.sh \
  tests/test-wud-append-updates.sh \
  tests/test-install.sh \
  tests/test-updates-wrapper.sh \
  tests/fakes/docker

run sh -n \
  wud/on-update.sh \
  wud/append-updates.sh

run shellcheck \
  entrypoint.sh \
  install.sh \
  bin/updates \
  bin/docker-update-from-wud \
  wud/on-update.sh \
  wud/append-updates.sh \
  wud/tag-manager.sh \
  wud/lsio-release-embed.sh \
  wud/release-notes-to-discord.sh \
  tests/run-all.sh \
  tests/test-docker-update-from-wud.sh \
  tests/container-build.sh \
  tests/test-entrypoint.sh \
  tests/test-release-notes-to-discord.sh \
  tests/test-wud-append-updates.sh \
  tests/test-install.sh \
  tests/test-updates-wrapper.sh \
  tests/fakes/docker

run "$python_bin" -m py_compile \
  src/wud_updater/__init__.py \
  src/wud_updater/cli.py \
  src/wud_updater/config.py \
  src/wud_updater/file_ops.py \
  src/wud_updater/images.py \
  src/wud_updater/line_specs.py \
  src/wud_updater/locks.py \
  src/wud_updater/wud_file.py \
  tests/run-python-tests.py \
  tests/test_python_cli.py \
  tests/test_python_config.py \
  tests/test_python_wud_file_ops.py \
  tests/test_python_wud_parsing.py

run "$python_bin" tests/run-python-tests.py

for test_script in tests/test-*.sh; do
  run "$test_script"
done

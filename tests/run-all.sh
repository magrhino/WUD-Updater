#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$REPO_ROOT"

run(){
  printf '==> %s\n' "$*"
  "$@"
}

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

for test_script in tests/test-*.sh; do
  run "$test_script"
done

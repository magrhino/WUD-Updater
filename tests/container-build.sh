#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$REPO_ROOT"

COMPOSE_EXAMPLE="docs/examples/docker-compose.example.yml"
COMPOSE_WEBUI="docs/examples/docker-compose.webui.yml"
COMPOSE_HARDENED="docs/examples/docker-compose.hardened.yml"
COMPOSE_BUILD="docs/examples/docker-compose.build.yml"
COMPOSE_TRUENAS="docs/examples/docker-compose.truenas.yml"
cleanup_image=0
SYNC_TMP=""
if [[ -n "${WUD_UPDATER_TEST_IMAGE:-}" ]]; then
  IMAGE="$WUD_UPDATER_TEST_IMAGE"
else
  IMAGE="wud-updater:test-${GITHUB_RUN_ID:-local}-$$"
  cleanup_image=1
fi

cleanup(){
  if [[ "$cleanup_image" -eq 1 ]]; then
    docker image rm "$IMAGE" >/dev/null 2>&1 || true
  fi
  if [[ -n "$SYNC_TMP" && -d "$SYNC_TMP" ]]; then
    rm -rf "$SYNC_TMP"
  fi
}
trap cleanup EXIT

run(){
  printf '==> %s\n' "$*"
  "$@"
}

run_quiet(){
  local output
  printf '==> %s\n' "$*"
  if ! output="$("$@" 2>&1)"; then
    printf '%s\n' "$output" >&2
    return 1
  fi
}

need_cmd(){
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Missing required command: %s\n' "$1" >&2
    exit 127
  }
}

need_cmd docker

run docker version
run docker compose version
run_quiet docker compose -f "$COMPOSE_EXAMPLE" config
run_quiet docker compose -f "$COMPOSE_WEBUI" config
run_quiet docker compose -f "$COMPOSE_HARDENED" config
run_quiet docker compose -f "$COMPOSE_BUILD" config
run_quiet docker compose -f "$COMPOSE_TRUENAS" config
run docker build -t "$IMAGE" .
run docker run --rm "$IMAGE" test -f /app/src/wud_updater/web_static/index.html
run docker run --rm "$IMAGE"
run docker run --rm -e WUD_UPDATER_PYTHON=false "$IMAGE"
SYNC_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-script-sync-test.XXXXXX")"
run docker run --rm -v "$SYNC_TMP:/managed-wud" "$IMAGE" sync-wud-scripts
[[ -x "$SYNC_TMP/on-update.sh" ]]
[[ -x "$SYNC_TMP/append-updates.sh" ]]
[[ -x "$SYNC_TMP/github-release-embed.sh" ]]
[[ -f "$SYNC_TMP/upstreams.txt" ]]
run docker run --rm "$IMAGE" docker-update-from-wud --help

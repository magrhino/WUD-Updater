#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$REPO_ROOT"

cleanup_image=0
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
run_quiet docker compose -f docker-compose.example.yml config
run docker build -t "$IMAGE" .
run docker run --rm "$IMAGE"
run docker run --rm -e WUD_UPDATER_PYTHON=1 "$IMAGE"

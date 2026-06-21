#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$REPO_ROOT"

docker_name_component(){
  local value="${1:-local}"
  local digest sanitized

  sanitized="$(printf '%s' "$value" | LC_ALL=C tr -c 'A-Za-z0-9_.-' '-')"
  if [[ -z "$sanitized" ]]; then
    sanitized="local"
  fi
  if (( ${#sanitized} > 48 )); then
    digest="$(printf '%s' "$value" | cksum | awk '{ print $1 }')"
    sanitized="${sanitized:0:40}-${digest}"
  fi

  printf '%s' "$sanitized"
}

COMPOSE_EXAMPLE="docs/examples/docker-compose.example.yml"
COMPOSE_WEBUI="docs/examples/docker-compose.webui.yml"
COMPOSE_HARDENED="docs/examples/docker-compose.hardened.yml"
COMPOSE_BUILD="docs/examples/docker-compose.build.yml"
COMPOSE_TRUENAS="docs/examples/docker-compose.truenas.yml"
cleanup_image=0
SYNC_TMP=""
HEALTH_TMP=""
HEALTH_CONTAINER=""
RUN_ID_COMPONENT="$(docker_name_component "${GITHUB_RUN_ID:-local}")"
if [[ -n "${WUDUP_TEST_IMAGE:-}" ]]; then
  IMAGE="$WUDUP_TEST_IMAGE"
else
  IMAGE="wudup:test-${RUN_ID_COMPONENT}-$$"
  cleanup_image=1
fi

cleanup(){
  if [[ -n "$HEALTH_CONTAINER" ]]; then
    docker rm -f "$HEALTH_CONTAINER" >/dev/null 2>&1 || true
  fi
  if [[ "$cleanup_image" -eq 1 ]]; then
    docker image rm "$IMAGE" >/dev/null 2>&1 || true
  fi
  if [[ -n "$SYNC_TMP" && -d "$SYNC_TMP" ]]; then
    rm -rf "$SYNC_TMP"
  fi
  if [[ -n "$HEALTH_TMP" && -d "$HEALTH_TMP" ]]; then
    rm -rf "$HEALTH_TMP"
  fi
}
trap cleanup EXIT

run(){
  local description="$*"
  local -a command=("$@")

  printf '==> %s\n' "$description"
  "${command[@]}"
}

run_quiet(){
  local description="$*"
  local output
  local -a command=("$@")

  printf '==> %s\n' "$description"
  if ! output="$("${command[@]}" 2>&1)"; then
    printf '%s\n' "$output" >&2
    return 1
  fi
}

assert_duration(){
  local label="$1" actual="$2" expected_text="$3" expected_nanos="$4"

  [[ "$actual" == "$expected_text" || "$actual" == "$expected_nanos" ]] || {
    printf 'Expected %s=%s, got %s\n' "$label" "$expected_text" "$actual" >&2
    return 1
  }
}

assert_image_metadata(){
  local cmd web_host
  local health_test_len health_test_type health_test_command
  local health_interval health_timeout health_retries health_start_period

  cmd="$(docker image inspect -f '{{json .Config.Cmd}}' "$IMAGE")"
  [[ "$cmd" == '["web"]' ]] || {
    printf 'Expected image Cmd ["web"], got %s\n' "$cmd" >&2
    return 1
  }

  web_host="$(
    docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$IMAGE" |
      awk -F= '$1 == "WUD_WEB_HOST" { print $2; exit }'
  )"
  [[ "$web_host" == "0.0.0.0" ]] || {
    printf 'Expected WUD_WEB_HOST=0.0.0.0, got %s\n' "${web_host:-<unset>}" >&2
    return 1
  }

  health_test_len="$(docker image inspect -f '{{if .Config.Healthcheck}}{{len .Config.Healthcheck.Test}}{{else}}0{{end}}' "$IMAGE")"
  [[ "$health_test_len" == "2" ]] || {
    printf 'Expected healthcheck test with 2 entries, got %s\n' "$health_test_len" >&2
    return 1
  }
  health_test_type="$(docker image inspect -f '{{index .Config.Healthcheck.Test 0}}' "$IMAGE")"
  health_test_command="$(docker image inspect -f '{{index .Config.Healthcheck.Test 1}}' "$IMAGE")"
  [[ "$health_test_type" == "CMD-SHELL" ]] || {
    printf 'Expected healthcheck type CMD-SHELL, got %s\n' "$health_test_type" >&2
    return 1
  }
  [[ " $health_test_command " == *" curl "* ]] || {
    printf 'Expected healthcheck command to run curl, got %s\n' "$health_test_command" >&2
    return 1
  }
  [[ " $health_test_command " == *" -fsS "* ]] || {
    printf 'Expected healthcheck curl flags -fsS, got %s\n' "$health_test_command" >&2
    return 1
  }
  [[ " $health_test_command " == *" -o /dev/null "* ]] || {
    printf 'Expected healthcheck to discard response body, got %s\n' "$health_test_command" >&2
    return 1
  }
  [[ "$health_test_command" == *"http://127.0.0.1:\${WUD_WEB_PORT:-7417}/readyz"* ]] || {
    printf 'Expected healthcheck command to call the readyz endpoint, got %s\n' "$health_test_command" >&2
    return 1
  }
  [[ "$health_test_command" == *'|| exit 1'* ]] || {
    printf 'Expected healthcheck command to fail on unsuccessful readyz probe, got %s\n' "$health_test_command" >&2
    return 1
  }

  health_interval="$(docker image inspect -f '{{.Config.Healthcheck.Interval}}' "$IMAGE")"
  health_timeout="$(docker image inspect -f '{{.Config.Healthcheck.Timeout}}' "$IMAGE")"
  health_retries="$(docker image inspect -f '{{.Config.Healthcheck.Retries}}' "$IMAGE")"
  health_start_period="$(docker image inspect -f '{{.Config.Healthcheck.StartPeriod}}' "$IMAGE")"

  assert_duration "healthcheck.interval" "$health_interval" "30s" "30000000000"
  assert_duration "healthcheck.timeout" "$health_timeout" "5s" "5000000000"
  [[ "$health_retries" == "3" ]] || {
    printf 'Expected healthcheck.retries=3, got %s\n' "$health_retries" >&2
    return 1
  }
  assert_duration "healthcheck.start_period" "$health_start_period" "10s" "10000000000"
}

wait_for_default_web_health(){
  local status

  for _ in {1..90}; do
    status="$(
      docker inspect \
        -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' \
        "$HEALTH_CONTAINER"
    )"
    case "$status" in
      healthy)
        return 0
        ;;
      unhealthy)
        printf 'Default WebUI container became unhealthy.\n' >&2
        docker inspect -f '{{json .State.Health}}' "$HEALTH_CONTAINER" >&2 || true
        docker logs "$HEALTH_CONTAINER" >&2 || true
        return 1
        ;;
      *)
        sleep 1
        ;;
    esac
  done

  printf 'Timed out waiting for default WebUI container healthcheck.\n' >&2
  docker inspect -f '{{json .State.Health}}' "$HEALTH_CONTAINER" >&2 || true
  docker logs "$HEALTH_CONTAINER" >&2 || true
  return 1
}

smoke_default_web_health(){
  HEALTH_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-health-test.XXXXXX")"
  HEALTH_CONTAINER="wudup-health-${RUN_ID_COMPONENT}-$$"
  mkdir -p "$HEALTH_TMP/host-docker" "$HEALTH_TMP/out" "$HEALTH_TMP/logs"
  touch "$HEALTH_TMP/out/images.todo"

  run docker run -d \
    --name "$HEALTH_CONTAINER" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$HEALTH_TMP/host-docker:/host/docker" \
    -v "$HEALTH_TMP/out:/out" \
    -v "$HEALTH_TMP/logs:/logs" \
    "$IMAGE"
  run wait_for_default_web_health
  run docker rm -f "$HEALTH_CONTAINER"
  HEALTH_CONTAINER=""
}

need_cmd(){
  local cmd="$1"

  command -v "$cmd" >/dev/null 2>&1 || {
    printf 'Missing required command: %s\n' "$cmd" >&2
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
run assert_image_metadata
run docker run --rm "$IMAGE" test -f /app/src/wudup/web_static/index.html
run smoke_default_web_health
run docker run --rm "$IMAGE" updates --dry-run
SYNC_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-script-sync-test.XXXXXX")"
run docker run --rm -v "$SYNC_TMP:/managed-wud" "$IMAGE" sync-wud-scripts
[[ -x "$SYNC_TMP/on-update.sh" ]]
[[ -x "$SYNC_TMP/append-updates.sh" ]]
[[ -x "$SYNC_TMP/release-parser.sh" ]]
[[ -x "$SYNC_TMP/release-notes-to-discord.sh" ]]
[[ -x "$SYNC_TMP/github-release-embed.sh" ]]
[[ -x "$SYNC_TMP/tag-manager.sh" ]]
[[ -f "$SYNC_TMP/upstreams.txt" ]]
run docker run --rm "$IMAGE" docker-update-from-wud --help

#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$REPO_ROOT"

TEST_TMP=""
IMAGE="${WUD_UPDATER_TEST_IMAGE:-}"
cleanup_image=0
REGISTRY_NAME=""
REGISTRY_REF=""
APP_IMAGE=""
OLD_LOCAL_IMAGE=""
NEW_LOCAL_IMAGE=""
STACK_DIR=""
COMPOSE_FILE=""
OUT_VOLUME=""
LOG_VOLUME=""
SCRIPTS_DIR=""

fail(){
  printf 'not ok - %s\n' "$*" >&2
  if [[ -n "${COMPOSE_FILE:-}" && -f "$COMPOSE_FILE" ]]; then
    (
      cd "$STACK_DIR"
      printf '# compose ps:\n' >&2
      docker compose -f docker-compose.yml ps >&2 || true
      printf '# compose logs:\n' >&2
      docker compose -f docker-compose.yml logs --no-color >&2 || true
    )
  fi
  if [[ -n "${LOG_VOLUME:-}" && -n "${IMAGE:-}" ]]; then
    printf '# log volume files:\n' >&2
    docker run --rm -v "$LOG_VOLUME:/mnt" "$IMAGE" find /mnt -maxdepth 1 -type f -print >&2 || true
  fi
  exit 1
}

cleanup(){
  if [[ -n "${COMPOSE_FILE:-}" && -f "$COMPOSE_FILE" ]]; then
    (
      cd "$STACK_DIR"
      docker compose -f docker-compose.yml down -v --remove-orphans >/dev/null 2>&1 || true
    )
  fi
  if [[ -n "$REGISTRY_NAME" ]]; then
    docker rm -f "$REGISTRY_NAME" >/dev/null 2>&1 || true
  fi
  if [[ -n "$APP_IMAGE" ]]; then
    docker image rm "$APP_IMAGE" >/dev/null 2>&1 || true
  fi
  if [[ -n "$OUT_VOLUME" ]]; then
    docker volume rm "$OUT_VOLUME" >/dev/null 2>&1 || true
  fi
  if [[ -n "$LOG_VOLUME" ]]; then
    docker volume rm "$LOG_VOLUME" >/dev/null 2>&1 || true
  fi
  if [[ -n "$OLD_LOCAL_IMAGE" ]]; then
    docker image rm "$OLD_LOCAL_IMAGE" >/dev/null 2>&1 || true
  fi
  if [[ -n "$NEW_LOCAL_IMAGE" ]]; then
    docker image rm "$NEW_LOCAL_IMAGE" >/dev/null 2>&1 || true
  fi
  if [[ "$cleanup_image" -eq 1 && -n "$IMAGE" ]]; then
    docker image rm "$IMAGE" >/dev/null 2>&1 || true
  fi
  if [[ -n "$TEST_TMP" && -d "$TEST_TMP" ]]; then
    rm -rf "$TEST_TMP"
  fi
}
trap cleanup EXIT

run(){
  printf '==> %s\n' "$*"
  "$@"
}

need_cmd(){
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Missing required command: %s\n' "$1" >&2
    exit 127
  }
}

compose(){
  (
    cd "$STACK_DIR"
    docker compose -f docker-compose.yml "$@"
  )
}

volume_file_content(){
  local volume="$1" path="$2"
  docker run --rm -v "$volume:/mnt" "$IMAGE" bash -lc 'cat "$1"' _ "/mnt/$path"
}

write_volume_file(){
  local volume="$1" path="$2" content="$3"
  printf '%s\n' "$content" | docker run -i --rm -v "$volume:/mnt" "$IMAGE" \
    bash -lc 'cat > "$1"' _ "/mnt/$path"
}

truncate_volume_file(){
  local volume="$1" path="$2"
  docker run --rm -v "$volume:/mnt" "$IMAGE" bash -lc ': > "$1"' _ "/mnt/$path"
}

assert_volume_file_equals(){
  local volume="$1" path="$2" expected="$3" actual
  actual="$(volume_file_content "$volume" "$path")"
  [[ "$actual" == "$expected" ]] || fail "expected $volume:$path to contain [$expected], got [$actual]"
}

assert_volume_file_empty(){
  local volume="$1" path="$2"
  docker run --rm -v "$volume:/mnt" "$IMAGE" bash -lc 'test ! -s "$1"' _ "/mnt/$path" ||
    fail "expected $volume:$path to be empty"
}

assert_volume_file_owner(){
  local volume="$1" path="$2" expected="$3" actual
  actual="$(docker run --rm -v "$volume:/mnt" "$IMAGE" stat -c '%u:%g' "/mnt/$path")"
  [[ "$actual" == "$expected" ]] || fail "expected $volume:$path owner $expected, got $actual"
}

assert_volume_glob_exists(){
  local volume="$1" pattern="$2"
  docker run --rm -v "$volume:/mnt" "$IMAGE" bash -lc 'compgen -G "$1" >/dev/null' _ "/mnt/$pattern" ||
    fail "expected $volume to contain $pattern"
}

container_id(){
  compose ps -q app
}

wait_for_container_version(){
  local expected="$1" attempt cid version status health

  for attempt in $(seq 1 45); do
    cid="$(container_id || true)"
    if [[ -n "$cid" ]]; then
      version="$(docker exec "$cid" cat /wud-e2e-version 2>/dev/null || true)"
      status="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || true)"
      health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || true)"
      if [[ "$version" == "$expected" && "$status" == "running" && "$health" == "healthy" ]]; then
        return 0
      fi
    fi
    sleep 1
  done

  fail "container did not reach version $expected"
}

start_registry(){
  REGISTRY_NAME="wud-updater-e2e-registry-${GITHUB_RUN_ID:-local}-$$"
  local registry_port

  run docker run -d --name "$REGISTRY_NAME" -p 127.0.0.1::5000 registry:2
  registry_port="$(docker inspect -f '{{(index (index .NetworkSettings.Ports "5000/tcp") 0).HostPort}}' "$REGISTRY_NAME")"
  REGISTRY_REF="127.0.0.1:${registry_port}"
  APP_IMAGE="${REGISTRY_REF}/wud-e2e-app:latest"
}

push_image(){
  local image="$1" attempt

  printf '==> docker push %s\n' "$image"
  for attempt in $(seq 1 30); do
    if docker push "$image"; then
      return 0
    fi
    printf 'docker push attempt %s failed for %s\n' "$attempt" "$image" >&2
    sleep 1
  done

  return 1
}

write_fixture_dockerfile(){
  cat > "$TEST_TMP/fixture.Dockerfile" <<'EOF'
ARG BASE_IMAGE=python:3.14-slim-bookworm
FROM ${BASE_IMAGE}
ARG FIXTURE_VERSION
RUN printf '%s\n' "${FIXTURE_VERSION}" > /wud-e2e-version
LABEL org.opencontainers.image.source="https://github.com/magrhino/wud-updater-e2e-fixture"
HEALTHCHECK --interval=1s --timeout=1s --retries=30 CMD test -f /wud-e2e-version
ENTRYPOINT []
CMD ["bash", "-lc", "trap 'exit 0' TERM INT; while :; do sleep 1; done"]
EOF
}

build_fixture_image(){
  local tag="$1" version="$2"

  run docker build \
    -f "$TEST_TMP/fixture.Dockerfile" \
    --build-arg "BASE_IMAGE=$IMAGE" \
    --build-arg "FIXTURE_VERSION=$version" \
    -t "$tag" \
    "$TEST_TMP"
}

prepare_images(){
  OLD_LOCAL_IMAGE="wud-updater-e2e-app-old:${GITHUB_RUN_ID:-local}-$$"
  NEW_LOCAL_IMAGE="wud-updater-e2e-app-new:${GITHUB_RUN_ID:-local}-$$"

  write_fixture_dockerfile
  build_fixture_image "$OLD_LOCAL_IMAGE" old
  run docker tag "$OLD_LOCAL_IMAGE" "$APP_IMAGE"
  push_image "$APP_IMAGE"

  build_fixture_image "$NEW_LOCAL_IMAGE" new
  run docker tag "$NEW_LOCAL_IMAGE" "$APP_IMAGE"
  push_image "$APP_IMAGE"
  run docker tag "$OLD_LOCAL_IMAGE" "$APP_IMAGE"
}

write_compose_file(){
  mkdir -p "$STACK_DIR"
  cat > "$COMPOSE_FILE" <<YAML
services:
  app:
    image: ${APP_IMAGE}
    healthcheck:
      test: ["CMD-SHELL", "test -f /wud-e2e-version"]
      interval: 1s
      timeout: 1s
      retries: 30
YAML
}

run_updater_e2e(){
  write_compose_file
  run compose up -d
  wait_for_container_version old

  write_volume_file "$OUT_VOLUME" images.todo "$APP_IMAGE"
  run docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$STACK_DIR:$STACK_DIR" \
    -v "$OUT_VOLUME:/out" \
    -v "$LOG_VOLUME:/logs" \
    -e WUD_UPDATER_BANNER=0 \
    -e WUD_DB_PATH=/logs/e2e.sqlite \
    -e OUT_UID="$(id -u)" \
    -e OUT_GID="$(id -g)" \
    "$IMAGE" \
    docker-update-from-wud \
    --base "$STACK_DIR" \
    --file /out/images.todo \
    --log-dir /logs \
    --mode live \
    --max-wait 30 \
    --yes \
    --no-color

  assert_volume_file_empty "$OUT_VOLUME" images.todo
  assert_volume_file_owner "$OUT_VOLUME" images.todo "$(id -u):$(id -g)"
  wait_for_container_version new
  docker run --rm -v "$LOG_VOLUME:/mnt" "$IMAGE" test -s /mnt/e2e.sqlite ||
    fail "expected audit database to be created"
  assert_volume_glob_exists "$LOG_VOLUME" 'update-from-wud-v2-*.log'
}

run_wud_callback_smoke(){
  run docker run --rm \
    -v "$SCRIPTS_DIR:/managed-wud" \
    "$IMAGE" \
    sync-wud-scripts

  truncate_volume_file "$OUT_VOLUME" images.todo
  run docker run --rm \
    -v "$SCRIPTS_DIR:/wud:ro" \
    -v "$OUT_VOLUME:/out" \
    -e WUD_OUT_FILE=/out/images.todo \
    -e OUT_UID="$(id -u)" \
    -e OUT_GID="$(id -g)" \
    -e update_available=true \
    -e image_name=repo/callback \
    -e image_tag_value=1.0.0 \
    "$IMAGE" \
    /wud/on-update.sh

  assert_volume_file_equals "$OUT_VOLUME" images.todo "repo/callback:1.0.0"
  assert_volume_file_owner "$OUT_VOLUME" images.todo "$(id -u):$(id -g)"
}

main(){
  need_cmd docker

  run docker version
  run docker compose version

  TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-updater-e2e.XXXXXX")"
  STACK_DIR="$TEST_TMP/docker/wud-e2e-stack"
  COMPOSE_FILE="$STACK_DIR/docker-compose.yml"
  OUT_VOLUME="wud-updater-e2e-out-${GITHUB_RUN_ID:-local}-$$"
  LOG_VOLUME="wud-updater-e2e-logs-${GITHUB_RUN_ID:-local}-$$"
  SCRIPTS_DIR="$TEST_TMP/managed-wud"
  mkdir -p "$SCRIPTS_DIR"

  if [[ -z "$IMAGE" ]]; then
    IMAGE="wud-updater:e2e-${GITHUB_RUN_ID:-local}-$$"
    cleanup_image=1
    run docker build -t "$IMAGE" .
  fi

  run docker volume create "$OUT_VOLUME"
  run docker volume create "$LOG_VOLUME"
  start_registry
  prepare_images
  run_updater_e2e
  run_wud_callback_smoke
}

main "$@"

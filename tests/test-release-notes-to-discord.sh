#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SCRIPT="$REPO_ROOT/wud/release-notes-to-discord.sh"
TEST_TMP=""

fail(){
  printf 'not ok - %s\n' "$*" >&2
  if [[ -n "${TEST_TMP:-}" && -f "$TEST_TMP/output.log" ]]; then
    sed 's/^/# /' "$TEST_TMP/output.log" >&2 || true
  fi
  exit 1
}

setup_case(){
  TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-release-notes-test.XXXXXX")"
  mkdir -p "$TEST_TMP/bin"
  write_fakes
}

teardown_case(){
  [[ -n "${TEST_TMP:-}" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
  TEST_TMP=""
}

write_fakes(){
  cat > "$TEST_TMP/bin/docker" <<'FAKE_DOCKER'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$1 $2" == "image inspect" ]]; then
  printf '%s\n' "${FAKE_IMAGE_SOURCE:-}"
  exit 0
fi
exit 1
FAKE_DOCKER

  cat > "$TEST_TMP/bin/curl" <<'FAKE_CURL'
#!/usr/bin/env bash
set -Eeuo pipefail

out_file=""
write_out=""
payload=""
url=""

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    -o)
      out_file="$2"
      shift 2
      ;;
    -w)
      write_out="$2"
      shift 2
      ;;
    -d)
      payload="$2"
      shift 2
      ;;
    -H|-X|--retry|--retry-delay|--max-time)
      shift 2
      ;;
    -*)
      shift
      ;;
    *)
      url="$1"
      shift
      ;;
  esac
done

write_body(){
  if [[ -n "$out_file" ]]; then
    printf '%s' "$1" > "$out_file"
  else
    printf '%s' "$1"
  fi
}

release_json(){
  jq -n \
    --arg tag "$1" \
    --arg repo "$2" \
    --arg body "$3" \
    '{
      tag_name:$tag,
      name:$tag,
      html_url:("https://github.com/" + $repo + "/releases/tag/" + $tag),
      body:$body,
      published_at:"2026-01-02T00:00:00Z"
    }'
}

if [[ "$url" == "https://discord.test/webhook" ]]; then
  printf '%s' "$payload" > "${FAKE_WEBHOOK_PAYLOAD:?}"
  if [[ "$write_out" == *"%{http_code}"* ]]; then
    printf '\n204'
  fi
  exit 0
fi

case "$url" in
  https://api.github.com/repos/acme/app/releases/latest)
    write_body "$(release_json "v2.0.0" "acme/app" $'## Changes\n- Routine maintenance')"
    ;;
  https://api.github.com/repos/linuxserver/docker-radarr/releases/latest)
    write_body "$(release_json "v1.0.0" "linuxserver/docker-radarr" $'## Changes\n- Container update')"
    ;;
  *)
    printf 'unexpected curl URL: %s\n' "$url" >&2
    exit 1
    ;;
esac
FAKE_CURL

  chmod +x "$TEST_TMP/bin/docker" "$TEST_TMP/bin/curl"
}

run_notes(){
  local image="$1" current="$2" payload_file="$3"

  PATH="$TEST_TMP/bin:$PATH" \
    DISCORD_RELEASES_WEBHOOK="https://discord.test/webhook" \
    FAKE_WEBHOOK_PAYLOAD="$payload_file" \
    FAKE_IMAGE_SOURCE="${FAKE_IMAGE_SOURCE:-}" \
    "$SCRIPT" "$image" "container" "$current" > "$TEST_TMP/output.log" 2>&1 || fail "release note script failed"
}

test_oci_source_uses_github_release_engine(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"

  FAKE_IMAGE_SOURCE="https://github.com/acme/app" run_notes "ghcr.io/acme/app:1.0.0" "1.0.0" "$payload_file"

  [[ -s "$payload_file" ]] || fail "webhook payload was not captured"
  jq -e '.username == "GitHub Release Notes"' "$payload_file" >/dev/null || fail "release engine username missing"
  jq -e '.embeds[0].fields[] | select(.name == "Container" and .value == "container")' "$payload_file" >/dev/null || fail "container field was not preserved"
  jq -e '.embeds[0].fields[] | select(.name == "Version" and .value == "1.0.0 -> v2.0.0")' "$payload_file" >/dev/null || fail "current to new field was not rendered"
  jq -e '.embeds[0].fields[] | select(.name == "Breaking" and .value == "yes")' "$payload_file" >/dev/null || fail "major bump was not marked breaking"
  teardown_case
}

test_linuxserver_image_falls_back_to_docker_repo(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"

  FAKE_IMAGE_SOURCE="" run_notes "linuxserver/radarr:latest" "latest" "$payload_file"

  [[ -s "$payload_file" ]] || fail "webhook payload was not captured"
  jq -e '.embeds[0].fields[] | select(.name == "Repository" and .value == "linuxserver/docker-radarr")' "$payload_file" >/dev/null || fail "LinuxServer source fallback was not used"
  teardown_case
}

test_missing_source_posts_minimal_notice(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"

  FAKE_IMAGE_SOURCE="" run_notes "docker.io/library/redis:latest" "latest" "$payload_file"

  [[ -s "$payload_file" ]] || fail "webhook payload was not captured"
  jq -e '.embeds[0].title == "Update available: docker.io/library/redis:latest"' "$payload_file" >/dev/null || fail "minimal notice title was wrong"
  jq -e '.embeds[0].description == "No GitHub source label found. Unable to fetch release notes."' "$payload_file" >/dev/null || fail "minimal notice description was wrong"
  teardown_case
}

run_test(){
  local name="$1"
  printf 'running %s\n' "$name"
  "$name"
  printf 'ok - %s\n' "$name"
}

main(){
  run_test test_oci_source_uses_github_release_engine
  run_test test_linuxserver_image_falls_back_to_docker_repo
  run_test test_missing_source_posts_minimal_notice
}

trap teardown_case EXIT
main "$@"

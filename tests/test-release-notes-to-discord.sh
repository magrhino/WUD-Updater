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
  printf 'linuxserver/docker-radarr: Radarr/Radarr\n' > "$TEST_TMP/upstreams.txt"
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

if [[ -n "${FAKE_CURL_ARGS_LOG:-}" ]]; then
  printf '%q ' "$@" >> "$FAKE_CURL_ARGS_LOG"
  printf '\n' >> "$FAKE_CURL_ARGS_LOG"
fi

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
    -H|-X|--retry|--retry-delay|--connect-timeout|--max-time)
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
if [[ "$url" == "https://discord.test/admin" ]]; then
  printf '%s' "$payload" > "${FAKE_ADMIN_PAYLOAD:?}"
  if [[ "$write_out" == *"%{http_code}"* ]]; then
    printf '\n204'
  fi
  exit 0
fi
if [[ "$url" == https://discord.test/fail/* ]]; then
  if [[ "$write_out" == *"%{http_code}"* ]]; then
    printf '\n500'
  fi
  exit 0
fi

case "$url" in
  https://api.github.com/repos/acme/app/releases/latest)
    write_body "$(release_json "v2.0.0" "acme/app" $'## Changes\n- Routine maintenance')"
    ;;
  https://api.github.com/repos/linuxserver/docker-radarr/releases/latest)
    write_body "$(release_json "5.1.0-ls1" "linuxserver/docker-radarr" $'LinuxServer Changes:\n- Rebase to Alpine 3.20\n- Add package\n\nRemote Changes:\n- Updating to 5.1.0')"
    ;;
  https://api.github.com/repos/Radarr/Radarr/releases/tags/v5.1.0)
    write_body "$(release_json "v5.1.0" "Radarr/Radarr" $'## Changes\n- New queue view')"
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
  local webhook="${DISCORD_RELEASES_WEBHOOK:-https://discord.test/webhook}"

  PATH="$TEST_TMP/bin:$PATH" \
    DISCORD_RELEASES_WEBHOOK="$webhook" \
    FAKE_WEBHOOK_PAYLOAD="$payload_file" \
    FAKE_CURL_ARGS_LOG="$TEST_TMP/curl.args" \
    FAKE_IMAGE_SOURCE="${FAKE_IMAGE_SOURCE:-}" \
    UPSTREAM_MAP="$TEST_TMP/upstreams.txt" \
    "$SCRIPT" "$image" "container" "$current" > "$TEST_TMP/output.log" 2>&1 || fail "release note script failed"
}

assert_curl_policy_for_url(){
  local url="$1" line
  line="$(grep -F -- "$url" "$TEST_TMP/curl.args" | head -n 1 || true)"
  [[ -n "$line" ]] || fail "no curl call captured for $url"
  [[ "$line" == *"--retry 3"* ]] || fail "curl call for $url did not set retry policy"
  [[ "$line" == *"--connect-timeout 5"* ]] || fail "curl call for $url did not set connect timeout"
  [[ "$line" == *"--max-time 20"* ]] || fail "curl call for $url did not set max time"
}

test_ghcr_image_uses_github_release_engine(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"

  FAKE_IMAGE_SOURCE="" run_notes "ghcr.io/acme/app:1.0.0" "1.0.0" "$payload_file"

  [[ -s "$payload_file" ]] || fail "webhook payload was not captured"
  assert_curl_policy_for_url "https://discord.test/webhook"
  jq -e '.allowed_mentions.parse == []' "$payload_file" >/dev/null || fail "allowed_mentions was not disabled"
  jq -e '.username == "GitHub Release Notes"' "$payload_file" >/dev/null || fail "release engine username missing"
  jq -e '.embeds[0].fields[] | select(.name == "Container" and .value == "container")' "$payload_file" >/dev/null || fail "container field was not preserved"
  jq -e '.embeds[0].fields[] | select(.name == "Version" and .value == "1.0.0 -> v2.0.0")' "$payload_file" >/dev/null || fail "current to new field was not rendered"
  jq -e '.embeds[0].fields[] | select(.name == "Breaking" and .value == "yes")' "$payload_file" >/dev/null || fail "major bump was not marked breaking"
  teardown_case
}

test_direct_repo_arg_uses_github_release_engine(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"

  PATH="$TEST_TMP/bin:$PATH" \
    FAKE_WEBHOOK_PAYLOAD="$payload_file" \
    FAKE_CURL_ARGS_LOG="$TEST_TMP/curl.args" \
    "$SCRIPT" --repo acme/app --webhook https://discord.test/webhook > "$TEST_TMP/output.log" 2>&1 || fail "direct repo release note script failed"

  [[ -s "$payload_file" ]] || fail "webhook payload was not captured"
  jq -e '.username == "GitHub Release Notes"' "$payload_file" >/dev/null || fail "release engine username missing"
  jq -e '.embeds[0].fields[] | select(.name == "Repository" and .value == "acme/app")' "$payload_file" >/dev/null || fail "direct repo was not used"
  jq -e '.embeds[0].fields[] | select(.name == "Links" and (.value | contains("GitHub release")))' "$payload_file" >/dev/null || fail "GitHub release link was not rendered"
  teardown_case
}

test_oci_source_label_uses_github_release_engine(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"

  FAKE_IMAGE_SOURCE="https://github.com/acme/app" run_notes "docker.io/acme/app:1.0.0" "1.0.0" "$payload_file"

  [[ -s "$payload_file" ]] || fail "webhook payload was not captured"
  jq -e '.embeds[0].fields[] | select(.name == "Repository" and .value == "acme/app")' "$payload_file" >/dev/null || fail "OCI source label repo was not used"
  teardown_case
}

test_linuxserver_image_shows_lsio_and_upstream_links(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"

  FAKE_IMAGE_SOURCE="" run_notes "linuxserver/radarr:latest" "latest" "$payload_file"

  [[ -s "$payload_file" ]] || fail "webhook payload was not captured"
  jq -e '.allowed_mentions.parse == []' "$payload_file" >/dev/null || fail "LinuxServer payload did not disable mentions"
  jq -e '.embeds[0].fields[] | select(.name == "LSIO Tag" and .value == "`5.1.0-ls1`")' "$payload_file" >/dev/null || fail "LSIO tag was not rendered"
  jq -e '.embeds[0].fields[] | select(.name == "Upstream Version" and .value == "`v5.1.0`")' "$payload_file" >/dev/null || fail "upstream version was not rendered"
  jq -e '.embeds[0].fields[] | select(.name == "Links" and (.value | contains("LSIO release") and contains("Upstream release")))' "$payload_file" >/dev/null || fail "LSIO and upstream links were not rendered"
  teardown_case
}

test_missing_linuxserver_mapping_posts_admin_only(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"
  local admin_payload_file="$TEST_TMP/admin-payload.json"
  : > "$TEST_TMP/upstreams.txt"

  PATH="$TEST_TMP/bin:$PATH" \
    DISCORD_RELEASES_WEBHOOK="https://discord.test/webhook" \
    ADMIN_WEBHOOK="https://discord.test/admin" \
    FAKE_WEBHOOK_PAYLOAD="$payload_file" \
    FAKE_ADMIN_PAYLOAD="$admin_payload_file" \
    FAKE_CURL_ARGS_LOG="$TEST_TMP/curl.args" \
    FAKE_IMAGE_SOURCE="" \
    UPSTREAM_MAP="$TEST_TMP/upstreams.txt" \
    "$SCRIPT" "linuxserver/radarr:latest" "container" "latest" > "$TEST_TMP/output.log" 2>&1 || fail "missing mapping script failed"

  [[ -s "$admin_payload_file" ]] || fail "admin webhook payload was not captured"
  [[ ! -s "$payload_file" ]] || fail "normal webhook received a minimal notice"
  jq -e '.content | contains("Missing upstream mapping")' "$admin_payload_file" >/dev/null || fail "admin missing-mapping alert was not sent"
  teardown_case
}

test_missing_source_posts_minimal_notice(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"

  FAKE_IMAGE_SOURCE="" run_notes "docker.io/library/redis:latest" "latest" "$payload_file"

  [[ -s "$payload_file" ]] || fail "webhook payload was not captured"
  assert_curl_policy_for_url "https://discord.test/webhook"
  jq -e '.allowed_mentions.parse == []' "$payload_file" >/dev/null || fail "minimal notice did not disable mentions"
  jq -e '.embeds[0].title == "Update available: docker.io/library/redis:latest"' "$payload_file" >/dev/null || fail "minimal notice title was wrong"
  jq -e '.embeds[0].description == "No GitHub source label found. Unable to fetch release notes."' "$payload_file" >/dev/null || fail "minimal notice description was wrong"
  teardown_case
}

test_missing_source_webhook_failure_is_nonzero_and_redacted(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"

  if PATH="$TEST_TMP/bin:$PATH" \
    DISCORD_RELEASES_WEBHOOK="https://discord.test/fail/secret-token" \
    FAKE_WEBHOOK_PAYLOAD="$payload_file" \
    FAKE_CURL_ARGS_LOG="$TEST_TMP/curl.args" \
    FAKE_IMAGE_SOURCE="" \
    "$SCRIPT" "docker.io/library/redis:latest" "container" "latest" > "$TEST_TMP/output.log" 2>&1; then
    fail "minimal notice webhook failure returned success"
  fi
  assert_curl_policy_for_url "https://discord.test/fail/secret-token"
  grep -q 'Discord webhook error 500' "$TEST_TMP/output.log" || fail "webhook failure message missing"
  ! grep -q 'secret-token' "$TEST_TMP/output.log" || fail "webhook secret leaked"
  teardown_case
}

run_test(){
  local name="$1"
  printf 'running %s\n' "$name"
  "$name"
  printf 'ok - %s\n' "$name"
}

main(){
  run_test test_ghcr_image_uses_github_release_engine
  run_test test_direct_repo_arg_uses_github_release_engine
  run_test test_oci_source_label_uses_github_release_engine
  run_test test_linuxserver_image_shows_lsio_and_upstream_links
  run_test test_missing_linuxserver_mapping_posts_admin_only
  run_test test_missing_source_posts_minimal_notice
  run_test test_missing_source_webhook_failure_is_nonzero_and_redacted
}

trap teardown_case EXIT
main "$@"

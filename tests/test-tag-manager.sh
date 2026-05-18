#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SCRIPT="$REPO_ROOT/wud/tag-manager.sh"
TEST_TMP=""

fail(){
  printf 'not ok - %s\n' "$*" >&2
  if [[ -n "${TEST_TMP:-}" && -f "$TEST_TMP/output.log" ]]; then
    sed 's/^/# /' "$TEST_TMP/output.log" >&2 || true
  fi
  if [[ -n "${TEST_TMP:-}" && -f "$TEST_TMP/curl.args" ]]; then
    sed 's/^/# curl.args: /' "$TEST_TMP/curl.args" >&2 || true
  fi
  if [[ -n "${TEST_TMP:-}" && -f "$TEST_TMP/admin.payload.args" ]]; then
    sed 's/^/# admin.payload.args: /' "$TEST_TMP/admin.payload.args" >&2 || true
  fi
  exit 1
}

setup_case(){
  TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-tag-manager-test.XXXXXX")"
  mkdir -p "$TEST_TMP/bin" "$TEST_TMP/logs"
  printf 'linuxserver/docker-radarr: Radarr/Radarr\n' > "$TEST_TMP/upstreams.txt"

  cat > "$TEST_TMP/bin/github-release-embed.sh" <<'FAKE_EMBED'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$@" > "${FAKE_EMBED_ARGS:?}"
FAKE_EMBED

  cat > "$TEST_TMP/bin/curl" <<'FAKE_CURL'
#!/usr/bin/env bash
set -Eeuo pipefail
args_log="${FAKE_CURL_ARGS_LOG:-}"
if [[ -z "$args_log" && -n "${FAKE_ADMIN_PAYLOAD:-}" ]]; then
  args_log="${FAKE_ADMIN_PAYLOAD}.args"
fi
payload=""
url=""
write_out=""
retry=""
connect_timeout=""
max_time=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d)
      payload="$2"
      shift 2
      ;;
    -w)
      write_out="$2"
      shift 2
      ;;
    --retry)
      retry="$2"
      shift 2
      ;;
    --retry-delay)
      shift 2
      ;;
    --connect-timeout)
      connect_timeout="$2"
      shift 2
      ;;
    --max-time)
      max_time="$2"
      shift 2
      ;;
    -H|-X)
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
if [[ -n "$args_log" ]]; then
  printf 'url=%s --retry %s --connect-timeout %s --max-time %s\n' "$url" "$retry" "$connect_timeout" "$max_time" >> "$args_log"
fi
printf '%s\n%s\n' "$url" "$payload" > "${FAKE_ADMIN_PAYLOAD:?}"
if [[ "$url" == https://discord.test/fail/* ]]; then
  if [[ "$write_out" == *"%{http_code}"* ]]; then
    printf '\n500'
  fi
  exit 0
fi
if [[ "$write_out" == *"%{http_code}"* ]]; then
  printf '\n204'
fi
FAKE_CURL

  chmod +x "$TEST_TMP/bin/github-release-embed.sh" "$TEST_TMP/bin/curl"
}

teardown_case(){
  [[ -n "${TEST_TMP:-}" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
  TEST_TMP=""
}

run_manager(){
  PATH="$TEST_TMP/bin:$PATH" \
    RELEASE_EMBED="$TEST_TMP/bin/github-release-embed.sh" \
    UPSTREAM_MAP="$TEST_TMP/upstreams.txt" \
    LOG_DIR="$TEST_TMP/logs" \
    FAKE_EMBED_ARGS="$TEST_TMP/embed.args" \
    FAKE_ADMIN_PAYLOAD="$TEST_TMP/admin.payload" \
    FAKE_CURL_ARGS_LOG="$TEST_TMP/curl.args" \
    update_available="${update_available:-}" \
    image_name="${image_name:-}" \
    image_registry_url="${image_registry_url:-}" \
    update_kind_kind="${update_kind_kind:-}" \
    update_kind_remote_value="${update_kind_remote_value:-}" \
    result_tag="${result_tag:-}" \
    DISCORD_WEBHOOK="${DISCORD_WEBHOOK:-}" \
    ADMIN_WEBHOOK="${ADMIN_WEBHOOK:-}" \
    "$SCRIPT" > "$TEST_TMP/output.log" 2>&1 || fail "tag-manager failed"
}

assert_arg_present(){
  local value="$1"
  grep -Fx -- "$value" "$TEST_TMP/embed.args" >/dev/null || fail "missing embed arg: $value"
}

assert_arg_absent(){
  local value="$1"
  ! grep -Fx -- "$value" "$TEST_TMP/embed.args" >/dev/null || fail "unexpected embed arg: $value"
}

assert_curl_policy_for_url(){
  local url="$1" line="" args_file
  for args_file in "$TEST_TMP/curl.args" "$TEST_TMP/admin.payload.args"; do
    [[ -f "$args_file" ]] || continue
    line="$(grep -F -- "$url" "$args_file" | head -n 1 || true)"
    [[ -n "$line" ]] && break
  done
  [[ -n "$line" ]] || fail "no curl call captured for $url"
  [[ "$line" == *"--retry 3"* ]] || fail "curl call for $url did not set retry policy"
  [[ "$line" == *"--connect-timeout 5"* ]] || fail "curl call for $url did not set connect timeout"
  [[ "$line" == *"--max-time 20"* ]] || fail "curl call for $url did not set max time"
}

test_lsio_image_routes_through_mapping(){
  setup_case

  update_available=true \
    image_name=linuxserver/radarr \
    image_registry_url=https://index.docker.io/v1/ \
    update_kind_kind=tag \
    update_kind_remote_value=5.1.0-ls1 \
    DISCORD_WEBHOOK=https://discord.test/webhook \
    run_manager

  assert_arg_present "--provider"
  assert_arg_present "lsio"
  assert_arg_present "--lsio"
  assert_arg_present "linuxserver/docker-radarr"
  assert_arg_present "--upstream"
  assert_arg_present "Radarr/Radarr"
  assert_arg_absent "--tag"
  assert_arg_absent "5.1.0-ls1"
  assert_arg_present "--webhook"
  assert_arg_present "https://discord.test/webhook"
  teardown_case
}

test_ghcr_image_routes_to_github_provider(){
  setup_case

  update_available=true \
    image_name=owner/repo \
    image_registry_url=https://ghcr.io \
    update_kind_kind=tag \
    update_kind_remote_value=v2.0.0 \
    DISCORD_WEBHOOK=https://discord.test/webhook \
    run_manager

  assert_arg_present "--provider"
  assert_arg_present "github"
  assert_arg_present "--repo"
  assert_arg_present "owner/repo"
  assert_arg_present "--tag"
  assert_arg_present "v2.0.0"
  teardown_case
}

test_missing_lsio_mapping_alerts_admin_and_skips_embed(){
  setup_case
  : > "$TEST_TMP/upstreams.txt"

  update_available=true \
    image_name=linuxserver/sonarr \
    image_registry_url=https://index.docker.io/v1/ \
    ADMIN_WEBHOOK=https://discord.test/admin \
    run_manager

  [[ ! -e "$TEST_TMP/embed.args" ]] || fail "embed was called despite missing mapping"
  grep -q 'https://discord.test/admin' "$TEST_TMP/admin.payload" || fail "admin webhook was not called"
  assert_curl_policy_for_url "https://discord.test/admin"
  grep -q 'Missing upstream mapping' "$TEST_TMP/admin.payload" || fail "missing mapping alert text was wrong"
  tail -n +2 "$TEST_TMP/admin.payload" | jq -e '.allowed_mentions.parse == []' >/dev/null || fail "admin webhook mentions were not disabled"
  tail -n +2 "$TEST_TMP/admin.payload" | jq -e '(.content | contains("Missing upstream mapping")) and (.content | contains("\n"))' >/dev/null || fail "multiline admin content was not valid JSON"
  teardown_case
}

test_missing_lsio_mapping_admin_failure_warns_without_leaking_secret(){
  setup_case
  : > "$TEST_TMP/upstreams.txt"

  update_available=true \
    image_name=linuxserver/sonarr \
    image_registry_url=https://index.docker.io/v1/ \
    ADMIN_WEBHOOK=https://discord.test/fail/secret-token \
    run_manager

  [[ ! -e "$TEST_TMP/embed.args" ]] || fail "embed was called despite missing mapping"
  assert_curl_policy_for_url "https://discord.test/fail/secret-token"
  grep -q 'WARN: admin webhook send failed' "$TEST_TMP/output.log" || fail "admin webhook failure warning missing"
  ! grep -q 'secret-token' "$TEST_TMP/output.log" || fail "webhook secret leaked to output"
  ! grep -R -q 'secret-token' "$TEST_TMP/logs" || fail "webhook secret leaked to logs"
  teardown_case
}

run_test(){
  local name="$1"
  printf 'running %s\n' "$name"
  "$name"
  printf 'ok - %s\n' "$name"
}

main(){
  run_test test_lsio_image_routes_through_mapping
  run_test test_ghcr_image_routes_to_github_provider
  run_test test_missing_lsio_mapping_alerts_admin_and_skips_embed
  run_test test_missing_lsio_mapping_admin_failure_warns_without_leaking_secret
}

trap teardown_case EXIT
main "$@"

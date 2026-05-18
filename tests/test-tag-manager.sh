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
payload=""
url=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d)
      payload="$2"
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
printf '%s\n%s\n' "$url" "$payload" > "${FAKE_ADMIN_PAYLOAD:?}"
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

test_lsio_image_routes_through_mapping(){
  setup_case

  update_available=true \
    image_name=linuxserver/radarr \
    image_registry_url=https://index.docker.io/v1/ \
    update_kind_kind=tag \
    update_kind_remote_value=5.1.0 \
    DISCORD_WEBHOOK=https://discord.test/webhook \
    run_manager

  assert_arg_present "--provider"
  assert_arg_present "lsio"
  assert_arg_present "--lsio"
  assert_arg_present "linuxserver/docker-radarr"
  assert_arg_present "--upstream"
  assert_arg_present "Radarr/Radarr"
  assert_arg_present "--tag"
  assert_arg_present "5.1.0"
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
  grep -q 'Missing upstream mapping' "$TEST_TMP/admin.payload" || fail "missing mapping alert text was wrong"
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
}

trap teardown_case EXIT
main "$@"

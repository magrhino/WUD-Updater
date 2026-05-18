#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SCRIPT="$REPO_ROOT/wud/github-release-embed.sh"
TEST_TMP=""

fail(){
  printf 'not ok - %s\n' "$*" >&2
  if [[ -n "${TEST_TMP:-}" && -f "$TEST_TMP/output.log" ]]; then
    sed 's/^/# /' "$TEST_TMP/output.log" >&2 || true
  fi
  exit 1
}

setup_case(){
  TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-github-release-embed-test.XXXXXX")"
  mkdir -p "$TEST_TMP/bin"
  write_fakes
}

teardown_case(){
  [[ -n "${TEST_TMP:-}" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
  TEST_TMP=""
}

write_fakes(){
  cat > "$TEST_TMP/bin/curl" <<'FAKE_CURL'
#!/usr/bin/env bash
set -Eeuo pipefail

out_file=""
write_out=""
payload=""
url=""

while [[ $# -gt 0 ]]; do
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
    --arg date "${4:-2026-01-02T00:00:00Z}" \
    '{
      tag_name:$tag,
      name:$tag,
      html_url:("https://github.com/" + $repo + "/releases/tag/" + $tag),
      body:$body,
      published_at:$date
    }'
}

not_found(){
  write_body '{"message":"Not Found"}'
}

if [[ "$url" == https://discord.test/fail/* ]]; then
  printf 'failure\n500'
  exit 0
fi
if [[ "$url" == "https://discord.test/webhook" ]]; then
  printf '%s' "$payload" > "${FAKE_WEBHOOK_PAYLOAD:?}"
  if [[ "$write_out" == *"%{http_code}"* ]]; then
    printf '\n204'
  fi
  exit 0
fi

case "$url" in
  https://api.github.com/repos/acme/app/releases/latest)
    write_body "$(release_json "v2.0.0" "acme/app" $'## Key changes\n- Fixed deployment notes\n\n## Changes\n- Merge pull request (#12)')"
    ;;
  https://api.github.com/repos/acme/app/releases/tags/v2.0.0)
    write_body "$(release_json "v2.0.0" "acme/app" $'## Key changes\n- Fixed tagged release')"
    ;;
  https://api.github.com/repos/acme/app/releases/tags/vplain-1)
    not_found
    ;;
  https://api.github.com/repos/acme/app/releases/tags/plain-1)
    write_body "$(release_json "plain-1" "acme/app" $'## Key changes\n- Plain tag release')"
    ;;
  https://api.github.com/repos/acme/noreleases/releases/tags/v9.9.9|https://api.github.com/repos/acme/noreleases/releases/tags/9.9.9)
    not_found
    ;;
  https://api.github.com/repos/acme/noreleases/releases?per_page=100)
    write_body '[]'
    ;;
  https://api.github.com/repos/acme/noreleases)
    write_body '{"html_url":"https://github.com/acme/noreleases"}'
    ;;
  https://api.github.com/repos/linuxserver/docker-radarr/releases/latest)
    write_body "$(release_json "5.1.0-ls1" "linuxserver/docker-radarr" $'LinuxServer Changes:\n- Rebase to Alpine 3.20\n- Add package\n\nRemote Changes:\n- Updating to 5.1.0')"
    ;;
  https://api.github.com/repos/Radarr/Radarr/releases/tags/v5.1.0)
    write_body "$(release_json "v5.1.0" "Radarr/Radarr" $'## Key changes\n- New queue view\n\n## Changes\n- Merge pull request (#42)')"
    ;;
  https://api.github.com/repos/linuxserver/docker-missing/releases/latest)
    write_body "$(release_json "9.9.9-ls1" "linuxserver/docker-missing" $'LinuxServer Changes:\n- Rebase to Alpine 3.19\n\nRemote Changes:\n- Updating to 9.9.9')"
    ;;
  https://api.github.com/repos/NoRelease/App/releases/tags/v9.9.9|https://api.github.com/repos/NoRelease/App/releases/tags/9.9.9)
    not_found
    ;;
  https://api.github.com/repos/NoRelease/App/releases?per_page=100)
    write_body '[]'
    ;;
  https://api.github.com/repos/NoRelease/App)
    write_body '{"html_url":"https://github.com/NoRelease/App"}'
    ;;
  *)
    printf 'unexpected curl URL: %s\n' "$url" >&2
    exit 1
    ;;
esac
FAKE_CURL

  chmod +x "$TEST_TMP/bin/curl"
}

run_payload(){
  local output_file="$1"
  shift
  PATH="$TEST_TMP/bin:$PATH" "$SCRIPT" "$@" > "$output_file" 2> "$TEST_TMP/output.log" || fail "github-release-embed failed"
}

assert_mentions_disabled(){
  local payload_file="$1"
  jq -e '.allowed_mentions.parse == []' "$payload_file" >/dev/null || fail "allowed_mentions was not disabled"
}

test_generic_latest_payload_is_neutral(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"

  run_payload "$payload_file" --repo acme/app

  assert_mentions_disabled "$payload_file"
  jq -e '.username == "GitHub Release Notes"' "$payload_file" >/dev/null || fail "username was not neutral"
  jq -e '.embeds[0].title == "Release v2.0.0 for acme/app"' "$payload_file" >/dev/null || fail "generic title was wrong"
  jq -e '.embeds[0].footer.text == "Built from GitHub Release"' "$payload_file" >/dev/null || fail "generic footer was wrong"
  jq -e '.embeds[0].fields[] | select(.name == "Repository" and .value == "acme/app")' "$payload_file" >/dev/null || fail "repository field missing"
  teardown_case
}

test_generic_explicit_tag_resolves_v_and_plain_tags(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"

  run_payload "$payload_file" --repo acme/app --tag 2.0.0
  jq -e '.embeds[0].fields[] | select(.name == "Version" and .value == "v2.0.0")' "$payload_file" >/dev/null || fail "v-prefixed tag was not resolved"

  run_payload "$payload_file" --repo acme/app --tag plain-1
  jq -e '.embeds[0].fields[] | select(.name == "Version" and .value == "plain-1")' "$payload_file" >/dev/null || fail "plain tag was not resolved"
  teardown_case
}

test_generic_missing_release_falls_back_to_project(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"

  run_payload "$payload_file" --repo acme/noreleases --tag 9.9.9

  assert_mentions_disabled "$payload_file"
  jq -e '.embeds[0].url == "https://github.com/acme/noreleases"' "$payload_file" >/dev/null || fail "fallback URL was wrong"
  jq -e '.embeds[0].fields[] | select(.name == "Links" and (.value | contains("GitHub project")))' "$payload_file" >/dev/null || fail "fallback link was missing"
  teardown_case
}

test_lsio_release_adds_upstream_and_linuxserver_fields(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"

  run_payload "$payload_file" --provider lsio --lsio linuxserver/docker-radarr --upstream Radarr/Radarr

  assert_mentions_disabled "$payload_file"
  jq -e '.embeds[0].fields[] | select(.name == "LSIO Tag" and .value == "`5.1.0-ls1`")' "$payload_file" >/dev/null || fail "LSIO tag field missing"
  jq -e '.embeds[0].fields[] | select(.name == "Upstream Version" and .value == "`v5.1.0`")' "$payload_file" >/dev/null || fail "upstream version field missing"
  jq -e '.embeds[0].fields[] | select(.name == "LinuxServer Changes" and (.value | contains("Alpine 3.20") and contains("Add package")))' "$payload_file" >/dev/null || fail "LinuxServer changes field missing"
  jq -e '.embeds[0].fields[] | select(.name == "Links" and (.value | contains("LSIO release") and contains("Upstream release")))' "$payload_file" >/dev/null || fail "LSIO links missing"
  teardown_case
}

test_lsio_missing_upstream_release_falls_back_to_project(){
  setup_case
  local payload_file="$TEST_TMP/payload.json"

  run_payload "$payload_file" --provider lsio --lsio linuxserver/docker-missing --upstream NoRelease/App

  assert_mentions_disabled "$payload_file"
  jq -e '.embeds[0].url == "https://github.com/NoRelease/App"' "$payload_file" >/dev/null || fail "LSIO fallback URL was wrong"
  jq -e '.embeds[0].fields[] | select(.name == "Upstream Version" and .value == "`N/A`")' "$payload_file" >/dev/null || fail "LSIO fallback upstream version was wrong"
  teardown_case
}

test_webhook_failures_are_nonzero_and_redacted(){
  setup_case

  if PATH="$TEST_TMP/bin:$PATH" "$SCRIPT" --repo acme/app --webhook "https://discord.test/fail/secret-token" > "$TEST_TMP/output.log" 2>&1; then
    fail "webhook failure returned success"
  fi
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
  run_test test_generic_latest_payload_is_neutral
  run_test test_generic_explicit_tag_resolves_v_and_plain_tags
  run_test test_generic_missing_release_falls_back_to_project
  run_test test_lsio_release_adds_upstream_and_linuxserver_fields
  run_test test_lsio_missing_upstream_release_falls_back_to_project
  run_test test_webhook_failures_are_nonzero_and_redacted
}

trap teardown_case EXIT
main "$@"

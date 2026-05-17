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
  printf 'https://github.com/acme/app\n'
  exit 0
fi
exit 1
FAKE_DOCKER

  cat > "$TEST_TMP/bin/curl" <<'FAKE_CURL'
#!/usr/bin/env bash
set -Eeuo pipefail
payload=""
url=""
while [[ "$#" -gt 0 ]]; do
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

if [[ "$url" == "https://api.github.com/repos/acme/app/releases/latest" ]]; then
  tag="${FAKE_RELEASE_TAG:-2.0}"
  body="${FAKE_RELEASE_BODY:-}"
  if [[ -z "$body" ]]; then
    body=$'## Changes\n- Fixed deployment notes'
  fi
  jq -n --arg tag "$tag" --arg body "$body" \
    '{tag_name:$tag, html_url:("https://github.com/acme/app/releases/tag/" + $tag), body:$body}'
  exit 0
fi

if [[ "$url" == "https://discord.test/webhook" ]]; then
  printf '%s' "$payload" > "${FAKE_WEBHOOK_PAYLOAD:?}"
  exit 0
fi

exit 1
FAKE_CURL

  chmod +x "$TEST_TMP/bin/docker" "$TEST_TMP/bin/curl"
}

test_payload_builds_current_to_new_field(){
  setup_case
  write_fakes
  local payload_file="$TEST_TMP/payload.json"

  PATH="$TEST_TMP/bin:$PATH" \
    DISCORD_RELEASES_WEBHOOK="https://discord.test/webhook" \
    FAKE_WEBHOOK_PAYLOAD="$payload_file" \
    "$SCRIPT" "ghcr.io/acme/app:1.0" "app" "1.0" > "$TEST_TMP/output.log" 2>&1 || fail "release note script failed"

  [[ -s "$payload_file" ]] || fail "webhook payload was not captured"
  jq -e '.embeds[0].fields[2].value == "1.0 \u2192 2.0"' "$payload_file" >/dev/null || fail "Current to New field was not rendered"
  teardown_case
}

test_semver_major_bump_marks_breaking(){
  setup_case
  write_fakes
  local payload_file="$TEST_TMP/payload.json"

  PATH="$TEST_TMP/bin:$PATH" \
    DISCORD_RELEASES_WEBHOOK="https://discord.test/webhook" \
    FAKE_WEBHOOK_PAYLOAD="$payload_file" \
    FAKE_RELEASE_TAG="2.0.0" \
    FAKE_RELEASE_BODY=$'## Changes\n- Routine maintenance' \
    "$SCRIPT" "ghcr.io/acme/app:1.9.9" "app" "1.9.9" > "$TEST_TMP/output.log" 2>&1 || fail "release note script failed"

  [[ -s "$payload_file" ]] || fail "webhook payload was not captured"
  jq -e '.embeds[0].fields[0].value == "yes"' "$payload_file" >/dev/null || fail "major bump was not marked breaking"
  teardown_case
}

run_test(){
  local name="$1"
  printf 'running %s\n' "$name"
  "$name"
  printf 'ok - %s\n' "$name"
}

main(){
  run_test test_payload_builds_current_to_new_field
  run_test test_semver_major_bump_marks_breaking
}

trap teardown_case EXIT
main "$@"

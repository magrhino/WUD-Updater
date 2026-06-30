#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SCRIPT="$REPO_ROOT/wud/http-trigger.sh"
TEST_TMP=""

fail(){
  printf 'not ok - %s\n' "$*" >&2
  exit 1
}

setup_case(){
  TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-http-trigger-test.XXXXXX")"
  mkdir -p "$TEST_TMP/bin"
  cat > "$TEST_TMP/bin/curl" <<'FAKE_CURL'
#!/usr/bin/env bash
printf '%s\n' "$@" > "${CURL_ARGS_FILE:?}"
FAKE_CURL
  chmod +x "$TEST_TMP/bin/curl"
}

teardown_case(){
  [[ -n "${TEST_TMP:-}" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
  TEST_TMP=""
}

assert_arg(){
  local expected="$1"
  grep -Fx -- "$expected" "$TEST_TMP/curl.args" >/dev/null || fail "missing curl arg: $expected"
}

test_posts_wud_payload(){
  setup_case
  PATH="$TEST_TMP/bin:$PATH" \
    CURL_ARGS_FILE="$TEST_TMP/curl.args" \
    WUDUP_TRIGGER_TOKEN=secret \
    update_available=true \
    id=docker.local.app \
    name=app \
    image_name=repo/app \
    image_tag_value=1.0 \
    "$SCRIPT"

  assert_arg "Authorization: Bearer secret"
  assert_arg "--connect-timeout"
  assert_arg "5"
  assert_arg "--max-time"
  assert_arg "20"
  assert_arg '{"updateAvailable":true,"id":"docker.local.app","container_id":"","name":"app","image_name":"repo/app","image":{"name":"repo/app","tag":"1.0"}}'
  assert_arg "http://wudup:7417/api/v1/wud/triggers/update"
  teardown_case
}

test_token_file_and_false_update(){
  setup_case
  printf 'file-secret\n' > "$TEST_TMP/token"
  PATH="$TEST_TMP/bin:$PATH" \
    CURL_ARGS_FILE="$TEST_TMP/curl.args" \
    WUDUP_TRIGGER_TOKEN_FILE="$TEST_TMP/token" \
    update_available=false \
    "$SCRIPT"

  assert_arg "Authorization: Bearer file-secret"
  assert_arg '{"updateAvailable":false,"id":"","container_id":"","name":"","image_name":"","image":{"name":"","tag":""}}'
  teardown_case
}

test_missing_update_available_fails_closed(){
  setup_case
  PATH="$TEST_TMP/bin:$PATH" \
    CURL_ARGS_FILE="$TEST_TMP/curl.args" \
    WUDUP_TRIGGER_TOKEN=secret \
    "$SCRIPT"

  assert_arg '{"updateAvailable":false,"id":"","container_id":"","name":"","image_name":"","image":{"name":"","tag":""}}'
  teardown_case
}

test_missing_token_fails_before_curl(){
  setup_case
  if PATH="$TEST_TMP/bin:$PATH" CURL_ARGS_FILE="$TEST_TMP/curl.args" "$SCRIPT" 2>"$TEST_TMP/err"; then
    fail "missing token unexpectedly succeeded"
  fi
  grep -q "WUDUP_TRIGGER_TOKEN" "$TEST_TMP/err" || fail "missing token error not reported"
  [[ ! -e "$TEST_TMP/curl.args" ]] || fail "curl ran without a token"
  teardown_case
}

run_test(){
  local name="$1"
  printf 'running %s\n' "$name"
  "$name"
  printf 'ok - %s\n' "$name"
}

trap teardown_case EXIT
run_test test_posts_wud_payload
run_test test_token_file_and_false_update
run_test test_missing_update_available_fails_closed
run_test test_missing_token_fails_before_curl

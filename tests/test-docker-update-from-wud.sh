#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SCRIPT="$REPO_ROOT/bin/docker-update-from-wud"
FAKE_BIN="$REPO_ROOT/tests/fakes"
TEST_TMP=""
BASE=""
WUD_FILE=""
LOG_DIR=""
FAKE_ROOT=""
LAST_STATUS=0

fail(){
  printf 'not ok - %s\n' "$*" >&2
  if [[ -n "${TEST_TMP:-}" && -f "$TEST_TMP/output.log" ]]; then
    sed 's/^/# /' "$TEST_TMP/output.log" >&2 || true
  fi
  if [[ -n "${FAKE_ROOT:-}" && -f "$FAKE_ROOT/calls.log" ]]; then
    printf '# calls:\n' >&2
    sed 's/^/# /' "$FAKE_ROOT/calls.log" >&2 || true
  fi
  exit 1
}

safe_name(){
  printf '%s' "$1" | sed 's/[^A-Za-z0-9._-]/_/g'
}

setup_case(){
  TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-updater-test.XXXXXX")"
  BASE="$TEST_TMP/base"
  WUD_FILE="$TEST_TMP/images.todo"
  LOG_DIR="$TEST_TMP/logs"
  FAKE_ROOT="$TEST_TMP/fake"
  mkdir -p "$BASE" "$LOG_DIR" "$FAKE_ROOT/images" "$FAKE_ROOT/stacks" "$FAKE_ROOT/containers"
  : > "$FAKE_ROOT/containers.tsv"
  : > "$FAKE_ROOT/calls.log"
}

teardown_case(){
  [[ -n "${TEST_TMP:-}" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
  TEST_TMP=""
}

make_stack(){
  local id="$1" dir="$2" file="$3"
  mkdir -p "$dir" "$FAKE_ROOT/stacks/$id"
  printf '%s\n' "$id" > "$dir/.fake-docker-id"
  : > "$dir/$file"
  : > "$FAKE_ROOT/stacks/$id/images.txt"
  : > "$FAKE_ROOT/stacks/$id/services.txt"
  : > "$FAKE_ROOT/stacks/$id/service-images.tsv"
  : > "$FAKE_ROOT/stacks/$id/cids.txt"
}

add_service(){
  local id="$1" service="$2" image="$3" cid
  cid="${4-cid-$id-$service}"
  {
    printf 'services:\n'
    printf '  %s:\n' "$service"
    printf '    image: %s\n' "$image"
  } >> "$BASE/$id/docker-compose.yml"
  printf '%s\n' "$service" >> "$FAKE_ROOT/stacks/$id/services.txt"
  printf '%s\n' "$image" >> "$FAKE_ROOT/stacks/$id/images.txt"
  printf '%s\t%s\n' "$service" "$image" >> "$FAKE_ROOT/stacks/$id/service-images.tsv"
  if [[ -n "$cid" ]]; then
    printf '%s\n' "$cid" >> "$FAKE_ROOT/stacks/$id/cids.txt"
    printf '%s\n' "$cid" > "$FAKE_ROOT/stacks/$id/cids-$service.txt"
    printf '/%s|running|healthy|0|0\n' "$cid" > "$FAKE_ROOT/containers/$cid.summary"
  fi
}

make_single_service_stack(){
  local id="$1" dir="$2" file="$3" image="$4" cid
  cid="${5-cid-$id}"
  make_stack "$id" "$dir" "$file"
  add_service "$id" app "$image" "$cid"
}

set_image_state(){
  local image="$1" id="$2" digest="${3:-}" safe
  safe="$(safe_name "$image")"
  printf '%s\n' "$id" > "$FAKE_ROOT/images/$safe.id"
  if [[ -n "$digest" ]]; then
    printf '%s@%s\n' "$image" "$digest" > "$FAKE_ROOT/images/$safe.digests"
  else
    : > "$FAKE_ROOT/images/$safe.digests"
  fi
}

set_image_after_pull(){
  local image="$1" id="$2" digest="${3:-}" safe
  safe="$(safe_name "$image")"
  printf '%s\n' "$id" > "$FAKE_ROOT/images/$safe.after_id"
  if [[ -n "$digest" ]]; then
    printf '%s@%s\n' "$image" "$digest" > "$FAKE_ROOT/images/$safe.after_digests"
  else
    : > "$FAKE_ROOT/images/$safe.after_digests"
  fi
}

run_script(){
  LAST_STATUS=0
  PATH="$FAKE_BIN:$PATH" FAKE_DOCKER_ROOT="$FAKE_ROOT" \
    "$SCRIPT" --base "$BASE" --file "$WUD_FILE" --log-dir "$LOG_DIR" --max-wait 0 --no-color "$@" \
    > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
}

assert_status(){
  local expected="$1"
  [[ "$LAST_STATUS" == "$expected" ]] || fail "expected status $expected, got $LAST_STATUS"
}

assert_file_equals(){
  local file="$1" expected="$2" actual
  actual="$(cat "$file")"
  [[ "$actual" == "$expected" ]] || fail "unexpected content in $file; expected [$expected], got [$actual]"
}

assert_calls_contain(){
  local pattern="$1"
  grep -Eq "$pattern" "$FAKE_ROOT/calls.log" || fail "calls did not contain pattern: $pattern"
}

assert_calls_not_contain(){
  local pattern="$1"
  if grep -Eq "$pattern" "$FAKE_ROOT/calls.log"; then
    fail "calls unexpectedly contained pattern: $pattern"
  fi
}

line_number(){
  local pattern="$1"
  grep -nE "$pattern" "$FAKE_ROOT/calls.log" | head -n 1 | cut -d: -f1
}

test_dry_run_no_mutation(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:new

  run_script --dry-run

  assert_status 0
  assert_file_equals "$WUD_FILE" 'repo/app:latest'
  assert_calls_not_contain 'compose -f .* pull'
  assert_calls_not_contain 'compose -f .* stop'
  assert_calls_not_contain 'compose -f .* down'
  assert_calls_not_contain 'compose -f .* up -d'
  teardown_case
}

test_confirm_required_blocks_mutation(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:new

  run_script

  assert_status 1
  assert_file_equals "$WUD_FILE" 'repo/app:latest'
  assert_calls_not_contain 'compose -f .* pull'
  assert_calls_not_contain 'compose -f .* stop'
  assert_calls_not_contain 'compose -f .* down'
  assert_calls_not_contain 'compose -f .* up -d'
  teardown_case
}

test_one_line_two_stacks_one_fails_keeps_line(){
  setup_case
  printf 'repo/app\n' > "$WUD_FILE"
  make_single_service_stack one "$BASE/one" docker-compose.yml repo/app:one cid-one
  make_single_service_stack two "$BASE/two" docker-compose.yml repo/app:two cid-two
  set_image_state repo/app:one old-one sha256:old-one
  set_image_after_pull repo/app:one new-one sha256:new-one
  set_image_state repo/app:two old-two sha256:old-two
  set_image_after_pull repo/app:two new-two sha256:new-two
  : > "$FAKE_ROOT/stacks/two/up_fail"

  run_script --yes

  assert_status 1
  assert_file_equals "$WUD_FILE" 'repo/app'
  teardown_case
}

test_expected_sha_mismatch_prevents_cleanup(){
  setup_case
  printf 'repo/app:latest sha256=good\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:bad

  run_script --yes

  assert_status 1
  assert_file_equals "$WUD_FILE" 'repo/app:latest sha256=good'
  assert_calls_not_contain 'compose -f .* up -d'
  teardown_case
}

test_expected_sha_match_allows_cleanup(){
  setup_case
  printf 'repo/app@sha256:good\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:good

  run_script --yes

  assert_status 0
  assert_file_equals "$WUD_FILE" ''
  teardown_case
}

test_stack_level_digest_cleanup_handles_no_service_map(){
  setup_case
  printf 'repo/app@sha256:good\n' > "$WUD_FILE"
  make_stack app "$BASE/app" docker-compose.yml
  printf 'repo/app:latest\n' > "$FAKE_ROOT/stacks/app/images.txt"
  printf 'cid-app\n' > "$FAKE_ROOT/stacks/app/cids.txt"
  printf '/cid-app|running|healthy|0|0\n' > "$FAKE_ROOT/containers/cid-app.summary"
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:good

  run_script --yes --mode stop

  assert_status 0
  assert_file_equals "$WUD_FILE" ''
  assert_calls_contain 'compose -f docker-compose.yml down'
  assert_calls_contain 'compose -f docker-compose.yml up -d --remove-orphans$'
  teardown_case
}

test_empty_health_ps_fails(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest ""
  : > "$FAKE_ROOT/stacks/app/cids.txt"
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:new

  run_script --yes

  assert_status 1
  assert_file_equals "$WUD_FILE" 'repo/app:latest'
  teardown_case
}

test_comments_and_blank_lines_preserved(){
  setup_case
  printf '# header\n\nrepo/app:latest\n# footer\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:new

  run_script --yes

  assert_status 0
  assert_file_equals "$WUD_FILE" '# header

# footer'
  teardown_case
}

test_paths_with_spaces(){
  setup_case
  BASE="$TEST_TMP/base with spaces"
  WUD_FILE="$TEST_TMP/wud file.todo"
  LOG_DIR="$TEST_TMP/log dir"
  mkdir -p "$BASE" "$LOG_DIR"
  printf 'repo/app:latest\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:new

  run_script --yes

  assert_status 0
  assert_file_equals "$WUD_FILE" ''
  assert_calls_contain 'compose -f docker-compose.yml up -d'
  teardown_case
}

test_live_mode_does_not_stop_or_down(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:new

  run_script --yes --mode live

  assert_status 0
  assert_calls_not_contain 'compose -f .* stop'
  assert_calls_not_contain 'compose -f .* down'
  assert_calls_contain 'compose -f .* up -d'
  teardown_case
}

test_stop_mode_stops_before_up(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:new

  run_script --yes --mode stop

  assert_status 0
  local stop_line up_line
  stop_line="$(line_number 'compose -f .* stop app')"
  up_line="$(line_number 'compose -f .* up -d .*app')"
  [[ -n "$stop_line" && -n "$up_line" && "$stop_line" -lt "$up_line" ]] || fail "expected stop before up"
  teardown_case
}

test_service_scoped_update_only_touches_matched_service(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"
  make_stack stack "$BASE/stack" docker-compose.yml
  add_service stack app repo/app:latest cid-app
  add_service stack db repo/db:latest cid-db
  set_image_state repo/app:latest old-app sha256:old-app
  set_image_after_pull repo/app:latest new-app sha256:new-app
  set_image_state repo/db:latest old-db sha256:old-db
  set_image_after_pull repo/db:latest new-db sha256:new-db

  run_script --yes --mode stop

  assert_status 0
  assert_file_equals "$WUD_FILE" ''
  assert_calls_contain 'compose -f docker-compose.yml pull app'
  assert_calls_contain 'compose -f docker-compose.yml stop app'
  assert_calls_contain 'compose -f docker-compose.yml up -d .* app'
  assert_calls_not_contain 'compose -f docker-compose.yml pull db'
  assert_calls_not_contain 'compose -f docker-compose.yml stop db'
  assert_calls_not_contain 'compose -f docker-compose.yml down'
  teardown_case
}

run_test(){
  local name="$1"
  printf 'running %s\n' "$name"
  "$name"
  printf 'ok - %s\n' "$name"
}

main(){
  run_test test_dry_run_no_mutation
  run_test test_confirm_required_blocks_mutation
  run_test test_one_line_two_stacks_one_fails_keeps_line
  run_test test_expected_sha_mismatch_prevents_cleanup
  run_test test_expected_sha_match_allows_cleanup
  run_test test_stack_level_digest_cleanup_handles_no_service_map
  run_test test_empty_health_ps_fails
  run_test test_comments_and_blank_lines_preserved
  run_test test_paths_with_spaces
  run_test test_live_mode_does_not_stop_or_down
  run_test test_stop_mode_stops_before_up
  run_test test_service_scoped_update_only_touches_matched_service
}

trap teardown_case EXIT
main "$@"

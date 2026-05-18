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
  local env_args=()
  while [[ "$#" -gt 0 && "$1" == *=* ]]; do
    env_args+=("$1")
    shift
  done

  LAST_STATUS=0
  if ((${#env_args[@]})); then
    PATH="$FAKE_BIN:$PATH" FAKE_DOCKER_ROOT="$FAKE_ROOT" \
      env "${env_args[@]}" "$SCRIPT" --base "$BASE" --file "$WUD_FILE" --log-dir "$LOG_DIR" --max-wait 0 --no-color "$@" \
      > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
  else
    PATH="$FAKE_BIN:$PATH" FAKE_DOCKER_ROOT="$FAKE_ROOT" \
      "$SCRIPT" --base "$BASE" --file "$WUD_FILE" --log-dir "$LOG_DIR" --max-wait 0 --no-color "$@" \
      > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
  fi
}

run_script_with_home_defaults(){
  local home_dir="$1"
  shift

  LAST_STATUS=0
  PATH="$FAKE_BIN:$PATH" HOME="$home_dir" FAKE_DOCKER_ROOT="$FAKE_ROOT" \
    "$SCRIPT" --log-dir "$LOG_DIR" --max-wait 0 --no-color "$@" \
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

stat_owner_group(){
  local file="$1"
  if stat -c '%u:%g' "$file" >/dev/null 2>&1; then
    stat -c '%u:%g' "$file"
  else
    stat -f '%u:%g' "$file"
  fi
}

stat_mode(){
  local file="$1"
  if stat -c '%a' "$file" >/dev/null 2>&1; then
    stat -c '%a' "$file"
  else
    stat -f '%Lp' "$file"
  fi
}

latest_log_file(){
  find "$LOG_DIR" -type f -name 'update-from-wud-v2-*.log' -print | sort | tail -n 1
}

test_help_exits_successfully(){
  setup_case

  run_script --help

  assert_status 0
  grep -q '^Usage:' "$TEST_TMP/output.log" || fail "help output did not include usage"
  assert_calls_not_contain '.'
  teardown_case
}

test_default_dispatch_uses_python_backend(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:new

  run_script --dry-run

  assert_status 0
  grep -q 'PTY     : python subprocess' "$TEST_TMP/output.log" || fail "default dispatcher did not use Python backend"
  teardown_case
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

test_default_base_uses_home_docker(){
  setup_case
  local home_dir="$TEST_TMP/home"
  BASE="$home_dir/docker"
  WUD_FILE="$BASE/wud/out/images.todo"
  mkdir -p "$BASE/wud/out" "$LOG_DIR"
  printf 'repo/app:latest\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:new

  run_script_with_home_defaults "$home_dir" --dry-run

  assert_status 0
  grep -q "Base    : $BASE" "$TEST_TMP/output.log" || fail "default base did not use HOME/docker"
  grep -q "WUD file: $WUD_FILE" "$TEST_TMP/output.log" || fail "default WUD file did not use HOME/docker"
  assert_calls_not_contain 'compose -f .* pull'
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

test_only_lines_updates_subset_and_keeps_unselected(){
  setup_case
  printf 'repo/app:one\nrepo/app:two\n' > "$WUD_FILE"
  make_single_service_stack one "$BASE/one" docker-compose.yml repo/app:one cid-one
  make_single_service_stack two "$BASE/two" docker-compose.yml repo/app:two cid-two
  set_image_state repo/app:one old-one sha256:old-one
  set_image_after_pull repo/app:one new-one sha256:new-one
  set_image_state repo/app:two old-two sha256:old-two
  set_image_after_pull repo/app:two new-two sha256:new-two

  run_script --yes --only-lines 2

  assert_status 0
  assert_file_equals "$WUD_FILE" 'repo/app:one'
  teardown_case
}

test_only_lines_keeps_unselected_duplicate_raw_line(){
  setup_case
  printf 'repo/app:latest\nrepo/app:latest\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:new

  run_script --yes --only-lines 1

  assert_status 0
  assert_file_equals "$WUD_FILE" 'repo/app:latest'
  teardown_case
}

test_remove_lines_before_run_removes_requested_lines_before_pull(){
  setup_case
  printf 'repo/app:one\nrepo/app:two\nrepo/app:three\n' > "$WUD_FILE"
  make_single_service_stack two "$BASE/two" docker-compose.yml repo/app:two cid-two
  set_image_state repo/app:two old-two sha256:old-two
  set_image_after_pull repo/app:two new-two sha256:new-two
  cat > "$FAKE_ROOT/post-pull-hook" <<'HOOK'
#!/usr/bin/env bash
cat "${HOOK_WUD_FILE:?}" > "${FAKE_DOCKER_ROOT:?}/wud-during-pull.txt"
HOOK
  chmod +x "$FAKE_ROOT/post-pull-hook"

  run_script HOOK_WUD_FILE="$WUD_FILE" --yes --only-lines 2 --remove-lines-before-run 1,3

  assert_status 0
  assert_file_equals "$FAKE_ROOT/wud-during-pull.txt" ''
  assert_file_equals "$WUD_FILE" ''
  teardown_case
}

test_same_image_wud_callback_survives_successful_update(){
  setup_case
  printf 'repo/app:one\nrepo/app:two\nrepo/app:three\n' > "$WUD_FILE"
  make_single_service_stack two "$BASE/two" docker-compose.yml repo/app:two cid-two
  set_image_state repo/app:two old-two sha256:old-two
  set_image_after_pull repo/app:two new-two sha256:new-two
  cat > "$FAKE_ROOT/post-pull-hook" <<'HOOK'
#!/usr/bin/env bash
env WUD_OUT_FILE="${HOOK_WUD_FILE:?}" WUD_LOCK_TIMEOUT=0 update_available=true image_name=repo/app image_tag_value=two sh "${HOOK_APPEND_SCRIPT:?}"
HOOK
  chmod +x "$FAKE_ROOT/post-pull-hook"

  run_script HOOK_WUD_FILE="$WUD_FILE" HOOK_APPEND_SCRIPT="$REPO_ROOT/wud/append-updates.sh" --yes --only-lines 2 --remove-lines-before-run 1,3

  assert_status 0
  assert_file_equals "$WUD_FILE" 'repo/app:two'
  teardown_case
}

test_cleanup_does_not_resurrect_replaced_unselected_line(){
  setup_case
  printf 'repo/app:one\nrepo/app:two\n' > "$WUD_FILE"
  make_single_service_stack two "$BASE/two" docker-compose.yml repo/app:two cid-two
  set_image_state repo/app:two old-two sha256:old-two
  set_image_after_pull repo/app:two new-two sha256:new-two
  cat > "$FAKE_ROOT/post-pull-hook" <<'HOOK'
#!/usr/bin/env bash
set -Eeuo pipefail
tmp="${HOOK_WUD_FILE:?}.hook"
awk '$1 != "repo/app:one" {print}' "$HOOK_WUD_FILE" > "$tmp"
printf 'repo/app:one sha256=new\n' >> "$tmp"
mv "$tmp" "$HOOK_WUD_FILE"
HOOK
  chmod +x "$FAKE_ROOT/post-pull-hook"

  run_script HOOK_WUD_FILE="$WUD_FILE" --yes --only-lines 2

  assert_status 0
  assert_file_equals "$WUD_FILE" 'repo/app:one sha256=new'
  teardown_case
}

test_parent_wud_lock_is_reused_and_released(){
  setup_case
  printf 'repo/app:one\nrepo/app:two\nrepo/app:three\n' > "$WUD_FILE"
  make_single_service_stack two "$BASE/two" docker-compose.yml repo/app:two cid-two
  set_image_state repo/app:two old-two sha256:old-two
  set_image_after_pull repo/app:two new-two sha256:new-two
  mkdir "$WUD_FILE.lock"

  run_script WUD_LOCK_HELD_BY_PARENT=1 WUD_LOCK_TIMEOUT=0 --yes --only-lines 2 --remove-lines-before-run 1,3

  assert_status 0
  assert_file_equals "$WUD_FILE" ''
  [[ ! -d "$WUD_FILE.lock" ]] || fail "parent WUD lock was not released"
  teardown_case
}

test_invalid_line_spec_fails_before_docker_calls(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:new

  run_script --yes --only-lines 0

  assert_status 1
  assert_file_equals "$WUD_FILE" 'repo/app:latest'
  [[ ! -s "$FAKE_ROOT/calls.log" ]] || fail "docker was called for invalid line spec"
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

test_sha_suffix_does_not_block_cleanup(){
  setup_case
  printf 'repo/app:latest sha256=good\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:bad

  run_script --yes

  assert_status 0
  assert_file_equals "$WUD_FILE" ''
  assert_calls_contain 'compose -f docker-compose.yml up -d .* app'
  teardown_case
}

test_tag_update_requires_explicit_flag(){
  setup_case
  printf 'repo/app:1.0 tag=2.0\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:1.0
  set_image_state repo/app:1.0 old sha256:old
  set_image_after_pull repo/app:2.0 new sha256:new

  run_script --yes

  assert_status 0
  assert_file_equals "$WUD_FILE" 'repo/app:1.0 tag=2.0'
  grep -q -- 'require --allow-tag-updates' "$TEST_TMP/output.log" || fail "missing tag opt-in message"
  grep -q -- 'image: repo/app:1.0' "$BASE/app/docker-compose.yml" || fail "compose file was rewritten without tag opt-in"
  assert_calls_not_contain 'compose -f .* pull'
  assert_calls_not_contain 'compose -f .* up -d'
  teardown_case
}

test_tag_update_dry_run_does_not_rewrite_compose(){
  setup_case
  printf 'repo/app:1.0 tag=2.0\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:1.0
  set_image_state repo/app:1.0 old sha256:old
  set_image_after_pull repo/app:2.0 new sha256:new

  run_script --dry-run --allow-tag-updates

  assert_status 0
  assert_file_equals "$WUD_FILE" 'repo/app:1.0 tag=2.0'
  grep -q -- 'repo/app:1.0 -> repo/app:2.0 (tag update)' "$TEST_TMP/output.log" || fail "dry-run did not show tag update plan"
  grep -q -- 'image: repo/app:1.0' "$BASE/app/docker-compose.yml" || fail "dry-run rewrote compose file"
  assert_calls_not_contain 'compose -f .* pull'
  assert_calls_not_contain 'compose -f .* up -d'
  teardown_case
}

test_allowed_tag_update_rewrites_compose_and_cleans_line(){
  setup_case
  printf 'repo/app:1.0 tag=2.0\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:1.0
  set_image_state repo/app:1.0 old sha256:old
  set_image_after_pull repo/app:2.0 new sha256:new

  run_script --yes --allow-tag-updates

  assert_status 0
  assert_file_equals "$WUD_FILE" ''
  grep -q -- 'image: repo/app:2.0' "$BASE/app/docker-compose.yml" || fail "compose file did not contain new tag"
  assert_calls_contain 'compose -f docker-compose.yml pull app'
  assert_calls_contain 'compose -f docker-compose.yml up -d .* app'
  teardown_case
}

test_unhealthy_tag_update_rolls_back_and_writes_incident_log(){
  setup_case
  printf 'repo/app:1.0 tag=2.0\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:1.0 cid-app
  set_image_state repo/app:1.0 old sha256:old
  set_image_after_pull repo/app:2.0 new sha256:new
  printf 'new tag failed health check\n' > "$FAKE_ROOT/containers/cid-app.healthlog"
  cat > "$FAKE_ROOT/post-up-hook" <<'HOOK'
#!/usr/bin/env bash
set -Eeuo pipefail
compose_file="${2:?compose file is required}"
if grep -q 'repo/app:2.0' "$compose_file"; then
  printf '/cid-app|running|unhealthy|1|0\n' > "${FAKE_DOCKER_ROOT:?}/containers/cid-app.summary"
else
  printf '/cid-app|running|healthy|0|0\n' > "${FAKE_DOCKER_ROOT:?}/containers/cid-app.summary"
fi
HOOK
  chmod +x "$FAKE_ROOT/post-up-hook"

  run_script --yes --allow-tag-updates

  assert_status 1
  assert_file_equals "$WUD_FILE" 'repo/app:1.0 tag=2.0'
  grep -q -- 'image: repo/app:1.0' "$BASE/app/docker-compose.yml" || fail "compose file was not rolled back"
  local incident
  incident="$(find "$BASE/app" -type f -name 'error-2.0-*.logs' -print | sort | tail -n 1)"
  [[ -n "$incident" && -f "$incident" ]] || fail "expected tag incident log"
  grep -q -- 'reason=health-failed' "$incident" || fail "incident log missing failure reason"
  grep -q -- 'repo/app:1.0 -> repo/app:2.0' "$incident" || fail "incident log missing attempted tag"
  grep -q -- 'health=unhealthy' "$incident" || fail "incident log missing unhealthy status"
  grep -q -- 'new tag failed health check' "$incident" || fail "incident log missing health output"
  grep -q -- 'manual_review_required=no' "$incident" || fail "incident log should report successful rollback"
  teardown_case
}

test_pinned_digest_mismatch_prevents_cleanup(){
  setup_case
  printf 'repo/app@sha256:good\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:bad

  run_script --yes

  assert_status 1
  assert_file_equals "$WUD_FILE" 'repo/app@sha256:good'
  assert_calls_not_contain 'compose -f .* up -d'
  teardown_case
}

test_pinned_digest_match_allows_cleanup(){
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

test_cleanup_removes_successful_raw_line_not_current_line_number(){
  setup_case
  printf 'repo/b:latest\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/b:latest
  set_image_state repo/b:latest old sha256:old
  set_image_after_pull repo/b:latest new sha256:new
  cat > "$FAKE_ROOT/post-pull-hook" <<'HOOK'
#!/usr/bin/env bash
set -Eeuo pipefail
env WUD_OUT_FILE="${HOOK_WUD_FILE:?}" update_available=true image_name=repo/a image_tag_value=latest sh "${HOOK_APPEND_SCRIPT:?}"
HOOK
  chmod +x "$FAKE_ROOT/post-pull-hook"

  run_script HOOK_WUD_FILE="$WUD_FILE" HOOK_APPEND_SCRIPT="$REPO_ROOT/wud/append-updates.sh" --yes

  assert_status 0
  assert_file_equals "$WUD_FILE" 'repo/a:latest'
  [[ ! -d "$WUD_FILE.lock" ]] || fail "WUD lock directory was left behind"
  teardown_case
}

test_cleanup_preserves_wud_file_owner_and_mode(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"
  chmod 660 "$WUD_FILE"
  local expected_owner expected_mode
  expected_owner="$(stat_owner_group "$WUD_FILE")"
  expected_mode="$(stat_mode "$WUD_FILE")"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:new

  run_script --yes

  assert_status 0
  assert_file_equals "$WUD_FILE" ''
  [[ "$(stat_owner_group "$WUD_FILE")" == "$expected_owner" ]] || fail "WUD file owner was not preserved"
  [[ "$(stat_mode "$WUD_FILE")" == "$expected_mode" ]] || fail "WUD file mode was not preserved"
  teardown_case
}

test_out_owner_config_accepts_out_guid_for_logs_and_cleanup(){
  setup_case
  local uid gid log_file
  uid="$(id -u)"
  gid="$(id -g)"
  printf 'repo/app:latest\n' > "$WUD_FILE"
  make_single_service_stack app "$BASE/app" docker-compose.yml repo/app:latest
  set_image_state repo/app:latest old sha256:old
  set_image_after_pull repo/app:latest new sha256:new

  run_script OUT_UID="$uid" OUT_GUID="$gid" --yes

  assert_status 0
  assert_file_equals "$WUD_FILE" ''
  log_file="$(latest_log_file)"
  [[ -n "$log_file" && -f "$log_file" ]] || fail "expected updater log file"
  [[ "$(stat_owner_group "$WUD_FILE")" == "$uid:$gid" ]] || fail "WUD file owner did not match OUT_UID:OUT_GUID"
  [[ "$(stat_owner_group "$LOG_DIR")" == "$uid:$gid" ]] || fail "log directory owner did not match OUT_UID:OUT_GUID"
  [[ "$(stat_owner_group "$log_file")" == "$uid:$gid" ]] || fail "log file owner did not match OUT_UID:OUT_GUID"
  grep -q "Owner   : $uid:$gid" "$TEST_TMP/output.log" || fail "owner config was not reported"
  teardown_case
}

test_out_owner_config_requires_uid_and_group(){
  setup_case
  printf 'repo/app:latest\n' > "$WUD_FILE"

  run_script OUT_UID="$(id -u)" --dry-run

  assert_status 1
  grep -q "OUT_UID and OUT_GID/OUT_GUID must be set together" "$TEST_TMP/output.log" || fail "missing owner config validation error"
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
  run_test test_help_exits_successfully
  run_test test_default_dispatch_uses_python_backend
  run_test test_dry_run_no_mutation
  run_test test_default_base_uses_home_docker
  run_test test_confirm_required_blocks_mutation
  run_test test_only_lines_updates_subset_and_keeps_unselected
  run_test test_only_lines_keeps_unselected_duplicate_raw_line
  run_test test_remove_lines_before_run_removes_requested_lines_before_pull
  run_test test_same_image_wud_callback_survives_successful_update
  run_test test_cleanup_does_not_resurrect_replaced_unselected_line
  run_test test_parent_wud_lock_is_reused_and_released
  run_test test_invalid_line_spec_fails_before_docker_calls
  run_test test_one_line_two_stacks_one_fails_keeps_line
  run_test test_sha_suffix_does_not_block_cleanup
  run_test test_tag_update_requires_explicit_flag
  run_test test_tag_update_dry_run_does_not_rewrite_compose
  run_test test_allowed_tag_update_rewrites_compose_and_cleans_line
  run_test test_unhealthy_tag_update_rolls_back_and_writes_incident_log
  run_test test_pinned_digest_mismatch_prevents_cleanup
  run_test test_pinned_digest_match_allows_cleanup
  run_test test_cleanup_removes_successful_raw_line_not_current_line_number
  run_test test_cleanup_preserves_wud_file_owner_and_mode
  run_test test_out_owner_config_accepts_out_guid_for_logs_and_cleanup
  run_test test_out_owner_config_requires_uid_and_group
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

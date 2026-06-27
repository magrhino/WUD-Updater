#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SCRIPT="$REPO_ROOT/wud/append-updates.sh"
APP_LATEST_IMAGE="repo/app:latest"
OLD_LATEST_IMAGE="repo/old:latest"
LOCK_CREATE_ERROR="Failed to create WUD file lock"
STALE_DIGEST="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
TEST_TMP=""
OUT_FILE=""
LAST_STATUS=0

fail(){
  printf 'not ok - %s\n' "$*" >&2
  if [[ -n "${TEST_TMP:-}" && -f "$TEST_TMP/output.log" ]]; then
    sed 's/^/# /' "$TEST_TMP/output.log" >&2 || true
  fi
  exit 1
}

setup_case(){
  TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-append-test.XXXXXX")"
  OUT_FILE="$TEST_TMP/images.todo"
}

teardown_case(){
  [[ -n "${TEST_TMP:-}" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
  TEST_TMP=""
}

run_script(){
  LAST_STATUS=0
  env WUD_OUT_FILE="$OUT_FILE" "$@" sh "$SCRIPT" > "$TEST_TMP/output.log" 2>&1 || LAST_STATUS=$?
}

assert_file_equals(){
  local expected="$1" actual
  actual="$(cat "$OUT_FILE")"
  [[ "$actual" == "$expected" ]] || fail "expected [$expected], got [$actual]"
}

assert_file_missing(){
  [[ ! -e "$OUT_FILE" ]] || fail "expected $OUT_FILE to be absent"
}

assert_status(){
  local expected="$1"
  [[ "$LAST_STATUS" == "$expected" ]] || fail "expected status $expected, got $LAST_STATUS"
}

assert_no_temp_files(){
  [[ ! -e "$OUT_FILE.tmp" ]] || fail "fixed temp file was left behind"
  [[ -z "$(find "$TEST_TMP" -maxdepth 1 -name '.images.todo.*' -print)" ]] || fail "unique temp file was left behind"
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

hex_digest(){
  printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
}

test_update_gate_does_not_create_file(){
  setup_case
  run_script update_available=false image_name=repo/app image_tag_value=latest
  assert_file_missing
  teardown_case
}

test_image_tag_ignores_result_digest(){
  setup_case
  run_script update_available=true image_name=repo/app image_tag_value=1.2 result_digest="$(hex_digest)"
  assert_file_equals "repo/app:1.2"
  teardown_case
}

test_tag_update_writes_proposed_tag(){
  setup_case
  run_script update_available=true image_name=linuxserver/qbittorrent image_tag_value=5.1.4 update_kind_kind=tag update_kind_remote_value=5.2.0 result_digest="$(hex_digest)"
  assert_file_equals "linuxserver/qbittorrent:5.1.4 tag=5.2.0 sha256=sha256:$(hex_digest)"
  teardown_case
}

test_tag_update_accepts_image_remote_value(){
  setup_case
  run_script update_available=true image_name=repo/app image_tag_value=1.0 update_kind_kind=tag update_kind_remote_value=repo/app:2.0
  assert_file_equals 'repo/app:1.0 tag=2.0'
  teardown_case
}

test_tag_update_accepts_single_component_image_remote_value(){
  setup_case
  run_script update_available=true image_name=nginx image_tag_value=1.0 update_kind_kind=tag update_kind_remote_value=nginx:2.0
  assert_file_equals 'nginx:1.0 tag=2.0'
  teardown_case
}

test_tag_update_uses_result_tag_fallback(){
  setup_case
  run_script update_available=true image_name=repo/app image_tag_value=1.0 update_kind_kind=tag result_tag=2.0
  assert_file_equals 'repo/app:1.0 tag=2.0'
  teardown_case
}

test_tag_update_omits_digest_when_tag_is_invalid(){
  setup_case
  run_script update_available=true image_name=repo/app image_tag_value=1.0 update_kind_kind=tag update_kind_remote_value='bad tag' result_digest="$(hex_digest)"
  assert_file_equals 'repo/app:1.0'
  teardown_case
}

test_platform_metadata_is_appended(){
  setup_case
  run_script update_available=true image_name=repo/app image_tag_value=1.0 image_os=linux image_architecture=amd64
  assert_file_equals 'repo/app:1.0 platform=linux/amd64'
  teardown_case
}

test_platform_variant_metadata_is_appended(){
  setup_case
  run_script update_available=true image_name=repo/app image_tag_value=1.0 update_kind_kind=tag result_tag=2.0 result_digest="$(hex_digest)" image_os=linux image_architecture=arm image_variant=v7
  assert_file_equals "repo/app:1.0 tag=2.0 platform=linux/arm/v7 sha256=sha256:$(hex_digest)"
  teardown_case
}

test_invalid_platform_metadata_is_omitted(){
  setup_case
  run_script update_available=true image_name=repo/app image_tag_value=1.0 image_os=linux image_architecture='bad/value'
  assert_file_equals 'repo/app:1.0'
  teardown_case
}

test_unknown_platform_metadata_is_omitted_case_insensitively(){
  setup_case
  run_script update_available=true image_name=repo/app image_tag_value=1.0 image_os=linux image_architecture=Unknown
  assert_file_equals 'repo/app:1.0'
  teardown_case
}

test_container_name_fallback(){
  setup_case
  run_script update_available=true name=container-app
  assert_file_equals 'container-app'
  teardown_case
}

test_digest_update_kind_fallback(){
  setup_case
  run_script update_available=true image_name=repo/app image_tag_value=latest update_kind_kind=digest update_kind_remote_value="repo/app@sha256:$(hex_digest)"
  assert_file_equals "$APP_LATEST_IMAGE@sha256:$(hex_digest)"
  teardown_case
}

test_tag_dedupe_replaces_existing_image_line(){
  setup_case
  mkdir -p "$(dirname "$OUT_FILE")"
  printf 'repo/app:1.0 tag=1.1\nrepo/other:latest\n' > "$OUT_FILE"
  run_script update_available=true image_name=repo/app image_tag_value=1.0 update_kind_kind=tag update_kind_remote_value=1.2
  assert_file_equals "repo/app:1.0 tag=1.2
repo/other:latest"
  teardown_case
}

test_invalid_digest_is_omitted(){
  setup_case
  run_script update_available=true image_name=repo/app image_tag_value=latest result_digest=not-a-digest
  assert_file_equals "$APP_LATEST_IMAGE"
  teardown_case
}

test_dedupe_replaces_existing_image_line(){
  setup_case
  mkdir -p "$(dirname "$OUT_FILE")"
  printf 'repo/other:latest\n%s sha256=%s\n' "$APP_LATEST_IMAGE" "$STALE_DIGEST" > "$OUT_FILE"
  run_script update_available=true image_name=repo/app image_tag_value=latest result_digest="$(hex_digest)"
  assert_file_equals "$APP_LATEST_IMAGE
repo/other:latest"
  teardown_case
}

test_dedupe_replaces_existing_digest_pinned_line(){
  setup_case
  mkdir -p "$(dirname "$OUT_FILE")"
  printf 'repo/other:latest\n%s@%s\n' "$APP_LATEST_IMAGE" "$STALE_DIGEST" > "$OUT_FILE"
  run_script update_available=true image_name=repo/app image_tag_value=latest update_kind_kind=digest update_kind_remote_value="repo/app@sha256:$(hex_digest)"
  assert_file_equals "$APP_LATEST_IMAGE@sha256:$(hex_digest)
repo/other:latest"
  teardown_case
}

test_existing_file_mode_and_owner_are_preserved(){
  setup_case
  mkdir -p "$(dirname "$OUT_FILE")"
  printf '%s\n' "$OLD_LATEST_IMAGE" > "$OUT_FILE"
  chmod 660 "$OUT_FILE"
  local expected_owner expected_mode
  expected_owner="$(stat_owner_group "$OUT_FILE")"
  expected_mode="$(stat_mode "$OUT_FILE")"

  run_script update_available=true image_name=repo/app image_tag_value=latest

  assert_status 0
  assert_file_equals "$APP_LATEST_IMAGE
$OLD_LATEST_IMAGE"
  [[ "$(stat_owner_group "$OUT_FILE")" == "$expected_owner" ]] || fail "owner was not preserved"
  [[ "$(stat_mode "$OUT_FILE")" == "$expected_mode" ]] || fail "mode was not preserved"
  teardown_case
}

test_existing_broader_mode_is_preserved(){
  setup_case
  mkdir -p "$(dirname "$OUT_FILE")"
  printf '%s\n' "$OLD_LATEST_IMAGE" > "$OUT_FILE"
  chmod 664 "$OUT_FILE"

  run_script update_available=true image_name=repo/app image_tag_value=latest

  assert_status 0
  [[ "$(stat_mode "$OUT_FILE")" == "664" ]] || fail "broader existing mode was not preserved"
  teardown_case
}

test_new_file_defaults_to_group_writable_mode(){
  setup_case
  run_script update_available=true image_name=repo/app image_tag_value=latest

  assert_status 0
  assert_file_equals "$APP_LATEST_IMAGE"
  [[ "$(stat_mode "$OUT_FILE")" == "660" ]] || fail "new file was not created with 660 mode"
  teardown_case
}

test_owner_config_is_applied_to_rewritten_file(){
  setup_case
  local uid gid
  uid="$(id -u)"
  gid="$(id -g)"

  run_script OUT_UID="$uid" OUT_GID="$gid" update_available=true image_name=repo/app image_tag_value=latest

  assert_status 0
  assert_file_equals "$APP_LATEST_IMAGE"
  [[ "$(stat_owner_group "$OUT_FILE")" == "$uid:$gid" ]] || fail "owner config was not applied"
  [[ "$(stat_mode "$OUT_FILE")" == "660" ]] || fail "owner-configured new file did not use 660 mode"
  teardown_case
}

test_out_guid_alias_is_applied_to_rewritten_file(){
  setup_case
  local uid gid
  uid="$(id -u)"
  gid="$(id -g)"

  run_script OUT_UID="$uid" OUT_GUID="$gid" update_available=true image_name=repo/app image_tag_value=latest

  assert_status 0
  [[ "$(stat_owner_group "$OUT_FILE")" == "$uid:$gid" ]] || fail "OUT_GUID alias was not applied"
  teardown_case
}

test_owner_config_requires_uid_and_group_before_replace(){
  setup_case
  mkdir -p "$(dirname "$OUT_FILE")"
  printf '%s\n' "$OLD_LATEST_IMAGE" > "$OUT_FILE"

  run_script OUT_UID="$(id -u)" update_available=true image_name=repo/app image_tag_value=latest

  assert_status 1
  assert_file_equals "$OLD_LATEST_IMAGE"
  grep -q "OUT_UID and OUT_GID/OUT_GUID must be set together" "$TEST_TMP/output.log" || fail "missing owner config validation error"
  assert_no_temp_files
  teardown_case
}

test_lock_removed_after_success(){
  setup_case
  run_script update_available=true image_name=repo/app image_tag_value=latest
  assert_status 0
  assert_file_equals "$APP_LATEST_IMAGE"
  [[ ! -d "$OUT_FILE.lock" ]] || fail "lock directory was left behind"
  assert_no_temp_files
  teardown_case
}

test_lock_timeout_leaves_file_unchanged(){
  setup_case
  mkdir -p "$(dirname "$OUT_FILE")"
  printf '%s\n' "$OLD_LATEST_IMAGE" > "$OUT_FILE"
  mkdir "$OUT_FILE.lock"

  run_script WUD_LOCK_TIMEOUT=0 update_available=true image_name=repo/app image_tag_value=latest

  assert_status 1
  assert_file_equals "$OLD_LATEST_IMAGE"
  [[ -d "$OUT_FILE.lock" ]] || fail "pre-existing lock directory was removed"
  assert_no_temp_files
  teardown_case
}

test_lock_retries_when_lock_released_during_status_check(){
  setup_case
  mkdir -p "$(dirname "$OUT_FILE")" "$TEST_TMP/bin"
  printf '%s\n' "$OLD_LATEST_IMAGE" > "$OUT_FILE"
  local real_mkdir
  real_mkdir="$(command -v mkdir)"
  cat > "$TEST_TMP/bin/mkdir" <<'FAKE_MKDIR'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$1" == "-p" ]]; then
  exec "$REAL_MKDIR" "$@"
fi

if [[ "$1" == "${WUD_OUT_FILE}.lock" && ! -e "$FAKE_LOCK_RACE_STATE" ]]; then
  : > "$FAKE_LOCK_RACE_STATE"
  "$REAL_MKDIR" "$1"
  rmdir "$1"
  exit 1
fi

exec "$REAL_MKDIR" "$@"
FAKE_MKDIR
  chmod +x "$TEST_TMP/bin/mkdir"

  run_script PATH="$TEST_TMP/bin:$PATH" REAL_MKDIR="$real_mkdir" FAKE_LOCK_RACE_STATE="$TEST_TMP/mkdir-raced" WUD_LOCK_TIMEOUT=2 update_available=true image_name=repo/app image_tag_value=latest

  assert_status 0
  assert_file_equals "$APP_LATEST_IMAGE
$OLD_LATEST_IMAGE"
  assert_no_temp_files
  teardown_case
}

test_lock_failure_when_dir_cannot_be_created(){
  setup_case
  mkdir -p "$(dirname "$OUT_FILE")"
  printf '%s\n' "$OLD_LATEST_IMAGE" > "$OUT_FILE"
  touch "$OUT_FILE.lock"

  run_script WUD_LOCK_TIMEOUT=5 update_available=true image_name=repo/app image_tag_value=latest

  assert_status 1
  assert_file_equals "$OLD_LATEST_IMAGE"
  grep -q "$LOCK_CREATE_ERROR" "$TEST_TMP/output.log" || fail "missing strict error check"
  assert_no_temp_files
  teardown_case
}

test_lock_failure_in_readonly_dir(){
  setup_case
  OUT_FILE="$TEST_TMP/readonly_dir/images.todo"
  mkdir -p "$(dirname "$OUT_FILE")"
  printf '%s\n' "$OLD_LATEST_IMAGE" > "$OUT_FILE"
  chmod 555 "$(dirname "$OUT_FILE")"

  run_script WUD_LOCK_TIMEOUT=5 update_available=true image_name=repo/app image_tag_value=latest

  chmod 755 "$(dirname "$OUT_FILE")"

  assert_status 1
  assert_file_equals "$OLD_LATEST_IMAGE"
  grep -q "$LOCK_CREATE_ERROR" "$TEST_TMP/output.log" || fail "missing strict error check"
  assert_no_temp_files
  teardown_case
}

test_sort_failure_leaves_file_unchanged(){
  setup_case
  mkdir -p "$(dirname "$OUT_FILE")" "$TEST_TMP/bin"
  printf '%s\n' "$OLD_LATEST_IMAGE" > "$OUT_FILE"
  cat > "$TEST_TMP/bin/sort" <<'FAKE_SORT'
#!/usr/bin/env bash
printf 'fake sort failed\n' >&2
exit 42
FAKE_SORT
  chmod +x "$TEST_TMP/bin/sort"

  run_script PATH="$TEST_TMP/bin:$PATH" update_available=true image_name=repo/app image_tag_value=latest

  assert_status 1
  assert_file_equals "$OLD_LATEST_IMAGE"
  grep -q "Failed to sort update entries for $OUT_FILE" "$TEST_TMP/output.log" || fail "missing sort failure error"
  [[ ! -d "$OUT_FILE.lock" ]] || fail "lock directory was left behind"
  assert_no_temp_files
  teardown_case
}

test_replace_failure_leaves_file_unchanged(){
  setup_case
  mkdir -p "$(dirname "$OUT_FILE")" "$TEST_TMP/bin"
  printf '%s\n' "$OLD_LATEST_IMAGE" > "$OUT_FILE"
  cat > "$TEST_TMP/bin/mv" <<'FAKE_MV'
#!/usr/bin/env bash
printf 'fake mv failed\n' >&2
exit 42
FAKE_MV
  chmod +x "$TEST_TMP/bin/mv"

  run_script PATH="$TEST_TMP/bin:$PATH" update_available=true image_name=repo/app image_tag_value=latest

  assert_status 1
  assert_file_equals "$OLD_LATEST_IMAGE"
  grep -q "Failed to replace $OUT_FILE" "$TEST_TMP/output.log" || fail "missing replace failure error"
  [[ ! -d "$OUT_FILE.lock" ]] || fail "lock directory was left behind"
  assert_no_temp_files
  teardown_case
}

run_test(){
  local name="$1"
  printf 'running %s\n' "$name"
  "$name"
  printf 'ok - %s\n' "$name"
}

main(){
  run_test test_update_gate_does_not_create_file
  run_test test_image_tag_ignores_result_digest
  run_test test_tag_update_writes_proposed_tag
  run_test test_tag_update_accepts_image_remote_value
  run_test test_tag_update_accepts_single_component_image_remote_value
  run_test test_tag_update_uses_result_tag_fallback
  run_test test_tag_update_omits_digest_when_tag_is_invalid
  run_test test_platform_metadata_is_appended
  run_test test_platform_variant_metadata_is_appended
  run_test test_invalid_platform_metadata_is_omitted
  run_test test_unknown_platform_metadata_is_omitted_case_insensitively
  run_test test_container_name_fallback
  run_test test_digest_update_kind_fallback
  run_test test_tag_dedupe_replaces_existing_image_line
  run_test test_invalid_digest_is_omitted
  run_test test_dedupe_replaces_existing_image_line
  run_test test_dedupe_replaces_existing_digest_pinned_line
  run_test test_existing_file_mode_and_owner_are_preserved
  run_test test_existing_broader_mode_is_preserved
  run_test test_new_file_defaults_to_group_writable_mode
  run_test test_owner_config_is_applied_to_rewritten_file
  run_test test_out_guid_alias_is_applied_to_rewritten_file
  run_test test_owner_config_requires_uid_and_group_before_replace
  run_test test_lock_removed_after_success
  run_test test_lock_timeout_leaves_file_unchanged
  run_test test_lock_retries_when_lock_released_during_status_check
  run_test test_lock_failure_when_dir_cannot_be_created
  run_test test_lock_failure_in_readonly_dir
  run_test test_sort_failure_leaves_file_unchanged
  run_test test_replace_failure_leaves_file_unchanged
}

trap teardown_case EXIT
main "$@"

#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SCRIPT="$REPO_ROOT/wud/append-updates.sh"
TEST_TMP=""
OUT_FILE=""

fail(){
  printf 'not ok - %s\n' "$*" >&2
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
  env WUD_OUT_FILE="$OUT_FILE" "$@" sh "$SCRIPT"
}

assert_file_equals(){
  local expected="$1" actual
  actual="$(cat "$OUT_FILE")"
  [[ "$actual" == "$expected" ]] || fail "expected [$expected], got [$actual]"
}

assert_file_missing(){
  [[ ! -e "$OUT_FILE" ]] || fail "expected $OUT_FILE to be absent"
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

test_image_tag_and_result_digest_are_written(){
  setup_case
  run_script update_available=true image_name=repo/app image_tag_value=1.2 result_digest="$(hex_digest)"
  assert_file_equals "repo/app:1.2 sha256=sha256:$(hex_digest)"
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
  assert_file_equals "repo/app:latest sha256=sha256:$(hex_digest)"
  teardown_case
}

test_invalid_digest_is_omitted(){
  setup_case
  run_script update_available=true image_name=repo/app image_tag_value=latest result_digest=not-a-digest
  assert_file_equals 'repo/app:latest'
  teardown_case
}

test_dedupe_replaces_existing_image_line(){
  setup_case
  mkdir -p "$(dirname "$OUT_FILE")"
  printf 'repo/other:latest\nrepo/app:latest sha256=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n' > "$OUT_FILE"
  run_script update_available=true image_name=repo/app image_tag_value=latest result_digest="$(hex_digest)"
  assert_file_equals "repo/app:latest sha256=sha256:$(hex_digest)
repo/other:latest"
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
  run_test test_image_tag_and_result_digest_are_written
  run_test test_container_name_fallback
  run_test test_digest_update_kind_fallback
  run_test test_invalid_digest_is_omitted
  run_test test_dedupe_replaces_existing_image_line
}

trap teardown_case EXIT
main "$@"

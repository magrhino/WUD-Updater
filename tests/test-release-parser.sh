#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=wud/release-parser.sh
source "$REPO_ROOT/wud/release-parser.sh"

fail(){
  printf 'not ok - %s\n' "$*" >&2
  exit 1
}

run_test(){
  local name="$1"
  printf 'running %s\n' "$name"
  "$name"
  printf 'ok - %s\n' "$name"
}

test_detect_breaking(){
  local res
  res="$(detect_breaking "This is a breaking change" "v1.0.0" "v2.0.0")"
  [[ "$res" == "yes" ]] || fail "detect_breaking did not detect keyword 'breaking'"

  res="$(detect_breaking "Minor updates" "v1.0.0" "v2.0.0")"
  [[ "$res" == "yes" ]] || fail "detect_breaking did not detect major version bump"

  res="$(detect_breaking "Minor updates" "v1.0.0" "v1.1.0")"
  [[ "$res" == "no" ]] || fail "detect_breaking incorrectly detected breaking on minor bump"

  res="$(detect_breaking "Manual step required before upgrade" "v1.0.0" "v1.1.0")"
  [[ "$res" == "yes" ]] || fail "detect_breaking did not detect 'manual step'"
}

test_semver_first(){
  local res
  res="$(printf 'v1.2.3-alpha' | semver_first)"
  [[ "$res" == "v1.2.3-alpha" ]] || fail "semver_first failed: got '$res'"

  res="$(printf '4.5.6.xyz' | semver_first)"
  [[ "$res" == "4.5.6.xyz" ]] || fail "semver_first failed on standard semver: got '$res'"
}

test_strip_md_headers(){
  local res
  res="$(printf '**Changes:**\nSome text' | strip_md_headers)"
  [[ "$res" == $'Changes:\nSome text' ]] || fail "strip_md_headers failed to strip **: got '$res'"
}

test_extract_block_header_ci(){
  local res
  local md=$'Some text\nLinuxServer Changes:\n- Rebase\n- Update\n\nOther changes:'
  res="$(printf '%s' "$md" | extract_block_header_ci "linuxserver changes:")"
  [[ "$res" == $'LinuxServer Changes:\n- Rebase\n- Update' ]] || fail "extract_block_header_ci failed: got '$res'"
}

test_extract_md_h2_section_ci(){
  local res
  local md=$'# Title\n## Changes\n- One\n- Two\n## Authors\n- Bob'
  res="$(printf '%s' "$md" | extract_md_h2_section_ci "changes")"
  [[ "$res" == $'## Changes\n- One\n- Two' ]] || fail "extract_md_h2_section_ci failed: got '$res'"
}

test_extract_upstream_version(){
  local res
  res="$(printf 'Updating to v2.5.0' | extract_upstream_version)"
  [[ "$res" == "v2.5.0" ]] || fail "extract_upstream_version failed: got '$res'"

  res="$(printf 'Bump to 3.0.0-rc1' | extract_upstream_version)"
  [[ "$res" == "3.0.0-rc1" ]] || fail "extract_upstream_version bump failed: got '$res'"
}

test_extract_alpine_base(){
  local res
  res="$(printf '%s' '- Rebase to Alpine 3.20' | extract_alpine_base)"
  [[ "$res" == "3.20" ]] || fail "extract_alpine_base failed: got '$res'"
}

test_extract_ci_link(){
  local res
  res="$(printf 'Check out https://github.com/ci-tests/123' | extract_ci_link)"
  [[ "$res" == "https://github.com/ci-tests/123" ]] || fail "extract_ci_link failed: got '$res'"
}

test_select_key_change_bullets(){
  local res
  local md=$'## Key changes\n* one\n* two\n## Other'
  res="$(printf '%s' "$md" | select_key_change_bullets)"
  [[ "$res" == $'- one\n- two' ]] || fail "select_key_change_bullets explicit section failed: got '$res'"

  local md_with_preamble=$'## Changes\n- fallback one\n- fallback two\n\n## Key changes\n- real one\n- real two\n\n## Other\n- ignored'
  res="$(printf '%s' "$md_with_preamble" | select_key_change_bullets)"
  [[ "$res" == $'- real one\n- real two' ]] || fail "select_key_change_bullets emitted fallback before explicit section: got '$res'"

  local md2=$'Introduction text.\n* first\n* second\n* third'
  res="$(printf '%s' "$md2" | select_key_change_bullets 2)"
  [[ "$res" == $'- first\n- second' ]] || fail "select_key_change_bullets max 2 failed: got '$res'"
}

test_select_representative_changes(){
  local res
  local md=$'## Changes\n- Fixed bug (#123)\n- Other fix #456\n- Minor abcdef123456789'
  res="$(printf '%s' "$md" | select_representative_changes "owner" "repo" 2)"
  [[ "$res" == $'- [#123](https://github.com/owner/repo/pull/123)\n- [#456](https://github.com/owner/repo/pull/456)' ]] || fail "select_representative_changes failed: got '$res'"
}

test_extract_intro_until_h3(){
  local res
  local md=$'Intro text\nMore intro\n### Subheader\nIgnored'
  res="$(printf '%s' "$md" | extract_intro_until_h3)"
  [[ "$res" == $'Intro text\nMore intro' ]] || fail "extract_intro_until_h3 failed: got '$res'"
}

test_extract_lsio_non_rebase_changes(){
  local res
  local txt=$'- rebase to alpine 3.20\n- Add new package\n- Rebase alpine 3.19'
  res="$(extract_lsio_non_rebase_changes "$txt")"
  [[ "$res" == "- Add new package" ]] || fail "extract_lsio_non_rebase_changes failed: got '$res'"
}

main(){
  run_test test_detect_breaking
  run_test test_semver_first
  run_test test_strip_md_headers
  run_test test_extract_block_header_ci
  run_test test_extract_md_h2_section_ci
  run_test test_extract_upstream_version
  run_test test_extract_alpine_base
  run_test test_extract_ci_link
  run_test test_select_key_change_bullets
  run_test test_select_representative_changes
  run_test test_extract_intro_until_h3
  run_test test_extract_lsio_non_rebase_changes
}

main "$@"

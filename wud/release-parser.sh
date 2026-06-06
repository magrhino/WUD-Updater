#!/usr/bin/env bash
# Helpers for parsing markdown, versions, and release notes
# Extracted to isolate brittle awk/sed/grep commands from main dispatch logic.

detect_breaking() {
  local body="$1" current="$2" new="$3" current_major new_major breaking="no"
  if grep -Eiq '(breaking|migration|incompatible|manual step|major change|requires [^ ]+ [0-9]|deprecated[^.]*remov|remove[ds] feature)' <<<"$body"; then
    breaking="yes"
  fi
  if [[ -n "$current" && "$current" =~ ^v?([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
    current_major="${BASH_REMATCH[1]}"
    if [[ "$new" =~ ^v?([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
      new_major="${BASH_REMATCH[1]}"
      if (( new_major > current_major )); then
        breaking="yes"
      fi
    fi
  fi
  printf '%s' "$breaking"
}

semver_first() {
  tr -d '\r' \
    | tr -cs '0-9A-Za-z._ -' '\n' \
    | grep -m1 -E '^[vV]?[0-9]+(\.[0-9]+){1,3}([._-][0-9A-Za-z]+)?$' \
    || true
}

strip_md_headers() {
  sed -E 's/\r//g; s/^\*\*([A-Za-z0-9 _-]+):\*\*/\1:/; s/[[:space:]]+$//'
}

extract_block_header_ci() {
  local header="$1"
  awk -v target="$(printf '%s' "$header" | tr '[:upper:]' '[:lower:]')" '
    function lower(s) { return tolower(s) }
    {
      line = $0
      low = lower(line)
      is_hdr = match(line, /^[[:space:]]*[A-Za-z0-9 _-]+:[[:space:]]*$/)
      if (low == target) { print line; show = 1; next }
      if (show && is_hdr) exit
      if (show) print line
    }'
}

extract_md_h2_section_ci() {
  local h2="$1"
  awk -v key="$(printf '%s' "$h2" | tr '[:upper:]' '[:lower:]')" '
    function lower(s) { return tolower(s) }
    /^##[[:space:]]+/ {
      header = lower($0)
      sub(/^##[[:space:]]*/, "", header)
      sub(/[[:space:]:]*$/, "", header)
      if (header == key) { print $0; show = 1; next }
      if (show) exit
    }
    { if (show) print $0 }
  '
}

extract_upstream_version() {
  local text version=""

  text="$(cat)"
  version="$(printf '%s\n' "$text" \
    | grep -Eoim1 'updat(ing|e)[[:space:]]+to[[:space:]]+[vV]?[0-9]+(\.[0-9]+){1,}([[:alnum:]._-])*' \
    | sed -E 's/.*to[[:space:]]+//' || true)"
  [[ -z "$version" ]] && version="$(printf '%s\n' "$text" \
    | grep -Eoim1 'bump[[:space:]]+to[[:space:]]+[vV]?[0-9]+(\.[0-9]+){1,}([[:alnum:]._-])*' \
    | sed -E 's/.*to[[:space:]]+//' || true)"
  [[ -z "$version" ]] && version="$(printf '%s\n' "$text" \
    | grep -Eoim1 '[vV]?[0-9]+(\.[0-9]+){1,}([[:alnum:]._-])*' || true)"
  printf '%s' "$version"
}

extract_alpine_base() {
  grep -Eoi -m1 'alpine[[:space:]]+[0-9]+\.[0-9]+' | awk '{print $2}'
}

extract_ci_link() {
  grep -Eom1 'https?://[^ ]+ci-tests[^ ]+' || true
}

select_key_change_bullets() {
  local max="${1:-7}"

  awk -v max="$max" '
    function lower(s) { return tolower(s) }
    function is_bullet(s) { return (s ~ /^[[:space:]]*([*+-]|•)[[:space:]]/) }
    {
      lines++
      line = $0
      low = lower(line)
      if (low ~ /^##[[:space:]]*key[[:space:]]*changes[[:space:]]*$/) { in_key = 1; next }
      if (in_key && line ~ /^##[[:space:]]/) in_key = 0
      if (in_key && is_bullet(line)) {
        sub(/^[[:space:]]*([*+-]|•)[[:space:]]*/, "- ", line)
        print line
        out++
        if (out >= max) exit
      } else if (!in_key && lines <= 200 && is_bullet(line) && seen < max) {
        sub(/^[[:space:]]*([*+-]|•)[[:space:]]*/, "- ", line)
        print line
        seen++
        if (seen >= max) exit
      }
    }
  '
}

select_representative_changes() {
  local owner="$1" repo="$2" max="${3:-3}" section line count=0

  section="$(cat | extract_md_h2_section_ci "changes")"
  [[ -n "$section" ]] || return 0
  while IFS= read -r line; do
    if [[ "$line" =~ \(#([0-9]+)\) ]]; then
      printf -- '- [#%s](https://github.com/%s/%s/pull/%s)\n' "${BASH_REMATCH[1]}" "$owner" "$repo" "${BASH_REMATCH[1]}"
      count=$((count + 1))
    elif [[ "$line" =~ (^|[^A-Za-z0-9_])#([0-9]+) ]]; then
      printf -- '- [#%s](https://github.com/%s/%s/pull/%s)\n' "${BASH_REMATCH[2]}" "$owner" "$repo" "${BASH_REMATCH[2]}"
      count=$((count + 1))
    elif [[ "$line" =~ ([0-9a-f]{7,40}) ]]; then
      printf -- '- [%s](https://github.com/%s/%s/commit/%s)\n' "${BASH_REMATCH[1]:0:7}" "$owner" "$repo" "${BASH_REMATCH[1]}"
      count=$((count + 1))
    fi
    if (( count >= max )); then
      break
    fi
  done < <(printf '%s\n' "$section" | sed -n '/^##/,$p' | sed '1d')
}

extract_intro_until_h3() {
  awk '{ if ($0 ~ /^###[[:space:]]/) exit; print }'
}

extract_lsio_non_rebase_changes() {
  local lsio_changes_text="$1"
  grep -viE '^[[:space:]]*[-*•]?[[:space:]]*rebase( to)? alpine[[:space:]]+[0-9]+\.[0-9]+' <<<"$lsio_changes_text" 2>/dev/null || true
}

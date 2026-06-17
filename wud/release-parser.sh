#!/usr/bin/env bash
# Helpers for parsing markdown, versions, and release notes
# Extracted to isolate brittle awk/sed/grep commands from main dispatch logic.

detect_breaking() {
  local body="$1" current="$2" new="$3" current_major new_major breaking="no"
  if grep -Eiq '(breaking|migration|incompatible|manual step|major change|requires [^ ]+ [0-9]|deprecated[^.]*remov|remove[ds] feature)' <<<"$body"; then
    breaking="yes"
  fi
  current="$(printf '%s' "$current" | semver_first)"
  new="$(printf '%s' "$new" | semver_first)"
  if [[ -n "$current" && "$current" =~ ^[vV]?([0-9]+)\. ]]; then
    current_major="${BASH_REMATCH[1]}"
    if [[ "$new" =~ ^[vV]?([0-9]+)\. ]]; then
      new_major="${BASH_REMATCH[1]}"
      if (( new_major > current_major )); then
        breaking="yes"
      fi
    fi
  fi
  printf '%s' "$breaking"
  return $?
}

semver_first() {
  grep -Eoim1 '(^|[^0-9A-Za-z])[vV]?[0-9]+(\.[0-9]+){1,3}([._-][0-9A-Za-z]+)*([^0-9A-Za-z]|$)' \
    | sed -E 's/^[^0-9A-Za-z]*//; s/[^0-9A-Za-z]$//' \
    | awk 'NF { print; exit }' \
    || true
  return $?
}

strip_lsio_suffix() {
  sed -E 's/[._-]ls[0-9]+([._-][0-9A-Za-z]+)*$//I'
  return $?
}

strip_md_headers() {
  sed -E 's/\r//g; s/^[[:space:]]*#+[[:space:]]*//; s/^\*\*([A-Za-z0-9 _-]+):\*\*/\1:/; s/[[:space:]]+$//'
  return $?
}

extract_block_header_ci() {
  local header="$1"
  awk -v target="$(printf '%s' "$header" | tr '[:upper:]' '[:lower:]')" '
    function lower(s) { return tolower(s) }
    function trim(s) { gsub(/^[[:space:]]+|[[:space:]]+$/, "", s); return s }
    function header_text(s) {
      s = trim(s)
      sub(/^#+[[:space:]]*/, "", s)
      sub(/^\*\*/, "", s)
      sub(/\*\*$/, "", s)
      return trim(s)
    }
    {
      line = $0
      header = header_text(line)
      low = lower(header)
      is_bullet = match(line, /^[[:space:]]*([*+-]|•)[[:space:]]/)
      is_hdr = !is_bullet && match(header, /^[A-Za-z0-9 _-]+:[[:space:]]*$/)
      if (low == target) { print line; show = 1; next }
      if (show && is_hdr) exit
      if (show) print line
    }'
  return $?
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
  return $?
}

extract_upstream_version() {
  local text version=""

  text="$(cat)"
  version="$(printf '%s\n' "$text" \
    | grep -Eim1 'updat(ing|e)[[:space:]]+to[[:space:]]+[vV]?[0-9]+(\.[0-9]+){1,}' \
    | semver_first || true)"
  [[ -z "$version" ]] && version="$(printf '%s\n' "$text" \
    | grep -Eim1 'bump[[:space:]]+to[[:space:]]+[vV]?[0-9]+(\.[0-9]+){1,}' \
    | semver_first || true)"
  [[ -z "$version" ]] && version="$(printf '%s\n' "$text" \
    | semver_first || true)"
  printf '%s' "$version"
  return $?
}

extract_alpine_base() {
  grep -Eoi -m1 'alpine[[:space:]]+[0-9]+\.[0-9]+' | awk '{print $2}'
  return $?
}

extract_ci_link() {
  grep -Eom1 'https?://[^ ]+ci-tests[^ ]+' || true
  return $?
}

select_key_change_bullets() {
  local max="${1:-7}"

  awk -v max="$max" '
    function lower(s) { return tolower(s) }
    function is_bullet(s) { return (s ~ /^[[:space:]]*([*+-]|•)[[:space:]]/) }
    function is_h2(s) { return (s ~ /^##[[:space:]]/) }
    function is_continuation(s) {
      return (s !~ /^[[:space:]]*$/ && !is_bullet(s) && !is_h2(s))
    }
    function print_bullet(line) {
      sub(/^[[:space:]]*([*+-]|•)[[:space:]]*/, "- ", line)
      print line
      keep = 1
    }
    function emit(line,    low) {
      low = lower(line)
      if (low ~ /^##[[:space:]]*key[[:space:]]*changes/) { in_key = 1; return }
      if (in_key && is_h2(line)) { in_key = 0; keep = 0 }
      if (has_key) {
        if (in_key && is_bullet(line)) {
          if (out >= max) exit
          print_bullet(line)
          out++
        } else if (in_key && keep && is_continuation(line)) {
          print line
        } else if (in_key) {
          keep = 0
        }
      } else if (lines <= 200 && is_bullet(line) && seen < max) {
        print_bullet(line)
        seen++
      } else if (!has_key && lines <= 200 && keep && is_continuation(line)) {
        print line
      } else if (!has_key) {
        keep = 0
      }
    }
    function finish_scan(    i, scan_lines) {
      scanned = 1
      scan_lines = lines
      lines = 0
      for (i = 1; i <= scan_lines; i++) {
        lines++
        emit(buffer[i])
      }
    }
    !scanned {
      lines++
      buffer[lines] = $0
      if (lines <= 200 && lower($0) ~ /^##[[:space:]]*key[[:space:]]*changes/) has_key = 1
      if (lines >= 200) {
        finish_scan()
        if (!has_key) exit
      }
      next
    }
    {
      lines++
      emit($0)
    }
    END {
      if (!scanned) finish_scan()
    }
  '
  return $?
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
    elif [[ "$line" =~ (^|[^A-Za-z0-9])([0-9a-f]{7,40})([^A-Za-z0-9]|$) ]]; then
      local commit="${BASH_REMATCH[2]:-}"
      if [[ "$commit" =~ [0-9] ]]; then
        printf -- '- [%s](https://github.com/%s/%s/commit/%s)\n' "${commit:0:7}" "$owner" "$repo" "$commit"
        count=$((count + 1))
      fi
    fi
    if (( count >= max )); then
      break
    fi
  done < <(printf '%s\n' "$section" | sed -n '/^##/,$p' | sed '1d')
  return $?
}

extract_intro_until_h3() {
  awk '{ if ($0 ~ /^###[[:space:]]/) exit; print }'
  return $?
}

extract_lsio_non_rebase_changes() {
  local lsio_changes_text="$1"
  grep -viE '^[[:space:]]*[-*•]?[[:space:]]*rebase( to)? alpine[[:space:]]+[0-9]+\.[0-9]+' <<<"$lsio_changes_text" 2>/dev/null || true
  return $?
}

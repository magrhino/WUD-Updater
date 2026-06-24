#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
MAP_FILE="${1:-$REPO_ROOT/wud/upstreams.txt}"

fail() {
  printf 'not ok - %s\n' "$*" >&2
  exit 1
}

[[ -f "$MAP_FILE" ]] || fail "upstream map not found: $MAP_FILE"

export LC_ALL=C

previous_key=""
line_no=0
entry_count=0

while IFS= read -r line || [[ -n "$line" ]]; do
  line_no=$((line_no + 1))
  [[ -z "$line" || "$line" == \#* ]] && continue

  if [[ ! "$line" =~ ^(linuxserver/docker-[A-Za-z0-9._-]+):[[:space:]]([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$ ]]; then
    fail "$MAP_FILE:$line_no must match 'linuxserver/docker-<image>: Owner/Repo'"
  fi

  key="${BASH_REMATCH[1]}"
  value="${BASH_REMATCH[2]}"
  if [[ "$line" != "$key: $value" ]]; then
    fail "$MAP_FILE:$line_no must use exactly one space after ':'"
  fi

  if [[ -n "$previous_key" ]]; then
    [[ "$key" != "$previous_key" ]] || fail "$MAP_FILE:$line_no duplicates $key"
    [[ "$key" > "$previous_key" ]] || fail "$MAP_FILE:$line_no sorts before $previous_key"
  fi

  previous_key="$key"
  entry_count=$((entry_count + 1))
done < "$MAP_FILE"

(( entry_count > 0 )) || fail "$MAP_FILE has no upstream mappings"

printf 'ok - validated %s upstream mappings\n' "$entry_count"

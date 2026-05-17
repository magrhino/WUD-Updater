#!/usr/bin/env bash
set -euo pipefail
trap '' PIPE   # ignore SIGPIPE so writers don’t kill the script

# =========================================
# Config / Defaults
# =========================================
PROVIDER="${PROVIDER:-lsio}"              # lsio | generic (default: lsio)
LSIO_OWNER="${LSIO_OWNER:-linuxserver}"
LSIO_REPO="${LSIO_REPO:-}"
UPSTREAM_OWNER="${UPSTREAM_OWNER:-Radarr}"
UPSTREAM_REPO="${UPSTREAM_REPO:-Radarr}"
UPSTREAM_TAG_OVERRIDE="${UPSTREAM_TAG_OVERRIDE:-}"   # for --tag with provider=generic (or lsio if desired)
WEBHOOK=""
MAX_COMMITS="${MAX_COMMITS:-3}"
COLOR_HEX="${COLOR_HEX:-0x57F287}"   # Discord green
DEBUG=0

# =========================================
# Logging (pipe-safe)
# =========================================
ts() { date +"%Y-%m-%d %H:%M:%S"; }
dbg(){ [[ $DEBUG -eq 1 ]] && { >&2 printf "[%s] [DEBUG] %s\n" "$(ts)" "$*" || true; }; }
err(){ >&2 printf "[%s] [ERROR] %s\n" "$(ts)" "$*" || true; }
inf(){ >&2 printf "[%s] [INFO ] %s\n" "$(ts)" "$*" || true; }

# =========================================
# Args
# =========================================
while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider) PROVIDER="$2"; shift 2 ;;
    --lsio) IFS=/ read -r LSIO_OWNER LSIO_REPO <<<"$2"; shift 2 ;;
    --upstream) IFS=/ read -r UPSTREAM_OWNER UPSTREAM_REPO <<<"$2"; shift 2 ;;
    --tag) UPSTREAM_TAG_OVERRIDE="$2"; shift 2 ;;
    --webhook) WEBHOOK="$2"; shift 2 ;;
    --max-commits) MAX_COMMITS="$2"; shift 2 ;;
    --color) COLOR_HEX="$2"; shift 2 ;;    # e.g. 0x57F287 or 5814783
    --debug) DEBUG=1; shift ;;
    *) err "Unknown arg: $1"; exit 2 ;;
  esac
done

# =========================================
# Preflight
# =========================================
command -v curl >/dev/null 2>&1 || { err "curl not found"; exit 1; }
command -v jq   >/dev/null 2>&1 || { err "jq not found"; exit 1; }

# Normalize color to integer (Discord expects decimal)
norm_color() {
  local c="$1"
  if [[ "$c" =~ ^0x[0-9A-Fa-f]+$ ]]; then
    printf "%d" "$((c))"
  else
    printf "%d" "$c" 2>/dev/null || printf "%d" 5814783
  fi
}
DISCORD_COLOR="$(norm_color "$COLOR_HEX")"

# =========================================
# GitHub API helper
# =========================================
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
CURL_HEADERS=(-fsSL -H "Accept: application/vnd.github+json" -H "User-Agent: lsio-release-embed/1.4")
[[ -n "$GITHUB_TOKEN" ]] && CURL_HEADERS+=(-H "Authorization: Bearer ${GITHUB_TOKEN}")

api_get() {
  local url="$1"
  dbg "GET $url"
  local tmp; tmp="$(mktemp)"
  if ! curl "${CURL_HEADERS[@]}" -sSf --retry 3 --retry-delay 1 --max-time 20 -o "$tmp" "$url"; then
    if [[ -s "$tmp" ]]; then
      # print a short error body snippet but never crash on write errors
      { >&2 printf "[%s] [ERROR] curl body (first 200 bytes): %s\n" "$(ts)" "$(head -c 200 "$tmp" | tr '\n' ' ')" || true; }
    fi
    rm -f "$tmp"
    return 1
  fi
  cat "$tmp" || true
  rm -f "$tmp"
}

# =========================================
# Markdown helpers (pipe-safe; no early head)
# =========================================
strip_md_headers() {
  sed -E 's/\r//g; s/^\*\*([A-Za-z0-9 _-]+):\*\*/\1:/; s/[[:space:]]+$//'
}

extract_block_header_ci() {
  # stdin: text; $1: header exact text (case-insensitive), e.g., "remote changes:"
  local header="$1"
  awk -v target="$(printf "%s" "$header" | tr '[:upper:]' '[:lower:]')" '
    function lower(s,  i,c,o){o="";for(i=1;i<=length(s);i++){c=substr(s,i,1);if(c>="A"&&c<="Z"){c=tolower(c)};o=o c}return o}
    {
      line=$0; low=lower(line)
      is_hdr=match(line, /^[[:space:]]*[A-Za-z0-9 _-]+:[[:space:]]*$/)
      if (low==target) { print line; show=1; next }
      if (show==1 && is_hdr) { exit }
      if (show==1) print line
    }
  '
}

extract_md_h2_section_ci() {
  # stdin: text; $1: H2 name (case-insensitive), e.g. "changes"
  local h2="$1"
  awk -v key="$(printf "%s" "$h2" | tr '[:upper:]' '[:lower:]')" '
    function lower(s,  i,c,o){o="";for(i=1;i<=length(s);i++){c=substr(s,i,1);if(c>="A"&&c<="Z"){c=tolower(c)};o=o c}return o}
    BEGIN{show=0}
    { L=lower($0) }
    L ~ /^##[[:space:]]*[a-z0-9 ._-]+[:[:space:]]*$/ {
      name=$0; N=lower(name)
      if (N ~ "^##[[:space:]]*" key "[:[:space:]]*$") { print $0; show=1; next }
      if (show==1) { exit }
    }
    { if (show==1) print $0 }
  '
}

extract_upstream_version() {
  local text; text="$(cat)"
  local v=""
  v="$(printf "%s\n" "$text" \
      | grep -Eoim1 'updat(ing|e)[[:space:]]+to[[:space:]]+[0-9]+(\.[0-9]+){1,}([[:alnum:]._-])*' \
      | sed -E 's/.*to[[:space:]]+//')"
  [[ -z "$v" ]] && v="$(printf "%s\n" "$text" \
      | grep -Eoim1 'bump[[:space:]]+to[[:space:]]+[0-9]+(\.[0-9]+){1,}([[:alnum:]._-])*' \
      | sed -E 's/.*to[[:space:]]+//')"
  [[ -z "$v" ]] && v="$(printf "%s\n" "$text" \
      | grep -Eoim1 '[0-9]+(\.[0-9]+){1,}([[:alnum:]._-])*')"
  printf "%s" "$v"
}

extract_alpine_base() {
  # was: ... | head -n1 | awk ...
  grep -Eoi -m1 'alpine[[:space:]]+[0-9]+\.[0-9]+' | awk '{print $2}'
}

extract_ci_link() {
  # was: ... | head -n1
  grep -Eom1 'https?://[^ ]+ci-tests[^ ]+' || true
}

select_key_change_bullets() {
  # Read from stdin. Prefer the "## Key changes" section; else scan first 200 lines.
  # Print up to $max bullet lines (•/-/*)
  local max="${1:-7}"
  awk -v max="$max" '
    function ltrim(s){ sub(/^[[:space:]]+/, "", s); return s }
    function is_bullet(s){ return (s ~ /^[[:space:]]*([*+-]|•)[[:space:]]/) }
    BEGIN{in_key=0; out=0; seen=0; lines=0}
    {
      lines++
      line=$0
      low=line; for(i=1;i<=length(low);i++) { c=substr(low,i,1); if (c>="A"&&c<="Z") c=tolower(c); s=s c } low=s; s=""
      if (low ~ /^##[[:space:]]*key[[:space:]]*changes[:[:space:]]*$/) { in_key=1; next }
      if (in_key && line ~ /^##[[:space:]]/) { in_key=0 }  # next H2 ends section
      if (in_key && is_bullet(line)) {
        sub(/^[[:space:]]*([*+-]|•)[[:space:]]*/, "• ", line)
        print line
        out++; if (out>=max) exit
      } else if (!in_key && lines<=200 && is_bullet(line) && seen<max) {
        sub(/^[[:space:]]*([*+-]|•)[[:space:]]*/, "• ", line)
        print line
        seen++; if (seen>=max) exit
      }
    }
  '
}


select_representative_changes() {
  local owner="$1" repo="$2" max="${3:-3}"
  local sec; sec="$(cat | extract_md_h2_section_ci "changes")"
  [[ -z "$sec" ]] && return 0
  echo "$sec" \
    | sed -n '/^##/,$p' | sed '1d' \
    | awk -v o="$owner" -v r="$repo" -v max="$max" '
        function out_hash(h) { short=substr(h,1,7); print "• [" short "](https://github.com/" o "/" r "/commit/" h ")" }
        function out_pr(n)  { print "• [#" n "](https://github.com/" o "/" r "/pull/" n ")" }
        BEGIN{count=0}
        {
          line=$0
          if (match(line, /\(#([0-9]+)\)/, m)) { out_pr(m[1]); count++ }
          else if (match(line, /(^|[^A-Za-z0-9_])#([0-9]+)/, m)) { out_pr(m[2]); count++ }
          else if (match(line, /[0-9a-f]{7,40}/, m)) { out_hash(m[0]); count++ }
          if (count>=max) { exit }
        }
      '
}

extract_intro_until_h3() {
  # Print everything until first H3 (###)
  awk 'BEGIN{done=0} { if ($0 ~ /^###[[:space:]]/) { done=1; exit } if (!done) print }'
}


build_context_line_lsio() {
  local image="$1" lsio_tag="$2" alpine="$3"
  local tag_suffix
  tag_suffix="$(printf "%s" "$lsio_tag" | awk -F- '{print $NF}')"
  if [[ -n "${alpine:-}" ]]; then
    printf "\`%s\` • %s • Alpine %s" "$image" "$tag_suffix" "$alpine"
  else
    printf "\`%s\` • %s" "$image" "$tag_suffix"
  fi
}

build_context_line_generic() {
  local image="$1" upstream_repo_full="$2" shown_tag="$3"
  local left="\`$upstream_repo_full\`"
  [[ -n "${image:-}" ]] && left="\`$image\`"
  if [[ -n "${shown_tag:-}" ]]; then
    printf "%s • %s" "$left" "$shown_tag"
  else
    printf "%s" "$left"
  fi
}

# =========================================
# HTML redirect resolver for /releases/latest
# =========================================
resolve_latest_redirect() {
  local o="$1" r="$2"
  local url="https://github.com/${o}/${r}/releases/latest"
  dbg "HEAD/GET (follow) $url"
  local effective
  effective="$(curl -fsSL -o /dev/null -w '%{url_effective}' -H "User-Agent: lsio-release-embed/1.4" "$url" || true)"
  if [[ -z "$effective" ]]; then
    echo ""
    return 0
  fi
  local tag
  tag="$(printf "%s" "$effective" | sed -nE 's#.*/releases/tag/([^/?#]+).*#\1#p')"
  printf "%s" "$tag"
}

# =========================================
# Fetch upstream release by version or latest; fallback to homepage
# =========================================
fetch_upstream_release() {
  local o="$1" r="$2" v="${3:-}"
  local rel=""

  if [[ -n "$v" ]]; then
    case "${v,,}" in
      latest|current)
        local real
        real="$(resolve_latest_redirect "$o" "$r")"
        if [[ -n "$real" ]]; then
          dbg "Resolved latest -> tag '$real' via redirect"
          v="$real"
        else
          dbg "Could not resolve latest via redirect; will use API latest endpoint"
          v=""
        fi
      ;;
    esac
  fi

  if [[ -n "$v" ]]; then
    rel="$(api_get "https://api.github.com/repos/${o}/${r}/releases/tags/v${v}" || true)"
    if [[ -z "$rel" || "$(jq -r '.message // empty' <<<"$rel")" == "Not Found" ]]; then
      rel="$(api_get "https://api.github.com/repos/${o}/${r}/releases/tags/${v}" || true)"
    fi
  else
    rel="$(api_get "https://api.github.com/repos/${o}/${r}/releases/latest" || true)"
  fi

  if [[ -z "$rel" || "$(jq -r '.message // empty' <<<"$rel")" == "Not Found" || "$rel" == "null" ]]; then
    if [[ -n "$v" ]]; then
      local list
      list="$(api_get "https://api.github.com/repos/${o}/${r}/releases?per_page=100" || true)"
      if [[ -n "$list" && "$(jq -r 'type' <<<"$list" 2>/dev/null)" == "array" ]]; then
        rel="$(jq --arg v "$v" -c '
          .[] | select(
            (.tag_name == ("v"+$v)) or
            (.tag_name == $v) or
            ((.name // "") | test($v))
          ) | .' <<<"$list" | head -n1 || true)"
        [[ -n "$rel" && "${rel:0:1}" != "{" ]] && rel="$(echo "$rel" | jq -r '.')"
      fi
    fi
  fi

  if [[ -z "$rel" || "$rel" == "null" || "$(jq -r '.message // empty' <<<"$rel")" == "Not Found" ]]; then
    if [[ -z "$v" || "${v,,}" == "latest" || "${v,,}" == "current" ]]; then
      local via
      via="$(resolve_latest_redirect "$o" "$r")"
      if [[ -n "$via" ]]; then
        dbg "Final fallback: resolved latest -> tag '$via' via redirect"
        rel="$(api_get "https://api.github.com/repos/${o}/${r}/releases/tags/${via}" || true)"
        if [[ -z "$rel" || "$(jq -r '.message // empty' <<<"$rel")" == "Not Found" ]]; then
          rel="$(api_get "https://api.github.com/repos/${o}/${r}/releases/tags/v${via}" || true)"
        fi
      fi
    fi
  fi

  if [[ -z "$rel" || "$rel" == "null" || "$(jq -r '.message // empty' <<<"$rel")" == "Not Found" ]]; then
    local repo_json
    repo_json="$(api_get "https://api.github.com/repos/${o}/${r}")"
    echo "FALLBACK"
    echo "$repo_json"
  else
    echo "RELEASE"
    echo "$rel"
  fi
}

# =========================================
# PROVIDER=lsio (default)
# =========================================
# helper used inline: keep only first semver-like token (e.g. 4.4.3, v4.4.3, 1.2.3-rc1)
_semver_first() {
  # read stdin, strip CRs, split on nonprintables, pick first token that looks like a version
  tr -d '\r' \
  | tr -cs '0-9A-Za-z._- ' '\n' \
  | grep -m1 -E '^[vV]?[0-9]+(\.[0-9]+){1,3}([._-][0-9A-Za-z]+)?$' \
  || true
}

# force to a single line (drop everything after the first newline)
_oneline() { sed -n '1{s/\r//;p}'; }

run_lsio() {
  local lsio_json lsio_tag lsio_body lsio_html
  lsio_json="$(api_get "https://api.github.com/repos/${LSIO_OWNER}/${LSIO_REPO}/releases/latest")"
  [[ -z "$lsio_json" || "$(jq -r '.message // empty' <<<"$lsio_json")" == "Not Found" ]] && { err "LSIO latest not found"; exit 1; }

  lsio_tag="$(jq -r '.tag_name' <<<"$lsio_json")"
  lsio_body="$(jq -r '.body // ""' <<<"$lsio_json")"
  lsio_html="$(jq -r '.html_url' <<<"$lsio_json")"
  [[ -z "$lsio_body" ]] && lsio_body=""

  # ---- parse LSIO body blocks (silence helper stderr) ----
  local norm_lsio_body linux_block remote_block
  norm_lsio_body="$(strip_md_headers <<<"$lsio_body" 2>/dev/null)"
  linux_block="$(extract_block_header_ci "linuxserver changes:" <<<"$norm_lsio_body" 2>/dev/null)"
  remote_block="$(extract_block_header_ci "remote changes:"   <<<"$norm_lsio_body" 2>/dev/null)"

  # ---- extract upstream version, but keep only first valid token ----
  local upstream_version_raw upstream_version alpine_base ci_url
  upstream_version_raw="$(extract_upstream_version <<<"$remote_block" 2>/dev/null || true)"
  upstream_version="$(printf "%s" "$upstream_version_raw" | _semver_first)"
  [[ -z "$upstream_version" ]] && upstream_version="$(printf "%s" "$lsio_tag" | _semver_first)"

  alpine_base="$(extract_alpine_base <<<"$linux_block" 2>/dev/null || true)"
  ci_url="$(extract_ci_link <<<"$lsio_body" 2>/dev/null || true)"

  # Detect LSIO non-rebase lines
  local lsio_changes_text lsio_non_rebase
  lsio_changes_text="$(sed '1d' <<<"$linux_block" | sed '/^[[:space:]]*$/d')"
  lsio_non_rebase="$(grep -viE '^[[:space:]]*rebase( to)? alpine[[:space:]]+[0-9]+\.[0-9]+' <<<"$lsio_changes_text" 2>/dev/null || true)"

  dbg "LSIO tag: $lsio_tag"
  dbg "Remote version: ${upstream_version:-<none>}"
  dbg "Alpine base: ${alpine_base:-<none>}"
  dbg "CI link: ${ci_url:-<none>}"

  # ---- fetch upstream; if version missing/invalid, try "latest" redirect path ----
  local relkind up_json
  { read -r relkind; up_json="$(cat)"; } < <(fetch_upstream_release "$UPSTREAM_OWNER" "$UPSTREAM_REPO" "${upstream_version:-}")
  if [[ "$relkind" == "FALLBACK" && -z "${upstream_version:-}" ]]; then
    { read -r relkind; up_json="$(cat)"; } < <(fetch_upstream_release "$UPSTREAM_OWNER" "$UPSTREAM_REPO" "latest")
  fi

  local up_name up_tag up_html up_body up_date upstream_exists=0
  if [[ "$relkind" == "RELEASE" ]]; then
    upstream_exists=1
    up_name="$(jq -r '.name // .tag_name // ""' <<<"$up_json" | _oneline)"
    up_tag="$(jq -r '.tag_name // ""' <<<"$up_json"            | _oneline)"
    up_html="$(jq -r '.html_url // ""' <<<"$up_json"           | _oneline)"
    up_body="$(jq -r '.body // ""' <<<"$up_json" | tr -d '\r')"
    up_date="$(jq -r '.published_at // .created_at // ""' <<<"$up_json" | cut -dT -f1)"
  else
    inf "Upstream release not found for version ${upstream_version:-?}; falling back to project homepage"
    up_name="$(printf "%s" "${upstream_version:-}" | _oneline)"
    up_tag="N/A"
    up_html="$(jq -r '.html_url // ""' <<<"$up_json" | _oneline)"
    up_body=""
    up_date=""
  fi

  dbg "Upstream name: ${up_name} / ${up_tag}"
  dbg "Upstream date: ${up_date}"

  local context_line
  context_line="$(build_context_line_lsio "${LSIO_OWNER}/${LSIO_REPO}" "$lsio_tag" "${alpine_base:-}")"

  # Prefer Key Changes bullets; else intro paragraphs before first H3
  local key_bullets rep_changes intro_text
  key_bullets="$(select_key_change_bullets 7 <<<"$up_body" 2>/dev/null || true)"
  if [[ -z "$key_bullets" && -n "$up_body" ]]; then
    intro_text="$(extract_intro_until_h3 <<<"$up_body" 2>/dev/null | sed '/^[[:space:]]*$/,$d' || true)"
  fi
  rep_changes="$(select_representative_changes "$UPSTREAM_OWNER" "$UPSTREAM_REPO" "$MAX_COMMITS" <<<"$up_body" 2>/dev/null || true)"

  # Links field
  local links_value
  if [[ $upstream_exists -eq 1 ]]; then
    links_value="[LSIO release](${lsio_html}) • [Upstream release](${up_html}) • [Full changelog](${up_html}#user-content-changes)"
  else
    links_value="[LSIO release](${lsio_html}) • [Upstream project](https://github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO})"
  fi
  [[ -n "${ci_url:-}" ]] && links_value="${links_value} • [CI](${ci_url})"

  # Build description (strip control chars; cap size)
  local desc_lines=()
  desc_lines+=("$context_line")

  if [[ -n "$key_bullets" ]]; then
    desc_lines+=("")
    desc_lines+=("**Key changes**")
    while IFS= read -r L; do desc_lines+=("$L"); done <<<"$key_bullets"
  elif [[ -n "${intro_text:-}" ]]; then
    desc_lines+=("")
    desc_lines+=("**Key changes**")
    desc_lines+=("$(printf "%s" "$intro_text")")
  fi

  if [[ -n "$rep_changes" ]]; then
    desc_lines+=("")
    desc_lines+=("**Representative changes**")
    while IFS= read -r L; do desc_lines+=("$L"); done <<<"$rep_changes"
  fi

  local DESCRIPTION
  DESCRIPTION="$(printf "%s\n" "${desc_lines[@]}" | tr -d '\r' | tr -d '\000-\010\013\014\016-\037')"
  DESCRIPTION="${DESCRIPTION:0:3900}"

  # Title (keep it single-line and tidy)
  local TITLE
  TITLE="${LSIO_OWNER}/${LSIO_REPO} → ${UPSTREAM_REPO} ${up_tag}"
  if [[ "$up_tag" == "N/A" && -n "$up_name" ]]; then
    TITLE="${LSIO_OWNER}/${LSIO_REPO} → ${UPSTREAM_REPO} ${up_name} (project)"
  fi
  TITLE="$(printf "%s" "$TITLE" | _oneline | tr -d '\000-\010\013\014\016-\037')"
  TITLE="${TITLE:0:240}"

  # LinuxServer Changes field value (conditionally present)
  local lsio_changes_field=""
  if [[ -n "${alpine_base:-}" || -n "${lsio_non_rebase:-}" ]]; then
    if [[ -n "${alpine_base:-}" ]]; then
      lsio_changes_field="**Rebase**: Alpine ${alpine_base}\n"
    fi
    if [[ -n "${lsio_non_rebase:-}" ]]; then
      lsio_changes_field+="$(
        sed -E 's/^[[:space:]]*[-*•]?[[:space:]]*/• /' <<<"$lsio_non_rebase" | awk 'NR<=10'
      )"
    fi
  fi
  lsio_changes_field="$(printf "%s" "$lsio_changes_field" | tr -d '\r' | tr -d '\000-\010\013\014\016-\037')"
  lsio_changes_field="${lsio_changes_field:0:950}"

  # Build embed payload
  local embed payload
  embed="$(jq -n \
    --arg title "$TITLE" \
    --arg url   "$up_html" \
    --arg desc  "$DESCRIPTION" \
    --arg lsio_tag "$lsio_tag" \
    --arg up_tag  "$up_tag" \
    --arg repo    "${UPSTREAM_OWNER}/${UPSTREAM_REPO}" \
    --arg date    "$up_date" \
    --arg links   "$links_value" \
    --arg lsio_changes "$lsio_changes_field" \
    --argjson color "$DISCORD_COLOR" '
  {
    title: $title,
    url: $url,
    color: $color,
    description: $desc,
    fields: [
      (if $lsio_tag != "" then {name: "LSIO Tag", value: ("`" + $lsio_tag + "`"), inline: true} else empty end),
      {name: "Upstream Version", value: ("`" + ($up_tag // "N/A") + "`"), inline: true},
      (if $lsio_changes != "" then {name: "LinuxServer Changes", value: $lsio_changes, inline: false} else empty end),
      {name: "About", value: ("**Repo**: " + $repo + "\n" + "**Tag**: `" + ($up_tag // "N/A") + "`\n" + "**Date**: " + ($date // "")), inline: false},
      {name: "Links", value: $links, inline: false}
    ],
    footer: { text: "Built from LSIO Remote Changes" },
    timestamp: (if $date != "" then ($date + "T00:00:00Z") else null end)
  }')"

  payload="$(jq -n --argjson e "$embed" '{username:"LSIO Notes", embeds:[ $e ] }')"

  if [[ -n "$WEBHOOK" ]]; then
    local _resp _code
    _resp="$(curl -sS -H "Content-Type: application/json" -d "$payload" -w '\n%{http_code}' "$WEBHOOK")" || {
      err "Discord webhook request failed to send"
      return 1
    }
    _code="${_resp##*$'\n'}"
    if [[ "$_code" =~ ^2[0-9][0-9]$ ]]; then
      printf "Sent embed to Discord.\n" || true
    else
      printf 'Discord webhook error %s: %s\n' "$_code" "${_resp%$'\n'$_code}" >&2
      return 1
    fi
  else
    printf "%s\n" "$payload" || true
  fi
}



# =========================================
# PROVIDER=generic (non-LSIO path)
# =========================================
run_generic() {
  local desired="${UPSTREAM_TAG_OVERRIDE:-}"
  if [[ -n "$desired" && ( "${desired,,}" == "latest" || "${desired,,}" == "current" ) ]]; then
    local real
    real="$(resolve_latest_redirect "$UPSTREAM_OWNER" "$UPSTREAM_REPO")"
    if [[ -n "$real" ]]; then
      dbg "Resolved generic latest -> tag '$real' via redirect"
      desired="$real"
    fi
  fi

  local relkind up_json
  { read -r relkind; up_json="$(cat)"; } < <(fetch_upstream_release "$UPSTREAM_OWNER" "$UPSTREAM_REPO" "${desired:-}")

  local up_name up_tag up_html up_body up_date upstream_exists=0
  if [[ "$relkind" == "RELEASE" ]]; then
    upstream_exists=1
    up_name="$(jq -r '.name // .tag_name // ""' <<<"$up_json")"
    up_tag="$(jq -r '.tag_name // ""' <<<"$up_json")"
    up_html="$(jq -r '.html_url // ""' <<<"$up_json")"
    up_body="$(jq -r '.body // ""' <<<"$up_json" | sed 's/\r//g')"
    up_date="$(jq -r '.published_at // .created_at // ""' <<<"$up_json" | cut -dT -f1)"
  else
    up_name="${desired:-}"
    up_tag="${desired:-N/A}"
    up_html="$(jq -r '.html_url // ""' <<<"$up_json")"
    up_body=""
    up_date=""
  fi

  dbg "Upstream name: ${up_name} / ${up_tag}"
  dbg "Upstream date: ${up_date}"

  local shown_tag=""
  if [[ -n "${UPSTREAM_TAG_OVERRIDE:-}" ]]; then
    shown_tag="${UPSTREAM_TAG_OVERRIDE}"
    [[ -n "$up_tag" && "$up_tag" != "N/A" ]] && shown_tag="$up_tag"
  elif [[ -n "${up_tag:-}" && "$up_tag" != "N/A" ]]; then
    shown_tag="${up_tag}"
  fi
  local context_line
  context_line="$(build_context_line_generic "" "${UPSTREAM_OWNER}/${UPSTREAM_REPO}" "$up_tag")"
  local key_bullets rep_changes intro_text
  key_bullets="$(printf "%s" "$up_body" | select_key_change_bullets 7 || true)"
  if [[ -z "$key_bullets" && -n "$up_body" ]]; then
    intro_text="$(printf "%s" "$up_body" | extract_intro_until_h3 | sed '/^[[:space:]]*$/,$d' || true)"
  fi
  rep_changes="$(printf "%s" "$up_body" | select_representative_changes "$UPSTREAM_OWNER" "$UPSTREAM_REPO" "$MAX_COMMITS" || true)"

  local links_value
  if [[ $upstream_exists -eq 1 ]]; then
    links_value="[Upstream release](${up_html}) • [Full changelog](${up_html}#user-content-changes)"
  else
    links_value="[Upstream project](https://github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO})"
  fi

  desc_lines=()
  desc_lines+=("$context_line")
  if [[ -n "$key_bullets" ]]; then
    desc_lines+=("")
    desc_lines+=("**Key changes**")
    while IFS= read -r L; do desc_lines+=("$L"); done <<< "$key_bullets"
  elif [[ -n "${intro_text:-}" ]]; then
    desc_lines+=("")
    desc_lines+=("**Key changes**")
    desc_lines+=("$(printf "%s" "$intro_text")")
  fi
  if [[ -n "$rep_changes" ]]; then
    desc_lines+=("")
    desc_lines+=("**Representative changes**")
    while IFS= read -r L; do desc_lines+=("$L"); done <<< "$rep_changes"
  fi
  local DESCRIPTION; DESCRIPTION="$(printf "%s\n" "${desc_lines[@]}")"

  local TITLE
  if [[ $upstream_exists -eq 1 ]]; then
    TITLE="${UPSTREAM_REPO} ${up_tag}"
  else
    TITLE="${UPSTREAM_REPO} ${up_name:-} (project)"
  fi

  local embed payload
  embed="$(jq -n \
    --arg title "$TITLE" \
    --arg url   "$up_html" \
    --arg desc  "$DESCRIPTION" \
    --arg up_tag  "$up_tag" \
    --arg repo    "${UPSTREAM_OWNER}/${UPSTREAM_REPO}" \
    --arg date    "$up_date" \
    --arg links   "$links_value" \
    --argjson color "$DISCORD_COLOR" '
  {
    title: $title,
    url: $url,
    color: $color,
    description: $desc,
    fields: [
      {name: "Upstream Version", value: ("`" + ($up_tag // "N/A") + "`"), inline: true},
      {name: "About", value: ("**Repo**: " + $repo + "\n" + "**Tag**: `" + ($up_tag // "N/A") + "`\n" + "**Date**: " + ($date // "")), inline: false},
      {name: "Links", value: $links, inline: false}
    ],
    footer: { text: "Built from Github Release" },
    timestamp: (if $date != "" then ($date + "T00:00:00Z") else null end)
  }')"

  payload="$(jq -n --argjson e "$embed" '{username:"LSIO Notes", embeds:[ $e ] }')"

  if [[ -n "$WEBHOOK" ]]; then
    curl -sS -H "Content-Type: application/json" -d "$payload" "$WEBHOOK" >/dev/null \
      && { printf "Sent embed to Discord.\n" || true; }
  else
    printf "%s\n" "$payload" || true
  fi
}

# =========================================
# Router
# =========================================
case "${PROVIDER,,}" in
  lsio|"") run_lsio ;;
  generic) run_generic ;;
  *) err "Unknown provider: $PROVIDER (use 'lsio' or 'generic')"; exit 2 ;;
esac

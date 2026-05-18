#!/usr/bin/env bash
set -Eeuo pipefail
trap '' PIPE

# =========================================
# Config / Defaults
# =========================================
PROVIDER="${PROVIDER:-github}" # github | generic | lsio
LSIO_OWNER="${LSIO_OWNER:-linuxserver}"
LSIO_REPO="${LSIO_REPO:-}"
UPSTREAM_OWNER="${UPSTREAM_OWNER:-}"
UPSTREAM_REPO="${UPSTREAM_REPO:-}"
TAG_OVERRIDE="${TAG_OVERRIDE:-}"
CURRENT_TAG="${CURRENT_TAG:-}"
IMAGE="${IMAGE:-}"
CONTAINER_NAME="${CONTAINER_NAME:-}"
WEBHOOK=""
MAX_COMMITS="${MAX_COMMITS:-3}"
COLOR_HEX="${COLOR_HEX:-0x57F287}"
DEBUG=0

# =========================================
# Logging
# =========================================
ts() { date +"%Y-%m-%d %H:%M:%S"; }
dbg() {
  if [[ $DEBUG -eq 1 ]]; then
    >&2 printf "[%s] [DEBUG] %s\n" "$(ts)" "$*" || true
  fi
  return 0
}
err() { >&2 printf "[%s] [ERROR] %s\n" "$(ts)" "$*" || true; }
inf() { >&2 printf "[%s] [INFO ] %s\n" "$(ts)" "$*" || true; }

usage() {
  cat >&2 <<'EOF'
usage:
  github-release-embed.sh --repo Owner/Repo [--tag TAG|latest] [--webhook URL]
  github-release-embed.sh --provider lsio --lsio linuxserver/docker-name --upstream Owner/Repo [--tag TAG|latest] [--webhook URL]

options:
  --provider github|generic|lsio
  --repo Owner/Repo
  --upstream Owner/Repo
  --lsio Owner/Repo
  --tag TAG|latest
  --current-tag TAG
  --image IMAGE
  --container NAME
  --webhook URL
  --max-commits N
  --color VALUE
  --debug
EOF
}

split_repo_arg() {
  local value="$1" owner repo extra

  value="${value#https://github.com/}"
  value="${value#http://github.com/}"
  value="${value%.git}"
  IFS=/ read -r owner repo extra <<<"$value"
  if [[ -z "${owner:-}" || -z "${repo:-}" || -n "${extra:-}" ]]; then
    err "Expected repository as Owner/Repo, got: $value"
    exit 2
  fi
  printf '%s\n%s\n' "$owner" "$repo"
}

set_upstream_repo() {
  local parsed
  parsed="$(split_repo_arg "$1")"
  UPSTREAM_OWNER="$(sed -n '1p' <<<"$parsed")"
  UPSTREAM_REPO="$(sed -n '2p' <<<"$parsed")"
}

set_lsio_repo() {
  local parsed
  parsed="$(split_repo_arg "$1")"
  LSIO_OWNER="$(sed -n '1p' <<<"$parsed")"
  LSIO_REPO="$(sed -n '2p' <<<"$parsed")"
}

# =========================================
# Args
# =========================================
while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider)
      PROVIDER="$2"
      shift 2
      ;;
    --repo)
      set_upstream_repo "$2"
      shift 2
      ;;
    --upstream)
      set_upstream_repo "$2"
      shift 2
      ;;
    --lsio)
      set_lsio_repo "$2"
      shift 2
      ;;
    --tag)
      TAG_OVERRIDE="$2"
      shift 2
      ;;
    --current-tag)
      CURRENT_TAG="$2"
      shift 2
      ;;
    --image)
      IMAGE="$2"
      shift 2
      ;;
    --container)
      CONTAINER_NAME="$2"
      shift 2
      ;;
    --webhook)
      WEBHOOK="$2"
      shift 2
      ;;
    --max-commits)
      MAX_COMMITS="$2"
      shift 2
      ;;
    --color)
      COLOR_HEX="$2"
      shift 2
      ;;
    --debug)
      DEBUG=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      err "Unknown arg: $1"
      usage
      exit 2
      ;;
  esac
done

PROVIDER="$(printf "%s" "$PROVIDER" | tr '[:upper:]' '[:lower:]')"
case "$PROVIDER" in
  github|generic|"")
    PROVIDER="github"
    ;;
  lsio)
    PROVIDER="lsio"
    ;;
  *)
    err "Unknown provider: $PROVIDER (use 'github', 'generic', or 'lsio')"
    exit 2
    ;;
esac

if [[ -z "$UPSTREAM_OWNER" || -z "$UPSTREAM_REPO" ]]; then
  err "Missing GitHub repository; pass --repo Owner/Repo"
  exit 2
fi
if [[ "$PROVIDER" == "lsio" && ( -z "$LSIO_OWNER" || -z "$LSIO_REPO" ) ]]; then
  err "Missing LSIO repository; pass --lsio linuxserver/docker-name"
  exit 2
fi

# =========================================
# Preflight
# =========================================
command -v curl >/dev/null 2>&1 || { err "curl not found"; exit 1; }
command -v jq >/dev/null 2>&1 || { err "jq not found"; exit 1; }

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
# GitHub API helpers
# =========================================
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
CURL_HEADERS=(-fsSL -H "Accept: application/vnd.github+json" -H "User-Agent: github-release-embed/1.0")
[[ -n "$GITHUB_TOKEN" ]] && CURL_HEADERS+=(-H "Authorization: Bearer ${GITHUB_TOKEN}")

api_get() {
  local url="$1" tmp

  dbg "GET $url"
  tmp="$(mktemp)"
  if ! curl "${CURL_HEADERS[@]}" -sSf --retry 3 --retry-delay 1 --max-time 20 -o "$tmp" "$url"; then
    if [[ -s "$tmp" ]]; then
      { >&2 printf "[%s] [ERROR] curl body (first 200 bytes): %s\n" "$(ts)" "$(head -c 200 "$tmp" | tr '\n' ' ')" || true; }
    fi
    rm -f "$tmp"
    return 1
  fi
  cat "$tmp" || true
  rm -f "$tmp"
}

resolve_latest_redirect() {
  local owner="$1" repo="$2" url effective tag

  url="https://github.com/${owner}/${repo}/releases/latest"
  dbg "HEAD/GET (follow) $url"
  effective="$(curl -fsSL -o /dev/null -w '%{url_effective}' -H "User-Agent: github-release-embed/1.0" "$url" || true)"
  [[ -n "$effective" ]] || {
    printf ''
    return 0
  }
  tag="$(sed -nE 's#.*/releases/tag/([^/?#]+).*#\1#p' <<<"$effective")"
  printf "%s" "$tag"
}

fetch_github_release() {
  local owner="$1" repo="$2" tag="${3:-}" rel="" list="" list_type="" repo_json=""
  local candidates=() candidate real

  if [[ -n "$tag" ]]; then
    case "$(printf "%s" "$tag" | tr '[:upper:]' '[:lower:]')" in
      latest|current)
        real="$(resolve_latest_redirect "$owner" "$repo")"
        if [[ -n "$real" ]]; then
          dbg "Resolved latest -> tag '$real' via redirect"
          tag="$real"
        else
          dbg "Could not resolve latest via redirect; using API latest endpoint"
          tag=""
        fi
        ;;
    esac
  fi

  if [[ -n "$tag" ]]; then
    if [[ "$tag" =~ ^[vV] ]]; then
      candidates+=("$tag")
    else
      candidates+=("v$tag" "$tag")
    fi
    for candidate in "${candidates[@]}"; do
      rel="$(api_get "https://api.github.com/repos/${owner}/${repo}/releases/tags/${candidate}" || true)"
      if [[ -n "$rel" && "$(jq -r '.message // empty' <<<"$rel" 2>/dev/null || true)" != "Not Found" ]]; then
        break
      fi
      rel=""
    done
  else
    rel="$(api_get "https://api.github.com/repos/${owner}/${repo}/releases/latest" || true)"
  fi

  if [[ -z "$rel" || "$rel" == "null" || "$(jq -r '.message // empty' <<<"$rel" 2>/dev/null || true)" == "Not Found" ]]; then
    if [[ -n "$tag" ]]; then
      list="$(api_get "https://api.github.com/repos/${owner}/${repo}/releases?per_page=100" || true)"
      list_type="$(jq -r 'type' <<<"$list" 2>/dev/null || true)"
      if [[ "$list_type" == "array" ]]; then
        rel="$(jq --arg v "$tag" -c '
          first(.[] | select(
            (.tag_name == ("v" + $v)) or
            (.tag_name == $v) or
            ((.name // "") | contains($v))
          )) // empty
        ' <<<"$list")"
      fi
    fi
  fi

  if [[ -z "$rel" || "$rel" == "null" || "$(jq -r '.message // empty' <<<"$rel" 2>/dev/null || true)" == "Not Found" ]]; then
    if [[ -z "$tag" ]]; then
      real="$(resolve_latest_redirect "$owner" "$repo")"
      if [[ -n "$real" ]]; then
        dbg "Final fallback: resolved latest -> tag '$real' via redirect"
        rel="$(api_get "https://api.github.com/repos/${owner}/${repo}/releases/tags/${real}" || true)"
      fi
    fi
  fi

  if [[ -z "$rel" || "$rel" == "null" || "$(jq -r '.message // empty' <<<"$rel" 2>/dev/null || true)" == "Not Found" ]]; then
    repo_json="$(api_get "https://api.github.com/repos/${owner}/${repo}" || true)"
    if [[ -z "$repo_json" || "$(jq -r 'type' <<<"$repo_json" 2>/dev/null || true)" != "object" ]]; then
      repo_json="$(jq -n --arg url "https://github.com/${owner}/${repo}" '{html_url:$url}')"
    fi
    printf 'FALLBACK\n%s\n' "$repo_json"
  else
    printf 'RELEASE\n%s\n' "$rel"
  fi
}

# =========================================
# Markdown helpers
# =========================================
sanitize_text() {
  tr -d '\r' | tr -d '\000-\010\013\014\016-\037'
}

strip_md_headers() {
  sed -E 's/\r//g; s/^\*\*([A-Za-z0-9 _-]+):\*\*/\1:/; s/[[:space:]]+$//'
}

extract_block_header_ci() {
  local header="$1"
  awk -v target="$(printf "%s" "$header" | tr '[:upper:]' '[:lower:]')" '
    function lower(s, i, c, out) {
      out=""
      for (i=1; i<=length(s); i++) {
        c=substr(s,i,1)
        if (c>="A" && c<="Z") c=tolower(c)
        out=out c
      }
      return out
    }
    {
      line=$0
      low=lower(line)
      is_hdr=match(line, /^[[:space:]]*[A-Za-z0-9 _-]+:[[:space:]]*$/)
      if (low == target) { print line; show=1; next }
      if (show == 1 && is_hdr) exit
      if (show == 1) print line
    }
  '
}

extract_md_h2_section_ci() {
  local h2="$1"
  awk -v key="$(printf "%s" "$h2" | tr '[:upper:]' '[:lower:]')" '
    function lower(s, i, c, out) {
      out=""
      for (i=1; i<=length(s); i++) {
        c=substr(s,i,1)
        if (c>="A" && c<="Z") c=tolower(c)
        out=out c
      }
      return out
    }
    /^##[[:space:]]+/ {
      header=lower($0)
      sub(/^##[[:space:]]*/, "", header)
      sub(/[[:space:]:]*$/, "", header)
      if (header == key) { print $0; show=1; next }
      if (show == 1) exit
    }
    { if (show == 1) print $0 }
  '
}

extract_upstream_version() {
  local text version=""

  text="$(cat)"
  version="$(printf "%s\n" "$text" \
    | grep -Eoim1 'updat(ing|e)[[:space:]]+to[[:space:]]+[vV]?[0-9]+(\.[0-9]+){1,}([[:alnum:]._-])*' \
    | sed -E 's/.*to[[:space:]]+//' || true)"
  [[ -z "$version" ]] && version="$(printf "%s\n" "$text" \
    | grep -Eoim1 'bump[[:space:]]+to[[:space:]]+[vV]?[0-9]+(\.[0-9]+){1,}([[:alnum:]._-])*' \
    | sed -E 's/.*to[[:space:]]+//' || true)"
  [[ -z "$version" ]] && version="$(printf "%s\n" "$text" \
    | grep -Eoim1 '[vV]?[0-9]+(\.[0-9]+){1,}([[:alnum:]._-])*' || true)"
  printf "%s" "$version"
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
    function lower(s, i, c, out) {
      out=""
      for (i=1; i<=length(s); i++) {
        c=substr(s,i,1)
        if (c>="A" && c<="Z") c=tolower(c)
        out=out c
      }
      return out
    }
    function is_bullet(s) { return (s ~ /^[[:space:]]*([*+-]|•)[[:space:]]/) }
    {
      lines++
      line=$0
      low=lower(line)
      if (low ~ /^##[[:space:]]*key[[:space:]]*changes[[:space:]]*$/) { in_key=1; next }
      if (in_key && line ~ /^##[[:space:]]/) in_key=0
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
  done < <(printf "%s\n" "$section" | sed -n '/^##/,$p' | sed '1d')
}

extract_intro_until_h3() {
  awk '{ if ($0 ~ /^###[[:space:]]/) exit; print }'
}

semver_first() {
  tr -d '\r' \
    | tr -cs '0-9A-Za-z._ -' '\n' \
    | grep -m1 -E '^[vV]?[0-9]+(\.[0-9]+){1,3}([._-][0-9A-Za-z]+)?$' \
    || true
}

oneline() {
  tr -d '\r' | awk 'NR == 1 { print; exit }'
}

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
  printf "%s" "$breaking"
}

build_description() {
  local context="$1" body="$2" owner="$3" repo="$4"
  local key_bullets intro_text rep_changes line
  local -a lines

  lines=("$context")
  key_bullets="$(select_key_change_bullets 7 <<<"$body" 2>/dev/null || true)"
  if [[ -z "$key_bullets" && -n "$body" ]]; then
    intro_text="$(extract_intro_until_h3 <<<"$body" 2>/dev/null | sed '/^[[:space:]]*$/,$d' || true)"
  fi
  rep_changes="$(select_representative_changes "$owner" "$repo" "$MAX_COMMITS" <<<"$body" 2>/dev/null || true)"

  if [[ -n "$key_bullets" ]]; then
    lines+=("")
    lines+=("**Key changes**")
    while IFS= read -r line; do
      lines+=("$line")
    done <<<"$key_bullets"
  elif [[ -n "${intro_text:-}" ]]; then
    lines+=("")
    lines+=("**Key changes**")
    lines+=("$(printf "%s" "$intro_text")")
  fi

  if [[ -n "$rep_changes" ]]; then
    lines+=("")
    lines+=("**Representative changes**")
    while IFS= read -r line; do
      lines+=("$line")
    done <<<"$rep_changes"
  fi

  printf "%s\n" "${lines[@]}" | sanitize_text
}

send_or_print_payload() {
  local payload="$1" response code

  if [[ -z "$WEBHOOK" ]]; then
    printf "%s\n" "$payload" || true
    return 0
  fi

  response="$(curl -sS -H "Content-Type: application/json" -d "$payload" -w '\n%{http_code}' "$WEBHOOK")" || {
    err "Discord webhook request failed to send"
    return 1
  }
  code="${response##*$'\n'}"
  if [[ "$code" =~ ^2[0-9][0-9]$ ]]; then
    printf "Sent embed to Discord.\n" || true
    return 0
  fi

  err "Discord webhook error $code"
  return 1
}

build_context_line_generic() {
  local image="$1" repo="$2" tag="$3" left

  left="\`$repo\`"
  [[ -n "$image" ]] && left="\`$image\`"
  if [[ -n "$tag" && "$tag" != "N/A" ]]; then
    printf "%s - %s" "$left" "$tag"
  else
    printf "%s" "$left"
  fi
}

build_context_line_lsio() {
  local image="$1" lsio_tag="$2" alpine="$3" tag_suffix

  tag_suffix="$(awk -F- '{print $NF}' <<<"$lsio_tag")"
  if [[ -n "$alpine" ]]; then
    printf "\`%s\` - %s - Alpine %s" "$image" "$tag_suffix" "$alpine"
  else
    printf "\`%s\` - %s" "$image" "$tag_suffix"
  fi
}

# =========================================
# Provider: GitHub
# =========================================
run_github() {
  local relkind up_json up_name up_tag up_html up_body up_date upstream_exists=0
  local context_line description title links_value version_value breaking embed payload

  { read -r relkind; up_json="$(cat)"; } < <(fetch_github_release "$UPSTREAM_OWNER" "$UPSTREAM_REPO" "${TAG_OVERRIDE:-}")

  if [[ "$relkind" == "RELEASE" ]]; then
    upstream_exists=1
    up_name="$(jq -r '.name // .tag_name // ""' <<<"$up_json" | oneline)"
    up_tag="$(jq -r '.tag_name // ""' <<<"$up_json" | oneline)"
    up_html="$(jq -r '.html_url // ""' <<<"$up_json" | oneline)"
    up_body="$(jq -r '.body // ""' <<<"$up_json" | sanitize_text)"
    up_date="$(jq -r '.published_at // .created_at // ""' <<<"$up_json" | cut -dT -f1)"
  else
    inf "GitHub release not found for ${UPSTREAM_OWNER}/${UPSTREAM_REPO}${TAG_OVERRIDE:+ tag ${TAG_OVERRIDE}}; falling back to project homepage"
    up_name="${TAG_OVERRIDE:-}"
    up_tag="${TAG_OVERRIDE:-N/A}"
    up_html="$(jq -r '.html_url // ""' <<<"$up_json" | oneline)"
    up_body=""
    up_date=""
  fi
  [[ -n "$up_html" && "$up_html" != "null" ]] || up_html="https://github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO}"

  context_line="$(build_context_line_generic "$IMAGE" "${UPSTREAM_OWNER}/${UPSTREAM_REPO}" "$up_tag")"
  description="$(build_description "$context_line" "$up_body" "$UPSTREAM_OWNER" "$UPSTREAM_REPO")"
  description="${description:0:3900}"

  if [[ $upstream_exists -eq 1 ]]; then
    title="Release ${up_tag} for ${UPSTREAM_OWNER}/${UPSTREAM_REPO}"
    links_value="[GitHub release](${up_html})"
    [[ "$up_html" == *"/releases/tag/"* ]] && links_value="${links_value} - [Full changelog](${up_html}#user-content-changes)"
  else
    title="${UPSTREAM_OWNER}/${UPSTREAM_REPO} ${up_name:-releases}"
    links_value="[GitHub project](${up_html})"
  fi
  title="$(printf "%s" "$title" | oneline | sanitize_text)"
  title="${title:0:240}"

  version_value="$up_tag"
  if [[ -n "$CURRENT_TAG" && "$up_tag" != "N/A" ]]; then
    version_value="${CURRENT_TAG} -> ${up_tag}"
  fi
  breaking="$(detect_breaking "$up_body" "$CURRENT_TAG" "$up_tag")"

  embed="$(jq -n \
    --arg title "$title" \
    --arg url "$up_html" \
    --arg desc "$description" \
    --arg breaking "$breaking" \
    --arg image "$IMAGE" \
    --arg container "$CONTAINER_NAME" \
    --arg repo "${UPSTREAM_OWNER}/${UPSTREAM_REPO}" \
    --arg version "$version_value" \
    --arg date "$up_date" \
    --arg links "$links_value" \
    --argjson color "$DISCORD_COLOR" '
  {
    title: $title,
    url: $url,
    color: $color,
    description: $desc,
    fields: [
      {name: "Breaking", value: $breaking, inline: true},
      (if $image != "" then {name: "Image", value: $image, inline: true} else empty end),
      (if $container != "" then {name: "Container", value: $container, inline: true} else empty end),
      {name: "Repository", value: $repo, inline: true},
      {name: "Version", value: $version, inline: true},
      {name: "Links", value: $links, inline: false}
    ],
    footer: { text: "Built from GitHub Release" },
    timestamp: (if $date != "" then ($date + "T00:00:00Z") else null end)
  }')"

  payload="$(jq -n --argjson e "$embed" '{username:"GitHub Release Notes", allowed_mentions:{parse:[]}, embeds:[ $e ] }')"
  send_or_print_payload "$payload"
}

# =========================================
# Provider: LinuxServer.io upstream support
# =========================================
run_lsio() {
  local lsio_json lsio_tag lsio_body lsio_html norm_lsio_body linux_block remote_block
  local upstream_version_raw upstream_version alpine_base ci_url lsio_changes_text lsio_non_rebase
  local relkind up_json up_name up_tag up_html up_body up_date upstream_exists=0
  local context_line description title links_value lsio_changes_field embed payload line

  lsio_json="$(api_get "https://api.github.com/repos/${LSIO_OWNER}/${LSIO_REPO}/releases/latest")"
  if [[ -z "$lsio_json" || "$(jq -r '.message // empty' <<<"$lsio_json" 2>/dev/null || true)" == "Not Found" ]]; then
    err "LSIO latest release not found for ${LSIO_OWNER}/${LSIO_REPO}"
    exit 1
  fi

  lsio_tag="$(jq -r '.tag_name // ""' <<<"$lsio_json" | oneline)"
  lsio_body="$(jq -r '.body // ""' <<<"$lsio_json" | sanitize_text)"
  lsio_html="$(jq -r '.html_url // ""' <<<"$lsio_json" | oneline)"

  norm_lsio_body="$(strip_md_headers <<<"$lsio_body" 2>/dev/null)"
  linux_block="$(extract_block_header_ci "linuxserver changes:" <<<"$norm_lsio_body" 2>/dev/null || true)"
  remote_block="$(extract_block_header_ci "remote changes:" <<<"$norm_lsio_body" 2>/dev/null || true)"

  upstream_version_raw="$(extract_upstream_version <<<"$remote_block" 2>/dev/null || true)"
  upstream_version="$(printf "%s" "$upstream_version_raw" | semver_first)"
  [[ -z "$upstream_version" ]] && upstream_version="$(printf "%s" "$lsio_tag" | semver_first)"
  [[ -n "$TAG_OVERRIDE" ]] && upstream_version="$TAG_OVERRIDE"

  alpine_base="$(extract_alpine_base <<<"$linux_block" 2>/dev/null || true)"
  ci_url="$(extract_ci_link <<<"$lsio_body" 2>/dev/null || true)"
  lsio_changes_text="$(sed '1d' <<<"$linux_block" | sed '/^[[:space:]]*$/d')"
  lsio_non_rebase="$(grep -viE '^[[:space:]]*[-*•]?[[:space:]]*rebase( to)? alpine[[:space:]]+[0-9]+\.[0-9]+' <<<"$lsio_changes_text" 2>/dev/null || true)"

  dbg "LSIO tag: $lsio_tag"
  dbg "Remote version: ${upstream_version:-<none>}"
  dbg "Alpine base: ${alpine_base:-<none>}"
  dbg "CI link: ${ci_url:-<none>}"

  { read -r relkind; up_json="$(cat)"; } < <(fetch_github_release "$UPSTREAM_OWNER" "$UPSTREAM_REPO" "${upstream_version:-}")
  if [[ "$relkind" == "FALLBACK" && -z "${upstream_version:-}" ]]; then
    { read -r relkind; up_json="$(cat)"; } < <(fetch_github_release "$UPSTREAM_OWNER" "$UPSTREAM_REPO" "latest")
  fi

  if [[ "$relkind" == "RELEASE" ]]; then
    upstream_exists=1
    up_name="$(jq -r '.name // .tag_name // ""' <<<"$up_json" | oneline)"
    up_tag="$(jq -r '.tag_name // ""' <<<"$up_json" | oneline)"
    up_html="$(jq -r '.html_url // ""' <<<"$up_json" | oneline)"
    up_body="$(jq -r '.body // ""' <<<"$up_json" | sanitize_text)"
    up_date="$(jq -r '.published_at // .created_at // ""' <<<"$up_json" | cut -dT -f1)"
  else
    inf "Upstream release not found for ${UPSTREAM_OWNER}/${UPSTREAM_REPO}${upstream_version:+ tag ${upstream_version}}; falling back to project homepage"
    up_name="$(printf "%s" "${upstream_version:-}" | oneline)"
    up_tag="N/A"
    up_html="$(jq -r '.html_url // ""' <<<"$up_json" | oneline)"
    up_body=""
    up_date=""
  fi
  [[ -n "$up_html" && "$up_html" != "null" ]] || up_html="https://github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO}"

  context_line="$(build_context_line_lsio "${LSIO_OWNER}/${LSIO_REPO}" "$lsio_tag" "${alpine_base:-}")"
  description="$(build_description "$context_line" "$up_body" "$UPSTREAM_OWNER" "$UPSTREAM_REPO")"
  description="${description:0:3900}"

  if [[ $upstream_exists -eq 1 ]]; then
    links_value="[LSIO release](${lsio_html}) - [Upstream release](${up_html}) - [Full changelog](${up_html}#user-content-changes)"
  else
    links_value="[LSIO release](${lsio_html}) - [Upstream project](https://github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO})"
  fi
  [[ -n "${ci_url:-}" ]] && links_value="${links_value} - [CI](${ci_url})"

  title="${LSIO_OWNER}/${LSIO_REPO} -> ${UPSTREAM_REPO} ${up_tag}"
  if [[ "$up_tag" == "N/A" && -n "$up_name" ]]; then
    title="${LSIO_OWNER}/${LSIO_REPO} -> ${UPSTREAM_REPO} ${up_name} (project)"
  fi
  title="$(printf "%s" "$title" | oneline | sanitize_text)"
  title="${title:0:240}"

  lsio_changes_field=""
  if [[ -n "${alpine_base:-}" || -n "${lsio_non_rebase:-}" ]]; then
    if [[ -n "${alpine_base:-}" ]]; then
      lsio_changes_field="**Rebase**: Alpine ${alpine_base}\n"
    fi
    if [[ -n "${lsio_non_rebase:-}" ]]; then
      while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        lsio_changes_field+="- ${line#- }"$'\n'
      done < <(awk 'NR<=10' <<<"$lsio_non_rebase")
    fi
  fi
  lsio_changes_field="$(printf "%s" "$lsio_changes_field" | sanitize_text)"
  lsio_changes_field="${lsio_changes_field:0:950}"

  embed="$(jq -n \
    --arg title "$title" \
    --arg url "$up_html" \
    --arg desc "$description" \
    --arg lsio_tag "$lsio_tag" \
    --arg up_tag "$up_tag" \
    --arg repo "${UPSTREAM_OWNER}/${UPSTREAM_REPO}" \
    --arg date "$up_date" \
    --arg links "$links_value" \
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

  payload="$(jq -n --argjson e "$embed" '{username:"GitHub Release Notes", allowed_mentions:{parse:[]}, embeds:[ $e ] }')"
  send_or_print_payload "$payload"
}

case "$PROVIDER" in
  github)
    run_github
    ;;
  lsio)
    run_lsio
    ;;
esac

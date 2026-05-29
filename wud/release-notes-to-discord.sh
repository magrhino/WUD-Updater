#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=wud/http.sh
source "${SCRIPT_DIR}/http.sh"

PROVIDER="${PROVIDER:-auto}"
IMAGE=""
CONTAINER_NAME=""
CURRENT_TAG=""
TAG_OVERRIDE=""
UPSTREAM_OWNER=""
UPSTREAM_REPO=""
LSIO_OWNER="${LSIO_OWNER:-linuxserver}"
LSIO_REPO=""
WEBHOOK="${DISCORD_RELEASES_WEBHOOK:-${DISCORD_WEBHOOK:-}}"
ADMIN_WEBHOOK="${ADMIN_WEBHOOK:-$WEBHOOK}"
UPSTREAM_MAP="${UPSTREAM_MAP:-${SCRIPT_DIR}/upstreams.txt}"
COLOR_HEX="${COLOR_HEX:-0x57F287}"
DISCORD_COLOR="$((COLOR_HEX))"

usage() {
  cat <<'EOF'
Usage:
  release-notes-to-discord.sh <image> [container_name] [current_tag]
  release-notes-to-discord.sh --repo Owner/Repo [--tag TAG|latest] [--webhook URL]
  release-notes-to-discord.sh --provider lsio --lsio linuxserver/docker-name --upstream Owner/Repo [--webhook URL]
EOF
}

err() {
  printf '%s\n' "$*" >&2
}

sanitize_text() {
  tr -d '\r' | tr -d '\000-\010\013\014\016-\037'
}

oneline() {
  tr -d '\r' | awk 'NR == 1 { print; exit }'
}

normalize_repo() {
  local value="$1" owner repo rest
  value="${value#https://github.com/}"
  value="${value#http://github.com/}"
  value="${value#git@github.com:}"
  value="${value%.git}"
  value="${value%%#*}"
  value="${value%%\?*}"
  IFS=/ read -r owner repo rest <<<"$value"
  if [[ -z "$owner" || -z "$repo" || -n "$rest" ]]; then
    return 1
  fi
  case "$owner/$repo" in
    *[!A-Za-z0-9_.-]*/*|*/*[!A-Za-z0-9_.-]*)
      return 1
      ;;
  esac
  printf '%s/%s\n' "$owner" "$repo"
}

set_upstream_repo() {
  local normalized
  normalized="$(normalize_repo "$1")" || {
    err "Invalid GitHub repository: $1"
    exit 2
  }
  UPSTREAM_OWNER="${normalized%%/*}"
  UPSTREAM_REPO="${normalized#*/}"
}

set_lsio_repo() {
  local normalized
  normalized="$(normalize_repo "$1")" || {
    err "Invalid LSIO repository: $1"
    exit 2
  }
  LSIO_OWNER="${normalized%%/*}"
  LSIO_REPO="${normalized#*/}"
}

while [[ "$#" -gt 0 && "${1:-}" == --* ]]; do
  case "$1" in
    --provider)
      PROVIDER="${2:?missing value for --provider}"
      shift 2
      ;;
    --repo|--upstream)
      set_upstream_repo "${2:?missing value for $1}"
      shift 2
      ;;
    --lsio)
      set_lsio_repo "${2:?missing value for --lsio}"
      shift 2
      ;;
    --tag)
      TAG_OVERRIDE="${2:?missing value for --tag}"
      shift 2
      ;;
    --webhook)
      WEBHOOK="${2:?missing value for --webhook}"
      shift 2
      ;;
    --image)
      IMAGE="${2:?missing value for --image}"
      shift 2
      ;;
    --container)
      CONTAINER_NAME="${2:?missing value for --container}"
      shift 2
      ;;
    --current-tag)
      CURRENT_TAG="${2:?missing value for --current-tag}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      err "Unknown option: $1"
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$#" -gt 0 ]]; then
  IMAGE="$1"
  CONTAINER_NAME="${2:-}"
  CURRENT_TAG="${3:-}"
fi

api_get() {
  local url="$1" tmp
  local -a headers
  headers=(-H "Accept: application/vnd.github+json" -H "User-Agent: wud-updater-release-notes/1.0")
  [[ -n "${GITHUB_TOKEN:-}" ]] && headers+=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
  tmp="$(mktemp)"
  if http_get_to_file "$tmp" "$url" "${headers[@]}"; then
    cat "$tmp"
    rm -f "$tmp"
    return 0
  fi
  rm -f "$tmp"
  return 1
}

lookup_upstream() {
  local key="$1"
  [[ -r "$UPSTREAM_MAP" ]] || return 1
  awk -v k="$key" -F: '
    $0 ~ /^[[:space:]]*#/ { next }
    NF >= 2 {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $1)
      if ($1 == k) {
        sub(/^[[:space:]]+/, "", $2)
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2)
        print $2
        exit 0
      }
    }' "$UPSTREAM_MAP"
}

extract_github_source_repo() {
  local source="$1"
  [[ "$source" == *github.com* ]] || return 1
  normalize_repo "$source"
}

extract_ghcr_repo() {
  local image="$1" without_digest path owner repo rest
  without_digest="${image%%@sha256:*}"
  without_digest="${without_digest%%:*}"
  case "$without_digest" in
    ghcr.io/*) path="${without_digest#ghcr.io/}" ;;
    *) return 1 ;;
  esac
  IFS=/ read -r owner repo rest <<<"$path"
  [[ -n "$owner" && -n "$repo" && -z "$rest" ]] || return 1
  normalize_repo "$owner/$repo"
}

extract_lsio_repo_from_image() {
  local value="$1" repo base
  value="${image_name:-$value}"
  value="${value%%@sha256:*}"
  value="${value%%:*}"
  case "$value" in
    linuxserver/*) repo="${value}" ;;
    */linuxserver/*) repo="${value#*/}" ;;
    *) return 1 ;;
  esac
  base="${repo#linuxserver/}"
  if [[ "$base" == docker-* ]]; then
    printf 'linuxserver/%s\n' "$base"
  else
    printf 'linuxserver/docker-%s\n' "$base"
  fi
}

release_json_value() {
  local json="$1" key="$2"
  jq -r --arg key "$key" '.[$key] // ""' <<<"$json" | oneline
}

fetch_github_release() {
  local owner="$1" repo="$2" tag="${3:-}" rel="" repo_json="" candidate
  local -a candidates

  if [[ -n "$tag" && "$tag" != latest && "$tag" != current ]]; then
    if [[ "$tag" =~ ^[vV] ]]; then
      candidates=("$tag")
    else
      candidates=("v$tag" "$tag")
    fi
    for candidate in "${candidates[@]}"; do
      rel="$(api_get "https://api.github.com/repos/${owner}/${repo}/releases/tags/${candidate}" || true)"
      if [[ -n "$rel" && "$(jq -r '.message // empty' <<<"$rel" 2>/dev/null || true)" != "Not Found" ]]; then
        printf 'RELEASE\n%s\n' "$rel"
        return 0
      fi
    done
  else
    rel="$(api_get "https://api.github.com/repos/${owner}/${repo}/releases/latest" || true)"
    if [[ -n "$rel" && "$(jq -r '.message // empty' <<<"$rel" 2>/dev/null || true)" != "Not Found" ]]; then
      printf 'RELEASE\n%s\n' "$rel"
      return 0
    fi
  fi

  repo_json="$(api_get "https://api.github.com/repos/${owner}/${repo}" || true)"
  if [[ -z "$repo_json" || "$(jq -r 'type' <<<"$repo_json" 2>/dev/null || true)" != "object" ]]; then
    repo_json="$(jq -n --arg url "https://github.com/${owner}/${repo}" '{html_url:$url}')"
  fi
  printf 'FALLBACK\n%s\n' "$repo_json"
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
  printf '%s' "$breaking"
}

semver_first() {
  tr -d '\r' \
    | tr -cs '0-9A-Za-z._ -' '\n' \
    | grep -m1 -E '^[vV]?[0-9]+(\.[0-9]+){1,3}([._-][0-9A-Za-z]+)?$' \
    || true
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

extract_upstream_version() {
  sed -nE 's/.*[Uu]pdat(e|ing)[^0-9vV]*([vV]?[0-9][0-9A-Za-z._-]*).*/\2/p' | head -n 1
}

extract_alpine_base() {
  sed -nE 's/.*[Aa]lpine[[:space:]]+([0-9]+(\.[0-9]+)?).*/\1/p' | head -n 1
}

extract_ci_link() {
  sed -nE 's#.*(https://ci\.linuxserver\.io/[^ )]+).*#\1#p' | head -n 1
}

build_context_line() {
  local image="$1" tag="$2"
  if [[ -n "$tag" && "$tag" != "N/A" ]]; then
    printf '%s%s%s - %s' '`' "$image" '`' "$tag"
  else
    printf '%s%s%s' '`' "$image" '`'
  fi
}

build_description() {
  local context="$1" body="$2"
  {
    printf '%s\n' "$context"
    if [[ -n "$body" ]]; then
      printf '\n**Key changes**\n'
      printf '%s\n' "$body" \
        | awk '
          /^[[:space:]]*[-*][[:space:]]+/ {
            sub(/^[[:space:]]*[-*][[:space:]]+/, "- ")
            print
            count++
            if (count == 7) exit
          }'
    fi
  } | sanitize_text
}

send_or_print_payload() {
  local payload="$1"
  if [[ -z "$WEBHOOK" ]]; then
    printf '%s\n' "$payload"
    return 0
  fi
  if ! http_post_discord_json "$WEBHOOK" "$payload"; then
    err "${HTTP_DISCORD_ERROR:-Discord webhook request failed to send}"
    return 1
  fi
}

post_minimal_notice() {
  local title="Update available: ${IMAGE}" desc payload
  desc="No GitHub source label found. Unable to fetch release notes."
  payload="$(jq -n --arg t "$title" --arg d "$desc" \
    '{allowed_mentions:{parse:[]},embeds:[{title:$t,description:$d}] }')"
  send_or_print_payload "$payload"
}

run_github() {
  local relkind json name tag html body date exists=0 context desc title links version breaking embed payload
  { read -r relkind; json="$(cat)"; } < <(fetch_github_release "$UPSTREAM_OWNER" "$UPSTREAM_REPO" "${TAG_OVERRIDE:-}")
  if [[ "$relkind" == "RELEASE" ]]; then
    exists=1
    name="$(release_json_value "$json" name)"
    tag="$(release_json_value "$json" tag_name)"
    html="$(release_json_value "$json" html_url)"
    body="$(jq -r '.body // ""' <<<"$json" | sanitize_text)"
    date="$(jq -r '.published_at // .created_at // ""' <<<"$json" | cut -dT -f1)"
  else
    name="${TAG_OVERRIDE:-}"
    tag="${TAG_OVERRIDE:-N/A}"
    html="$(release_json_value "$json" html_url)"
    body=""
    date=""
  fi
  [[ -n "$html" && "$html" != "null" ]] || html="https://github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO}"

  context="$(build_context_line "${IMAGE:-${UPSTREAM_OWNER}/${UPSTREAM_REPO}}" "$tag")"
  desc="$(build_description "$context" "$body")"
  desc="${desc:0:3900}"
  if (( exists )); then
    title="Release ${tag} for ${UPSTREAM_OWNER}/${UPSTREAM_REPO}"
    links="[GitHub release](${html})"
  else
    title="${UPSTREAM_OWNER}/${UPSTREAM_REPO} ${name:-releases}"
    links="[GitHub project](${html})"
  fi
  version="$tag"
  [[ -n "$CURRENT_TAG" && "$tag" != "N/A" ]] && version="${CURRENT_TAG} -> ${tag}"
  breaking="$(detect_breaking "$body" "$CURRENT_TAG" "$tag")"

  embed="$(jq -n \
    --arg title "$title" --arg url "$html" --arg desc "$desc" \
    --arg breaking "$breaking" --arg image "$IMAGE" --arg container "$CONTAINER_NAME" \
    --arg repo "${UPSTREAM_OWNER}/${UPSTREAM_REPO}" --arg version "$version" \
    --arg date "$date" --arg links "$links" --argjson color "$DISCORD_COLOR" '
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

run_lsio() {
  local lsio_json lsio_tag lsio_body lsio_html linux_block remote_block upstream_version_raw upstream_version
  local alpine_base ci_url lsio_changes_text lsio_non_rebase relkind up_json up_tag up_html up_body up_date exists=0
  local context desc title links lsio_changes embed payload line

  lsio_json="$(api_get "https://api.github.com/repos/${LSIO_OWNER}/${LSIO_REPO}/releases/latest")"
  if [[ -z "$lsio_json" || "$(jq -r '.message // empty' <<<"$lsio_json" 2>/dev/null || true)" == "Not Found" ]]; then
    err "LSIO latest release not found for ${LSIO_OWNER}/${LSIO_REPO}"
    return 1
  fi
  lsio_tag="$(release_json_value "$lsio_json" tag_name)"
  lsio_body="$(jq -r '.body // ""' <<<"$lsio_json" | sanitize_text)"
  lsio_html="$(release_json_value "$lsio_json" html_url)"
  linux_block="$(extract_block_header_ci "linuxserver changes:" <<<"$lsio_body" 2>/dev/null || true)"
  remote_block="$(extract_block_header_ci "remote changes:" <<<"$lsio_body" 2>/dev/null || true)"
  upstream_version_raw="$(extract_upstream_version <<<"$remote_block" 2>/dev/null || true)"
  upstream_version="$(printf '%s' "$upstream_version_raw" | semver_first)"
  [[ -z "$upstream_version" ]] && upstream_version="$(printf '%s' "$lsio_tag" | semver_first)"
  [[ -n "$TAG_OVERRIDE" ]] && upstream_version="$TAG_OVERRIDE"
  alpine_base="$(extract_alpine_base <<<"$linux_block" 2>/dev/null || true)"
  ci_url="$(extract_ci_link <<<"$lsio_body" 2>/dev/null || true)"
  lsio_changes_text="$(sed '1d' <<<"$linux_block" | sed '/^[[:space:]]*$/d')"
  lsio_non_rebase="$(grep -viE '^[[:space:]]*[-*•]?[[:space:]]*rebase( to)? alpine[[:space:]]+[0-9]+\.[0-9]+' <<<"$lsio_changes_text" 2>/dev/null || true)"

  { read -r relkind; up_json="$(cat)"; } < <(fetch_github_release "$UPSTREAM_OWNER" "$UPSTREAM_REPO" "${upstream_version:-}")
  if [[ "$relkind" == "RELEASE" ]]; then
    exists=1
    up_tag="$(release_json_value "$up_json" tag_name)"
    up_html="$(release_json_value "$up_json" html_url)"
    up_body="$(jq -r '.body // ""' <<<"$up_json" | sanitize_text)"
    up_date="$(jq -r '.published_at // .created_at // ""' <<<"$up_json" | cut -dT -f1)"
  else
    up_tag="N/A"
    up_html="$(release_json_value "$up_json" html_url)"
    up_body=""
    up_date=""
  fi
  [[ -n "$up_html" && "$up_html" != "null" ]] || up_html="https://github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO}"

  context="$(build_context_line "${LSIO_OWNER}/${LSIO_REPO}" "$lsio_tag")"
  desc="$(build_description "$context" "$up_body")"
  desc="${desc:0:3900}"
  if (( exists )); then
    links="[LSIO release](${lsio_html}) - [Upstream release](${up_html})"
  else
    links="[LSIO release](${lsio_html}) - [Upstream project](https://github.com/${UPSTREAM_OWNER}/${UPSTREAM_REPO})"
  fi
  [[ -n "$ci_url" ]] && links="${links} - [CI](${ci_url})"
  title="${LSIO_OWNER}/${LSIO_REPO} -> ${UPSTREAM_REPO} ${up_tag}"

  lsio_changes=""
  if [[ -n "$alpine_base" ]]; then
    lsio_changes="**Rebase**: Alpine ${alpine_base}\n"
  fi
  if [[ -n "$lsio_non_rebase" ]]; then
    while IFS= read -r line; do
      [[ -n "$line" ]] || continue
      lsio_changes+="- ${line#- }"$'\n'
    done < <(awk 'NR<=10' <<<"$lsio_non_rebase")
  fi
  lsio_changes="$(printf '%s' "$lsio_changes" | sanitize_text)"
  lsio_changes="${lsio_changes:0:950}"

  embed="$(jq -n \
    --arg title "$title" --arg url "$up_html" --arg desc "$desc" \
    --arg lsio_tag "$lsio_tag" --arg up_tag "$up_tag" \
    --arg repo "${UPSTREAM_OWNER}/${UPSTREAM_REPO}" --arg date "$up_date" \
    --arg links "$links" --arg lsio_changes "$lsio_changes" --argjson color "$DISCORD_COLOR" '
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

resolve_auto_provider() {
  local lsio_repo upstream source repo

  if lsio_repo="$(extract_lsio_repo_from_image "$IMAGE" 2>/dev/null)"; then
    set_lsio_repo "$lsio_repo"
    upstream="$(lookup_upstream "${LSIO_OWNER}/${LSIO_REPO}" || true)"
    if [[ -z "$upstream" ]]; then
      if [[ -n "$ADMIN_WEBHOOK" ]]; then
        local payload
        payload="$(jq -n --arg content "Missing upstream mapping for \`${LSIO_OWNER}/${LSIO_REPO}\`. Add \`${LSIO_OWNER}/${LSIO_REPO}: Owner/Repo\` to \`${UPSTREAM_MAP}\`." '{content:$content, allowed_mentions:{parse:[]}}')"
        WEBHOOK="$ADMIN_WEBHOOK" send_or_print_payload "$payload" || err "WARN: admin webhook send failed"
      fi
      return 2
    fi
    set_upstream_repo "$upstream"
    PROVIDER="lsio"
    return 0
  fi

  if repo="$(extract_ghcr_repo "${image_name:-$IMAGE}" 2>/dev/null || true)" && [[ -n "$repo" ]]; then
    set_upstream_repo "$repo"
    [[ -z "$TAG_OVERRIDE" ]] && TAG_OVERRIDE="${update_kind_remote_value:-${result_tag:-}}"
    PROVIDER="github"
    return 0
  fi

  source="$(docker image inspect "$IMAGE" --format '{{ index .Config.Labels "org.opencontainers.image.source" }}' 2>/dev/null || true)"
  if repo="$(extract_github_source_repo "$source" 2>/dev/null || true)" && [[ -n "$repo" ]]; then
    set_upstream_repo "$repo"
    PROVIDER="github"
    return 0
  fi

  return 1
}

case "$PROVIDER" in
  github|generic)
    PROVIDER="github"
    ;;
  lsio)
    ;;
  auto|"")
    if ! resolve_auto_provider; then
      rc=$?
      if (( rc == 2 )); then
        exit 0
      fi
      post_minimal_notice
      exit $?
    fi
    ;;
  *)
    err "Unknown provider: $PROVIDER"
    usage >&2
    exit 2
    ;;
esac

case "$PROVIDER" in
  github)
    [[ -n "$UPSTREAM_OWNER" && -n "$UPSTREAM_REPO" ]] || {
      err "Missing GitHub repository; pass --repo Owner/Repo"
      exit 2
    }
    run_github
    ;;
  lsio)
    [[ -n "$LSIO_OWNER" && -n "$LSIO_REPO" ]] || {
      err "Missing LSIO repository; pass --lsio linuxserver/docker-name"
      exit 2
    }
    [[ -n "$UPSTREAM_OWNER" && -n "$UPSTREAM_REPO" ]] || {
      err "Missing upstream repository; pass --upstream Owner/Repo"
      exit 2
    }
    run_lsio
    ;;
esac

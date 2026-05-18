#!/usr/bin/env bash
set -Eeuo pipefail

# Logging/pipe robustness in containerized environments
# - Ignore SIGPIPE (reader closed): don't die mid-run
# - Never let a logging printf abort the script (|| :)
trap '' PIPE
# ---------- config ----------
RELEASE_EMBED="${RELEASE_EMBED:-/wud/github-release-embed.sh}"
UPSTREAM_MAP="${UPSTREAM_MAP:-/wud/upstreams.txt}"   # lines: linuxserver/docker-xyz: Owner/Repo
LOG_DIR="${LOG_DIR:-/out}"
LOG_FILE="${LOG_DIR}/tag-manager.$(date +%Y%m%d).log"
: "${DISCORD_WEBHOOK:=}"           # normal release embeds
ADMIN_WEBHOOK="${ADMIN_WEBHOOK:-$DISCORD_WEBHOOK}"  # missing-mapping alerts (falls back to DISCORD_WEBHOOK)

# ---------- logging ----------
mkdir -p "$LOG_DIR"
timestamp() { date -Iseconds; }
log() { echo "$(timestamp) $*" | tee -a "$LOG_FILE" >&2; }
die() { log "ERROR: $*"; exit 1; }
trap 'rc=$?; log "EXIT rc=${rc}"; exit $rc' EXIT

# redact webhook when echoing commands
redact() {
  sed -E 's#(--webhook +)[^ ]+#\1<redacted>#g'
}

dump_env_subset() {
  log "---- WUD ENV (subset) ----"
  # image facts
  printf 'image_name=%s\n' "${image_name:-}"        | tee -a "$LOG_FILE" >&2
  printf 'image_registry_url=%s\n' "${image_registry_url:-}" | tee -a "$LOG_FILE" >&2
  printf 'update_available=%s\n' "${update_available:-}" | tee -a "$LOG_FILE" >&2
  printf 'update_kind_kind=%s\n' "${update_kind_kind:-}" | tee -a "$LOG_FILE" >&2
  printf 'update_kind_remote_value=%s\n' "${update_kind_remote_value:-}" | tee -a "$LOG_FILE" >&2
  printf 'result_tag=%s\n' "${result_tag:-}"        | tee -a "$LOG_FILE" >&2
  printf 'DISCORD_WEBHOOK=%s\n' "$([ -n "${DISCORD_WEBHOOK}" ] && echo "<set>" || echo "<empty>")" | tee -a "$LOG_FILE" >&2
  log "--------------------------"
}

send_discord() {
  local url="$1" msg="$2"
  [[ -n "$url" ]] || return 0
  local payload
  payload="$(jq -n --arg content "$msg" '{content:$content, allowed_mentions:{parse:[]}}')"
  curl -fsSL -H 'Content-Type: application/json' -X POST -d "$payload" "$url"
}

lookup_upstream() {
  local key="$1"
  [[ -r "$UPSTREAM_MAP" ]] || return 1
  awk -v k="$key" -F: '
    $0 ~ /^[[:space:]]*#/ {next}
    NF>=2 {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $1)
      if ($1==k) {
        sub(/^[[:space:]]+/, "", $2)
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2)
        print $2
        exit 0
      }
    }' "$UPSTREAM_MAP"
}

# redact only the webhook value when we print commands
_redact_cmd_for_log() {
  # joins args safely and redacts the token after --webhook
  local out=()
  local redact_next=0
  for a in "$@"; do
    if (( redact_next )); then
      out+=("<redacted>")
      redact_next=0
      continue
    fi
    if [[ "$a" == "--webhook" ]]; then
      out+=("$a")
      redact_next=1
      continue
    fi
    out+=("$a")
  done
  printf '%q ' "${out[@]}"
}

# make pipes resilient and still get producer's exit code
run_logged() {
  local cmd=( "$@" )

  # print the exact command (with webhook redacted)
  local printable
  printable=$(_redact_cmd_for_log "${cmd[@]}")
  log "+ ${printable% }"

  # remember current pipefail state and disable it for this pipeline
  local _had_pipefail=0
  if [[ "$(set -o | awk '/pipefail/ {print $2}')" == "on" ]]; then
    _had_pipefail=1
    set +o pipefail
  fi

  # ignore SIGPIPE to avoid killing the script if a reader disappears
  trap 'log "WARN: SIGPIPE caught (downstream closed) — continuing"' SIGPIPE

  # prefer line-buffered output if stdbuf exists
  if command -v stdbuf >/dev/null 2>&1; then
    "${cmd[@]}" 2>&1 | stdbuf -oL -eL tee -a "$LOG_FILE" || true
  else
    "${cmd[@]}" 2>&1 | tee -a "$LOG_FILE" || true
  fi

  # capture producer's exit code even with a pipeline
  local rc=${PIPESTATUS[0]}

  # restore previous pipefail behavior
  if (( _had_pipefail )); then
    set -o pipefail
  fi

  # restore default SIGPIPE behavior for the rest of the script
  trap - SIGPIPE

  log "cmd rc=${rc}"
  return "$rc"
}


# ---------- start ----------
dump_env_subset

# basic guards
[[ -x "$RELEASE_EMBED" ]] || die "github-release-embed.sh not found or not executable at $RELEASE_EMBED"
[[ "${update_available:-false}" == "true" ]] || { log "No update_available=true; exiting."; exit 0; }

# inputs from WUD
image_name="${image_name:-}"
image_registry_url="${image_registry_url:-}"
update_kind_kind="${update_kind_kind:-}"
update_kind_remote_value="${update_kind_remote_value:-}"
result_tag="${result_tag:-}"

# decide mode and build command
if [[ "$image_name" == linuxserver/* ]]; then
  # -------- LSIO mode --------
  base="${image_name#linuxserver/}"
  if [[ "$base" != docker-* ]]; then
    lsio_repo="linuxserver/docker-$base"
  else
    lsio_repo="linuxserver/$base"
  fi

  upstream_repo="$(lookup_upstream "$lsio_repo" || true)"
  if [[ -z "$upstream_repo" ]]; then
    msg="⚠️ Missing upstream mapping for \`$lsio_repo\`. Please add a line:
\`$lsio_repo: Owner/Repo\` in \`$UPSTREAM_MAP\`."
    log "$msg"
    send_discord "$ADMIN_WEBHOOK" "$msg" || log "WARN: admin webhook send failed"
    log "Skipping embed call due to missing upstream."
    exit 0
  fi

  args=( "$RELEASE_EMBED" --provider lsio --lsio "$lsio_repo" --upstream "$upstream_repo" --debug )
  [[ -n "$DISCORD_WEBHOOK" ]] && args+=( --webhook "$DISCORD_WEBHOOK" )

  run_logged "${args[@]}"

elif [[ "$image_registry_url" == *ghcr.io* ]]; then
  # -------- Generic GHCR mode --------
  upstream="$image_name"   # owner/repo
  args=( "$RELEASE_EMBED" --provider github --repo "$upstream" --debug)
  if [[ "$update_kind_kind" == "tag" && -n "$update_kind_remote_value" ]]; then
    args+=( --tag "$update_kind_remote_value" )
  elif [[ -n "$result_tag" ]]; then
    args+=( --tag "$result_tag" )
  fi
  [[ -n "$DISCORD_WEBHOOK" ]] && args+=( --webhook "$DISCORD_WEBHOOK" )

  run_logged "${args[@]}"

else
  log "Non-LSIO and non-GHCR image ($image_name @ $image_registry_url); skipping."
fi

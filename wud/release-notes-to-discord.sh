#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE="${1:?usage: release-notes-to-discord.sh <image> [container_name] [current_tag]}"
CONTAINER_NAME="${2:-}"
CURRENT_TAG="${3:-}"
WEBHOOK="${DISCORD_RELEASES_WEBHOOK:?set DISCORD_RELEASES_WEBHOOK env}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
RELEASE_EMBED="${SCRIPT_DIR}/github-release-embed.sh"

/usr/bin/which jq >/dev/null 2>&1 || { echo "jq required in host env"; exit 1; }
[[ -x "$RELEASE_EMBED" ]] || { echo "github-release-embed.sh not found or not executable at $RELEASE_EMBED"; exit 1; }

# Try to discover the source repo from the OCI label.
SRC="$(docker image inspect "$IMAGE" --format '{{ index .Config.Labels "org.opencontainers.image.source" }}' 2>/dev/null || true)"

# Fallback for common LinuxServer.io naming.
if [[ -z "$SRC" && "$IMAGE" =~ ^linuxserver/([^:@]+) ]]; then
  SRC="https://github.com/linuxserver/docker-${BASH_REMATCH[1]}"
fi

if [[ -z "$SRC" || "$SRC" != *"github.com"* ]]; then
  TITLE="Update available: ${IMAGE}"
  DESC="No GitHub source label found. Unable to fetch release notes."
  curl -sS -H "Content-Type: application/json" -d "$(jq -n --arg t "$TITLE" --arg d "$DESC" \
    '{allowed_mentions:{parse:[]},embeds:[{title:$t,description:$d}] }')" "$WEBHOOK" >/dev/null
  exit 0
fi

ORG="$(sed -E 's#.*github\.com[:/]+([^/]+)/.*#\1#' <<<"$SRC")"
REPO="$(sed -E 's#.*github\.com[:/]+[^/]+/([^/.]+).*#\1#' <<<"$SRC")"

args=( "$RELEASE_EMBED" --provider github --repo "${ORG}/${REPO}" --webhook "$WEBHOOK" --image "$IMAGE" )
[[ -n "$CONTAINER_NAME" ]] && args+=( --container "$CONTAINER_NAME" )
[[ -n "$CURRENT_TAG" ]] && args+=( --current-tag "$CURRENT_TAG" )

"${args[@]}"

#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:?usage: release-notes-to-discord.sh <image> [container_name] [current_tag]}"
CONTAINER_NAME="${2:-}"
CURRENT_TAG="${3:-}"
WEBHOOK="${DISCORD_RELEASES_WEBHOOK:?set DISCORD_RELEASES_WEBHOOK env}"

/usr/bin/which jq >/dev/null 2>&1 || { echo "jq required in host env"; exit 1; }

# 1) Try to discover the source repo from the OCI label
SRC="$(docker image inspect "$IMAGE" --format '{{ index .Config.Labels "org.opencontainers.image.source" }}' 2>/dev/null || true)"

# Fallback for common LinuxServer.io naming
if [[ -z "$SRC" && "$IMAGE" =~ ^linuxserver/([^:@]+) ]]; then
  SRC="https://github.com/linuxserver/docker-${BASH_REMATCH[1]}"
fi

if [[ -z "$SRC" || "$SRC" != *"github.com"* ]]; then
  # Nothing we can do; just post a minimal notice with a link to Docker Hub page
  TITLE="Update available: ${IMAGE}"
  DESC="No GitHub source label found. Unable to fetch release notes."
  curl -sS -H "Content-Type: application/json" -d "$(jq -n --arg t "$TITLE" --arg d "$DESC" \
    '{embeds:[{title:$t,description:$d}] }')" "$WEBHOOK" >/dev/null
  exit 0
fi

ORG="$(sed -E 's#.*github\.com[:/]+([^/]+)/.*#\1#' <<<"$SRC")"
REPO="$(sed -E 's#.*github\.com[:/]+[^/]+/([^/.]+).*#\1#' <<<"$SRC")"

# 2) Query GitHub latest release (unauthenticated is fine for public repos)
JSON="$(curl -sSL -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${ORG}/${REPO}/releases/latest")"

# Some repos don’t use GitHub Releases; bail to the generic releases page.
if jq -e '.message=="Not Found"' >/dev/null 2>&1 <<<"$JSON"; then
  TITLE="Update available: ${IMAGE}"
  URL="https://github.com/${ORG}/${REPO}/releases"
  DESC="This repo does not publish GitHub Releases. See $URL"
  curl -sS -H "Content-Type: application/json" -d "$(jq -n --arg t "$TITLE" --arg d "$DESC" --arg u "$URL" \
    '{embeds:[{title:$t,description:$d,url:$u}] }')" "$WEBHOOK" >/dev/null
  exit 0
fi

TAG="$(jq -r '.tag_name // ""' <<<"$JSON")"
URL="$(jq -r '.html_url // ""' <<<"$JSON")"
BODY="$(jq -r '.body // ""' <<<"$JSON")"

# 3) Heuristic breaking-change detector
BREAKING="no"
grep -Eiq '(breaking|⚠|migration|incompatible|manual step|major change|requires [^ ]+ \d|deprecated[^.]*remov|remove[ds] feature)' <<<"$BODY" && BREAKING="yes"

# Optional: semver major bump vs current tag if provided
if [[ -n "$CURRENT_TAG" && "$CURRENT_TAG" =~ ^v?([0-9]+)\.([0-9]+)\.([0-9]+) && "$TAG" =~ ^v?([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
  cur_major="${BASH_REMATCH[1]}"; new_major="$(sed -E 's/^v?([0-9]+).*/\1/' <<<"$TAG")"
  if (( new_major > cur_major )); then BREAKING="yes"; fi
fi

# Trim notes for Discord (keep first ~20 lines)
EXCERPT="$(awk 'NR<=20{print} NR==21{print "... (truncated)"}' <<<"$BODY")"

# 4) Build a Discord embed
TITLE="Release ${TAG:-"(no tag)"} for ${ORG}/${REPO}"
DESCRIPTION="${EXCERPT:-No release notes body found.}"
COLOR=$([[ "$BREAKING" == "yes" ]] && echo 13632027 || echo 5793266)  # red-ish / green-ish

# Optional footer details
FOOTER="image=${IMAGE}"
[[ -n "$CONTAINER_NAME" ]] && FOOTER="${FOOTER} • container=${CONTAINER_NAME}"

PAYLOAD="$(jq -n \
  --arg title "$TITLE" \
  --arg url "$URL" \
  --arg desc "$DESCRIPTION" \
  --arg breaking "$BREAKING" \
  --arg image "$IMAGE" \
  --arg tag "$TAG" \
  --arg footer "$FOOTER" \
  --arg cont "$CONTAINER_NAME" \
  --arg cur "$CURRENT_TAG" \
  --arg src "$SRC" \
  --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --argjson color "$COLOR" \
'{
  username: "Release Notes",
  embeds: [{
    title: $title,
    url: $url,
    description: $desc,
    color: $color,
    timestamp: $timestamp,
    fields: [
      {name:"Breaking", value:$breaking, inline:true},
      {name:"Image", value:$image, inline:true},
      {name:"Current→New", value:(if (($cur|length)>0 and ($tag|length)>0) then ($cur + " → " + $tag) else ($tag) end), inline:true},
      {name:"Source", value:$src, inline:false}
    ],
    footer: { text: $footer }
  }]
}')"

curl -sS -H "Content-Type: application/json" -d "$PAYLOAD" "$WEBHOOK" >/dev/null

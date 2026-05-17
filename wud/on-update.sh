#!/bin/sh
set -eu

# WUD envs available here:
#   update_available, image_name, image_tag_value, name

# 1) Keep your existing behavior: append to file
/wud/append-updates.sh || true

# 2) Only post rich notes when an update is actually available
if [ "${update_available:-}" = "true" ]; then
  # Build a fully-qualified reference if possible
  IMG="${image_name:-}"
  if [ -n "${image_tag_value:-}" ]; then
    IMG="${IMG}:${image_tag_value}"
  fi

  # container name (may be empty if unknown)
  CNAME="${name:-}"

  # Optional: pass CURRENT_TAG if you track it; otherwise just echo the tag WUD saw
  CUR="${image_tag_value:-}"

  /wud/release-notes-to-discord.sh "$IMG" "$CNAME" "$CUR" || true
fi

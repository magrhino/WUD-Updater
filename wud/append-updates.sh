#!/bin/sh
# Append containers/images that HAVE an update to a file (dedupes per image name).
# WUD provides env vars like: update_available, image_name, name, etc.

OUT_FILE="${WUD_OUT_FILE:-/out/images.todo}"
TMP="${OUT_FILE}.tmp"

normalize_sha256() {
  digest="$1"
  [ -n "$digest" ] || return 1

  case "$digest" in
    *@sha256:*) digest="${digest##*@}" ;;
    sha256:*) ;;
    *) digest="sha256:${digest}" ;;
  esac

  printf '%s' "$digest" | grep -Eq '^sha256:[0-9a-fA-F]{64}$' || return 1
  printf '%s' "$digest"
}

# Only act when there is an update (true)
if [ "${update_available:-}" = "true" ]; then
  mkdir -p "$(dirname "$OUT_FILE")"

  # Prefer fully-qualified image+tag if available; else fall back to container name
  IMAGE="${image_name:-}${image_tag_value:+:${image_tag_value}}"
  [ -n "$IMAGE" ] || IMAGE="${name:-}"
  [ -n "$IMAGE" ] || exit 0

  SHA256=""
  if [ -n "${result_digest:-}" ]; then
    SHA256="$(normalize_sha256 "$result_digest" || true)"
  fi
  if [ -z "$SHA256" ] && [ "${update_kind_kind:-}" = "digest" ]; then
    SHA256="$(normalize_sha256 "${update_kind_remote_value:-}" || true)"
  fi

  # Include a digest only when WUD provides a real registry digest.
  LINE="${IMAGE}"
  if [ -n "$SHA256" ]; then
    LINE="${LINE} sha256=${SHA256}"
  fi

  umask 077
  touch "$OUT_FILE"

  # Remove existing lines for this image, with or without a digest suffix.
  awk -v image="$IMAGE" 'NF == 0 || $1 != image' "$OUT_FILE" > "$TMP"

  # Append the updated line
  echo "$LINE" >> "$TMP"

  # Sort and deduplicate (optional if images are already unique)
  sort -u "$TMP" > "$OUT_FILE"

  # Set ownership
  chown 1000:1000 "$OUT_FILE" 2>/dev/null || true
fi

exit 0

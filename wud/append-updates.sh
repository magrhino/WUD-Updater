#!/bin/sh
# Append containers/images that HAVE an update to a file (dedupes per image name).
# WUD provides env vars like: update_available, image_name, name, etc.

OUT_FILE="${WUD_OUT_FILE:-/out/images.todo}"
LOCK_TIMEOUT="${WUD_LOCK_TIMEOUT:-30}"
LOCK_DIR="${OUT_FILE}.lock"
LOCK_HELD=0
TMP=""
SORTED_TMP=""
rc=0

# shellcheck disable=SC2329
cleanup() {
  [ -n "$TMP" ] && rm -f "$TMP"
  [ -n "$SORTED_TMP" ] && rm -f "$SORTED_TMP"
  if [ "$LOCK_HELD" = "1" ]; then
    rmdir "$LOCK_DIR" 2>/dev/null || true
  fi
}
trap 'rc=$?; cleanup; exit "$rc"' 0
trap 'exit 1' 1 2 15

acquire_lock() {
  waited=0

  case "$LOCK_TIMEOUT" in
    ''|*[!0-9]*)
      echo "WUD_LOCK_TIMEOUT must be an integer number of seconds" >&2
      return 1
      ;;
  esac

  while ! mkdir "$LOCK_DIR" 2>/dev/null; do
    if [ "$waited" -ge "$LOCK_TIMEOUT" ]; then
      echo "Timed out waiting for WUD file lock: $LOCK_DIR" >&2
      return 1
    fi
    sleep 1
    waited=$((waited + 1))
  done

  LOCK_HELD=1
}

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
  OUT_DIR="$(dirname "$OUT_FILE")"
  OUT_BASE="$(basename "$OUT_FILE")"
  mkdir -p "$OUT_DIR"

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
  acquire_lock || exit $?
  touch "$OUT_FILE"
  TMP="$(mktemp "${OUT_DIR}/.${OUT_BASE}.left.XXXXXX")"
  SORTED_TMP="$(mktemp "${OUT_DIR}/.${OUT_BASE}.sorted.XXXXXX")"

  # Remove existing lines for this image, with or without a digest suffix.
  awk -v image="$IMAGE" 'NF == 0 || $1 != image' "$OUT_FILE" > "$TMP"

  # Append the updated line
  echo "$LINE" >> "$TMP"

  # Sort and deduplicate (optional if images are already unique)
  sort -u "$TMP" > "$SORTED_TMP"
  mv "$SORTED_TMP" "$OUT_FILE"
  SORTED_TMP=""

  # Set ownership
  chown 1000:1000 "$OUT_FILE" 2>/dev/null || true
fi

exit 0

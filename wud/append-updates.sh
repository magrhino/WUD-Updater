#!/bin/sh
# Append containers/images that HAVE an update to a file (dedupes per image name).
# WUD provides env vars like: update_available, image_name, name, etc.

OUT_FILE="${WUD_OUT_FILE:-/out/images.todo}"
LOCK_TIMEOUT="${WUD_LOCK_TIMEOUT:-30}"
LOCK_DIR="${OUT_FILE}.lock"
LOCK_HELD=0
TMP=""
SORTED_TMP=""
OUT_UID="${OUT_UID:-}"
OUT_GID="${OUT_GID:-}"
OUT_GUID="${OUT_GUID:-}"
rc=0

# shellcheck disable=SC2317,SC2329
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
    if [ -e "$LOCK_DIR" ] && [ ! -d "$LOCK_DIR" ]; then
      echo "Failed to create WUD file lock: $LOCK_DIR (permissions or missing parent?)" >&2
      return 1
    fi
    LOCK_PARENT="$(dirname "$LOCK_DIR")"
    if [ ! -e "$LOCK_DIR" ] && { [ ! -d "$LOCK_PARENT" ] || [ ! -w "$LOCK_PARENT" ]; }; then
      echo "Failed to create WUD file lock: $LOCK_DIR (permissions or missing parent?)" >&2
      return 1
    fi

    if [ "$waited" -ge "$LOCK_TIMEOUT" ]; then
      echo "Timed out waiting for WUD file lock: $LOCK_DIR" >&2
      return 1
    fi
    sleep 1
    waited=$((waited + 1))
  done

  LOCK_HELD=1
}

stat_mode() {
  if stat -c '%a' "$1" >/dev/null 2>&1; then
    stat -c '%a' "$1"
  else
    stat -f '%Lp' "$1"
  fi
}

stat_uid() {
  if stat -c '%u' "$1" >/dev/null 2>&1; then
    stat -c '%u' "$1"
  else
    stat -f '%u' "$1"
  fi
}

stat_gid() {
  if stat -c '%g' "$1" >/dev/null 2>&1; then
    stat -c '%g' "$1"
  else
    stat -f '%g' "$1"
  fi
}

validate_owner_config() {
  if [ -z "$OUT_GID" ] && [ -n "$OUT_GUID" ]; then
    OUT_GID="$OUT_GUID"
  fi

  if [ -n "$OUT_UID" ] || [ -n "$OUT_GID" ]; then
    if [ -z "$OUT_UID" ] || [ -z "$OUT_GID" ]; then
      echo "OUT_UID and OUT_GID/OUT_GUID must be set together" >&2
      return 1
    fi
    case "$OUT_UID" in
      *[!0-9]*)
        echo "OUT_UID must be numeric" >&2
        return 1
        ;;
    esac
    case "$OUT_GID" in
      *[!0-9]*)
        echo "OUT_GID/OUT_GUID must be numeric" >&2
        return 1
        ;;
    esac
  fi
}

desired_metadata() {
  if [ -e "$OUT_FILE" ]; then
    FILE_MODE="$(stat_mode "$OUT_FILE")" || return 1
    FILE_UID="$(stat_uid "$OUT_FILE")" || return 1
    FILE_GID="$(stat_gid "$OUT_FILE")" || return 1
  else
    FILE_MODE="660"
    FILE_UID="$(id -u)"
    FILE_GID="$(id -g)"
    if [ "$FILE_UID" = "0" ]; then
      FILE_UID="1000"
      FILE_GID="1000"
    fi
  fi

  if [ -n "$OUT_UID" ]; then
    FILE_UID="$OUT_UID"
    FILE_GID="$OUT_GID"
  fi
}

apply_metadata() {
  file="$1"
  actual_uid="$(stat_uid "$file")" || return 1
  actual_gid="$(stat_gid "$file")" || return 1

  if [ "$actual_uid" != "$FILE_UID" ] || [ "$actual_gid" != "$FILE_GID" ]; then
    if ! chown "${FILE_UID}:${FILE_GID}" "$file"; then
      echo "Failed to set owner ${FILE_UID}:${FILE_GID} on $file" >&2
      return 1
    fi
  fi
  if ! chmod "$FILE_MODE" "$file"; then
    echo "Failed to set mode $FILE_MODE on $file" >&2
    return 1
  fi

  actual_uid="$(stat_uid "$file")" || return 1
  actual_gid="$(stat_gid "$file")" || return 1
  actual_mode="$(stat_mode "$file")" || return 1
  if [ "$actual_uid" != "$FILE_UID" ] || [ "$actual_gid" != "$FILE_GID" ] || [ "$actual_mode" != "$FILE_MODE" ]; then
    echo "Metadata verification failed for $file: wanted ${FILE_MODE} ${FILE_UID}:${FILE_GID}, got ${actual_mode} ${actual_uid}:${actual_gid}" >&2
    return 1
  fi
}

tag_from_remote() {
  tag="$1"
  [ -n "$tag" ] || return 1

  tag="${tag%%@sha256:*}"
  case "$tag" in
    *:*)
      tag="${tag##*:}"
      ;;
  esac

  case "$tag" in
    ''|*[!A-Za-z0-9_.-]*|[!A-Za-z0-9_]*)
      return 1
      ;;
  esac

  printf '%s' "$tag"
}

digest_from_remote() {
  digest="$1"
  [ -n "$digest" ] || return 1

  case "$digest" in
    *@sha256:*)
      digest="sha256:${digest##*@sha256:}"
      ;;
    sha256:*)
      ;;
    *)
      return 1
      ;;
  esac

  hex="${digest#sha256:}"
  [ "${#hex}" -eq 64 ] || return 1
  case "$hex" in
    *[!0-9A-Fa-f]*)
      return 1
      ;;
  esac

  printf 'sha256:%s' "$hex"
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

  LINE="${IMAGE}"
  if [ "${update_kind_kind:-}" = "tag" ]; then
    REMOTE_TAG_SOURCE="${update_kind_remote_value:-}"
    [ -n "$REMOTE_TAG_SOURCE" ] || REMOTE_TAG_SOURCE="${result_tag:-}"
    if REMOTE_TAG="$(tag_from_remote "$REMOTE_TAG_SOURCE")"; then
      LINE="${IMAGE} tag=${REMOTE_TAG}"
    fi
  elif [ "${update_kind_kind:-}" = "digest" ]; then
    REMOTE_DIGEST_SOURCE="${update_kind_remote_value:-}"
    if REMOTE_DIGEST="$(digest_from_remote "$REMOTE_DIGEST_SOURCE")"; then
      LINE="${IMAGE}@${REMOTE_DIGEST}"
    fi
  fi

  umask 077
  acquire_lock || exit $?
  validate_owner_config || exit $?
  desired_metadata || {
    echo "Failed to read desired metadata for $OUT_FILE" >&2
    exit 1
  }
  TMP="$(mktemp "${OUT_DIR}/.${OUT_BASE}.left.XXXXXX")"
  SORTED_TMP="$(mktemp "${OUT_DIR}/.${OUT_BASE}.sorted.XXXXXX")"

  # Remove existing lines for this image, with or without a digest suffix.
  if [ -e "$OUT_FILE" ]; then
    if ! awk -v image="$IMAGE" '
      function target_key(value) {
        sub(/@sha256:[^[:space:]]+$/, "", value)
        return value
      }
      NF == 0 || target_key($1) != image
    ' "$OUT_FILE" > "$TMP"; then
      echo "Failed to filter existing entries in $OUT_FILE" >&2
      exit 1
    fi
  else
    if ! : > "$TMP"; then
      echo "Failed to initialize temporary file for $OUT_FILE" >&2
      exit 1
    fi
  fi

  # Append the updated line
  if ! printf '%s\n' "$LINE" >> "$TMP"; then
    echo "Failed to append update entry for $IMAGE" >&2
    exit 1
  fi

  # Sort and deduplicate (optional if images are already unique)
  if ! sort -u "$TMP" > "$SORTED_TMP"; then
    echo "Failed to sort update entries for $OUT_FILE" >&2
    exit 1
  fi
  apply_metadata "$SORTED_TMP" || exit $?
  if ! mv "$SORTED_TMP" "$OUT_FILE"; then
    echo "Failed to replace $OUT_FILE" >&2
    exit 1
  fi
  SORTED_TMP=""
fi

exit 0

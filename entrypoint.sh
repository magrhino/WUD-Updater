#!/usr/bin/env bash
set -Eeuo pipefail

app_dir="${WUD_APP_DIR:-/app}"
docker_base="${DOCKER_BASE:-/host/docker}"
wud_out_file="${WUD_OUT_FILE:-/out/images.todo}"
wud_log_dir="${WUD_LOG_DIR:-/logs}"
wud_scripts_dir="${WUD_SCRIPTS_DIR-/managed-wud}"
wud_scripts_marker=".wud-updater-managed"

has_arg(){
  local wanted="$1" arg
  shift
  for arg in "$@"; do
    case "$arg" in
      "$wanted"|"$wanted"=*)
        return 0
        ;;
    esac
  done
  return 1
}

normalize_absolute_path(){
  local path="$1" part
  local -a parts normalized

  IFS='/' read -r -a parts <<< "$path"
  normalized=()
  for part in "${parts[@]}"; do
    case "$part" in
      ""|".")
        ;;
      "..")
        if ((${#normalized[@]} > 0)); then
          normalized=("${normalized[@]:0:$((${#normalized[@]} - 1))}")
        fi
        ;;
      *)
        normalized+=("$part")
        ;;
    esac
  done

  if ((${#normalized[@]} == 0)); then
    printf '/\n'
    return
  fi
  local IFS=/
  printf '/%s\n' "${normalized[*]}"
}

canonicalize_dir_target(){
  local path="$1" probe suffix base canon

  [[ -n "$path" ]] || return 1
  case "$path" in
    /*) ;;
    *) path="$PWD/$path" ;;
  esac
  while [[ "$path" != "/" && "$path" == */ ]]; do
    path="${path%/}"
  done

  probe="$path"
  suffix=""
  while [[ ! -e "$probe" ]]; do
    base="${probe##*/}"
    [[ -n "$base" && "$probe" != "/" ]] || return 1
    suffix="/$base$suffix"
    probe="${probe%/*}"
    [[ -n "$probe" ]] || probe="/"
  done
  [[ -d "$probe" ]] || return 1

  canon="$(cd "$probe" && pwd -P)" || return 1
  normalize_absolute_path "$canon$suffix"
}

path_is_or_under(){
  local path="$1" parent="$2"

  [[ -n "$parent" ]] || return 1
  [[ "$path" == "$parent" || "$path" == "$parent"/* ]]
}

dirname_path(){
  local path="$1" parent

  if [[ "$path" == */* ]]; then
    parent="${path%/*}"
    [[ -n "$parent" ]] || parent="/"
    printf '%s\n' "$parent"
    return
  fi
  printf '.\n'
}

refuse_unsafe_wud_scripts_dir(){
  printf 'Refusing unsafe WUD_SCRIPTS_DIR: %s\n' "${wud_scripts_dir:-<empty>}" >&2
}

sync_wud_scripts(){
  local src="$app_dir/wud"
  local dst="$wud_scripts_dir"
  local dst_canon app_canon docker_base_canon out_dir_canon out_dir marker

  if [[ -z "$dst" ]]; then
    refuse_unsafe_wud_scripts_dir
    return 1
  fi
  if [[ ! -d "$src" ]]; then
    printf 'Packaged WUD scripts directory not found: %s\n' "$src" >&2
    return 1
  fi

  dst_canon="$(canonicalize_dir_target "$dst")" || {
    printf 'Unable to resolve WUD_SCRIPTS_DIR: %s\n' "$dst" >&2
    return 1
  }
  app_canon="$(canonicalize_dir_target "$app_dir")" || {
    printf 'Unable to resolve WUD_APP_DIR: %s\n' "$app_dir" >&2
    return 1
  }
  docker_base_canon="$(canonicalize_dir_target "$docker_base")" || {
    printf 'Unable to resolve DOCKER_BASE: %s\n' "$docker_base" >&2
    return 1
  }
  out_dir="$(dirname_path "$wud_out_file")"
  out_dir_canon="$(canonicalize_dir_target "$out_dir")" || {
    printf 'Unable to resolve WUD_OUT_FILE directory: %s\n' "$out_dir" >&2
    return 1
  }

  if [[ "$dst_canon" == "/" ]] ||
    path_is_or_under "$dst_canon" "$app_canon" ||
    path_is_or_under "$dst_canon" "$docker_base_canon" ||
    path_is_or_under "$dst_canon" "$out_dir_canon"; then
    refuse_unsafe_wud_scripts_dir
    return 1
  fi

  mkdir -p "$dst_canon"
  marker="$dst_canon/$wud_scripts_marker"
  if [[ ! -e "$marker" ]] &&
    [[ -n "$(find "$dst_canon" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    printf 'Refusing to sync into non-empty unmanaged WUD_SCRIPTS_DIR: %s\n' "$wud_scripts_dir" >&2
    printf 'Use an empty managed directory or remove/relocate existing contents first.\n' >&2
    return 1
  fi

  find "$dst_canon" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  cp -R "$src"/. "$dst_canon"/
  find "$dst_canon" -type f -name '*.sh' -exec chmod +x {} +
  : > "$marker"
  printf 'Synced WUD scripts to %s\n' "$dst"
}

if [[ "$#" -eq 0 ]]; then
  set -- updates --dry-run
elif [[ "$1" == -* ]]; then
  set -- updates "$@"
fi

if [[ "${WUD_SYNC_SCRIPTS:-}" == "1" && "$1" != "sync-wud-scripts" ]]; then
  sync_wud_scripts
fi

case "$1" in
  sync-wud-scripts)
    sync_wud_scripts
    ;;
  updates)
    shift
    exec "$app_dir/bin/updates" "$@"
    ;;
  truenas-status-export)
    shift
    if [[ -n "${PYTHONPATH:-}" ]]; then
      export PYTHONPATH="$app_dir/src:$PYTHONPATH"
    else
      export PYTHONPATH="$app_dir/src"
    fi
    exec "${PYTHON_BIN:-python3}" -m wud_updater.cli truenas-status-export "$@"
    ;;
  docker-update-from-wud)
    shift
    updater_args=()
    has_arg --base "$@" || updater_args+=(--base "$docker_base")
    has_arg --file "$@" || updater_args+=(--file "$wud_out_file")
    has_arg --log-dir "$@" || updater_args+=(--log-dir "$wud_log_dir")
    exec "$app_dir/bin/docker-update-from-wud" "${updater_args[@]}" "$@"
    ;;
  *)
    exec "$@"
    ;;
esac

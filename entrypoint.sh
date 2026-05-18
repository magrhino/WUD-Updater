#!/usr/bin/env bash
set -Eeuo pipefail

app_dir="${WUD_APP_DIR:-/app}"
docker_base="${DOCKER_BASE:-/host/docker}"
wud_out_file="${WUD_OUT_FILE:-/out/images.todo}"
wud_scripts_dir="${WUD_SCRIPTS_DIR-/managed-wud}"

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

sync_wud_scripts(){
  local src="$app_dir/wud"
  local dst="$wud_scripts_dir"

  if [[ -z "$dst" || "$dst" == "/" || "$dst" == "$app_dir" || "$dst" == "$app_dir/"* ]]; then
    printf 'Refusing unsafe WUD_SCRIPTS_DIR: %s\n' "${dst:-<empty>}" >&2
    return 1
  fi
  if [[ ! -d "$src" ]]; then
    printf 'Packaged WUD scripts directory not found: %s\n' "$src" >&2
    return 1
  fi

  mkdir -p "$dst"
  find "$dst" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  cp -R "$src"/. "$dst"/
  find "$dst" -type f -name '*.sh' -exec chmod +x {} +
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
  docker-update-from-wud|docker-update-from-wud-legacy)
    updater_cmd="$1"
    shift
    if has_arg --base "$@"; then
      if has_arg --file "$@"; then
        exec "$app_dir/bin/$updater_cmd" "$@"
      fi
      exec "$app_dir/bin/$updater_cmd" --file "$wud_out_file" "$@"
    fi
    if has_arg --file "$@"; then
      exec "$app_dir/bin/$updater_cmd" --base "$docker_base" "$@"
    fi
    exec "$app_dir/bin/$updater_cmd" --base "$docker_base" --file "$wud_out_file" "$@"
    ;;
  *)
    exec "$@"
    ;;
esac

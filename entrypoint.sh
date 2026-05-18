#!/usr/bin/env bash
set -Eeuo pipefail

app_dir="${WUD_APP_DIR:-/app}"
docker_base="${DOCKER_BASE:-/host/docker}"
wud_out_file="${WUD_OUT_FILE:-/out/images.todo}"

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

if [[ "$#" -eq 0 ]]; then
  set -- updates --dry-run
elif [[ "$1" == -* ]]; then
  set -- updates "$@"
fi

case "$1" in
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

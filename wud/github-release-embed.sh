#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
RELEASE_NOTES="${SCRIPT_DIR}/release-notes-to-discord.sh"

usage() {
  cat <<'EOF'
usage:
  github-release-embed.sh --repo Owner/Repo [--tag TAG|latest] [--webhook URL]
  github-release-embed.sh --provider lsio --lsio linuxserver/docker-name --upstream Owner/Repo [--tag TAG|latest] [--webhook URL]

compatibility options:
  --provider github|generic|lsio
  --repo Owner/Repo
  --upstream Owner/Repo
  --lsio Owner/Repo
  --tag TAG|latest
  --current-tag TAG
  --image IMAGE
  --container NAME
  --webhook URL
  --max-commits N
  --color VALUE
  --debug
EOF
}

[[ -x "$RELEASE_NOTES" ]] || {
  printf 'release-notes-to-discord.sh not found or not executable at %s\n' "$RELEASE_NOTES" >&2
  exit 1
}

args=()
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --provider|--repo|--upstream|--lsio|--tag|--current-tag|--image|--container|--webhook)
      [[ "$#" -ge 2 ]] || {
        printf 'missing value for %s\n' "$1" >&2
        exit 2
      }
      args+=("$1" "$2")
      shift 2
      ;;
    --max-commits|--color)
      [[ "$#" -ge 2 ]] || {
        printf 'missing value for %s\n' "$1" >&2
        exit 2
      }
      args+=("$1" "$2")
      shift 2
      ;;
    --debug)
      args+=("$1")
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown arg: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

exec "$RELEASE_NOTES" "${args[@]}"

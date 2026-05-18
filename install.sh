#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
bin_dir="${BIN_DIR:-$HOME/bin}"
docker_base="${DOCKER_BASE:-$HOME/docker}"
wud_scripts_link="${WUD_SCRIPTS_LINK:-$docker_base/wud/scripts}"
wud_out_dir="${WUD_OUT_DIR:-$docker_base/wud/out}"

link_one() {
  local src="$1"
  local dst="$2"

  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    echo "Refusing to replace existing non-symlink: $dst" >&2
    echo "Move it aside or set a different target before rerunning install.sh." >&2
    return 1
  fi

  ln -sfn "$src" "$dst"
  echo "$dst -> $src"
}

mkdir -p "$bin_dir" "$(dirname "$wud_scripts_link")" "$wud_out_dir"

chmod +x "$repo_dir/bin/updates" "$repo_dir/bin/docker-update-from-wud" "$repo_dir/bin/docker-update-from-wud-legacy"
find "$repo_dir/wud" -type f -name '*.sh' -exec chmod +x {} \;

link_one "$repo_dir/bin/updates" "$bin_dir/updates"
link_one "$repo_dir/bin/docker-update-from-wud" "$bin_dir/docker-update-from-wud"
link_one "$repo_dir/bin/docker-update-from-wud-legacy" "$bin_dir/docker-update-from-wud-legacy"
link_one "$repo_dir/wud" "$wud_scripts_link"

cat <<EOF

Installed WUD-Updater.

Add this to your shell startup if needed:
  export PATH="\$HOME/bin:\$PATH"

Mount this path into the WUD container:
  $wud_scripts_link:/wud:ro

Keep WUD output mounted at:
  $wud_out_dir:/out
EOF

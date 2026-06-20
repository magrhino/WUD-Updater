#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
bin_dir="${BIN_DIR:-$HOME/bin}"
docker_base="${DOCKER_BASE:-$HOME/docker}"
wud_scripts_link="${WUD_SCRIPTS_LINK:-$docker_base/wud/scripts}"
wud_out_dir="${WUD_OUT_DIR:-$docker_base/wud/out}"
python_bin="${PYTHON_BIN:-python3}"
venv_dir="${WUDUP_VENV:-${WUD_UPDATER_VENV:-$repo_dir/.venv}}"
venv_python="$venv_dir/bin/python"

python_has_runtime_deps() {
  "$1" - >/dev/null 2>&1 <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(1)
import rich
import ruamel.yaml
PY
}

python_has_runtime_version() {
  "$1" - >/dev/null 2>&1 <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

ensure_python_runtime_deps() {
  if python_has_runtime_deps "$python_bin"; then
    echo "Python runtime dependencies already available in: $python_bin"
    return 0
  fi

  if [[ -x "$venv_python" ]] && python_has_runtime_deps "$venv_python"; then
    echo "Python runtime dependencies already available in: $venv_dir"
    return 0
  fi

  if ! command -v "$python_bin" >/dev/null 2>&1; then
    echo "Python interpreter not found: $python_bin" >&2
    echo "Install Python 3.10+ or set PYTHON_BIN before rerunning install.sh." >&2
    return 1
  fi
  if ! python_has_runtime_version "$python_bin"; then
    echo "Python 3.10 or newer is required: $python_bin" >&2
    echo "Install Python 3.10+ or set PYTHON_BIN before rerunning install.sh." >&2
    return 1
  fi

  echo "Installing Python runtime dependencies into: $venv_dir"
  "$python_bin" -m venv "$venv_dir"
  "$venv_python" -m pip install -e "$repo_dir"

  if ! python_has_runtime_deps "$venv_python"; then
    echo "Installed venv is missing required Python dependencies: $venv_dir" >&2
    return 1
  fi
}

link_one() {
  local src="$1"
  local dst="$2"

  if [[ -e "$dst" && ! -L "$dst" ]]; then
    echo "Refusing to replace existing non-symlink: $dst" >&2
    echo "Move it aside or set a different target before rerunning install.sh." >&2
    return 1
  fi

  ln -sfn "$src" "$dst"
  echo "$dst -> $src"
}

mkdir -p "$bin_dir" "$(dirname "$wud_scripts_link")" "$wud_out_dir"

ensure_python_runtime_deps

chmod +x "$repo_dir/bin/updates" "$repo_dir/bin/docker-update-from-wud"
find "$repo_dir/wud" -type f -name '*.sh' -exec chmod +x {} +

link_one "$repo_dir/bin/updates" "$bin_dir/updates"
link_one "$repo_dir/bin/docker-update-from-wud" "$bin_dir/docker-update-from-wud"
link_one "$repo_dir/wud" "$wud_scripts_link"

cat <<EOF

Installed WUDup.

Add this to your shell startup if needed:
  export PATH="\$HOME/bin:\$PATH"

Python dependencies:
  If your host Python does not provide the required runtime packages, this
  installer creates $venv_dir. The installed command wrappers automatically use
  that venv when PYTHON_BIN is unset and host python3 is missing dependencies.

Mount this path into the WUD container:
  $wud_scripts_link:/wud:ro

Keep WUD output mounted at:
  $wud_out_dir:/out
EOF

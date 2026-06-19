#!/usr/bin/env python3
"""Create disposable local demo state for WebUI development."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from wud_updater.web_demo_fixtures import seed_demo_state  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT / "local-dev",
        help="demo state directory, default: local-dev",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    paths = seed_demo_state(args.root)
    if not args.quiet:
        print("Created WebUI demo state:")
        print(f"  DOCKER_BASE={paths['docker_base']}")
        print(f"  FAKE_DOCKER_ROOT={paths['fake_docker_root']}")
        print(f"  WUD_OUT_FILE={paths['wud_file']}")
        print(f"  WUD_LOG_DIR={paths['log_dir']}")
        print(f"  WUD_DB_PATH={paths['db_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

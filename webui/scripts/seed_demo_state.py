#!/usr/bin/env python3
"""Create disposable local demo state for WebUI development."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from wudup.web_demo_fixtures import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

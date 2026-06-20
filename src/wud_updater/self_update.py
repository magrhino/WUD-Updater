"""Compatibility entrypoint for ``python -m wud_updater.self_update``."""

from __future__ import annotations

from wudup.self_update import *  # noqa: F401,F403
from wudup.self_update import main


if __name__ == "__main__":
    raise SystemExit(main())

"""Compatibility entrypoint for ``python -m wud_updater.cli``."""

from __future__ import annotations

from wudup.cli import *  # noqa: F401,F403
from wudup.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

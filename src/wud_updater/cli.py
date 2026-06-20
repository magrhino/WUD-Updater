"""Compatibility entrypoint for ``python -m wud_updater.cli``."""

from __future__ import annotations

from typing import Any

from wudup import cli as _cli

__all__ = tuple(name for name in dir(_cli) if not name.startswith("_"))
globals().update({name: getattr(_cli, name) for name in __all__})
main = _cli.main


def __getattr__(name: str) -> Any:
    return getattr(_cli, name)


if __name__ == "__main__":
    raise SystemExit(main())

"""Compatibility entrypoint for ``python -m wud_updater.self_update``."""

from __future__ import annotations

from typing import Any

from wudup import self_update as _self_update

__all__ = tuple(name for name in dir(_self_update) if not name.startswith("_"))
globals().update({name: getattr(_self_update, name) for name in __all__})
main = _self_update.main


def __getattr__(name: str) -> Any:
    return getattr(_self_update, name)


if __name__ == "__main__":
    raise SystemExit(main())

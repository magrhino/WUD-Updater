"""Compatibility package for the renamed :mod:`wudup` package."""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
from types import ModuleType
from typing import Any

_CANONICAL_PACKAGE = "wudup"
_LEGACY_PACKAGE = __name__

_canonical = importlib.import_module(_CANONICAL_PACKAGE)
__version__ = getattr(_canonical, "__version__", "")
# Mirror canonical exports dynamically so legacy imports stay in sync.
__all__ = getattr(_canonical, "__all__", ())


class _LegacyAliasLoader(importlib.abc.Loader):
    def __init__(self, legacy_name: str) -> None:
        self.legacy_name = legacy_name
        self.canonical_name = _CANONICAL_PACKAGE + legacy_name[len(_LEGACY_PACKAGE) :]

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        module = importlib.import_module(self.canonical_name)
        sys.modules[self.legacy_name] = module
        return module

    def exec_module(self, module: ModuleType) -> None:
        return None


class _LegacyAliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self,
        fullname: str,
        path: object | None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if not fullname.startswith(f"{_LEGACY_PACKAGE}."):
            return None
        if fullname in {f"{_LEGACY_PACKAGE}.cli", f"{_LEGACY_PACKAGE}.self_update"}:
            return None
        canonical_name = _CANONICAL_PACKAGE + fullname[len(_LEGACY_PACKAGE) :]
        canonical_spec = importlib.util.find_spec(canonical_name)
        if canonical_spec is None:
            return None
        return importlib.machinery.ModuleSpec(
            fullname,
            _LegacyAliasLoader(fullname),
            origin=canonical_spec.origin,
            is_package=canonical_spec.submodule_search_locations is not None,
        )


def _install_alias_finder() -> None:
    if not any(isinstance(finder, _LegacyAliasFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _LegacyAliasFinder())


def __getattr__(name: str) -> Any:
    return getattr(_canonical, name)


_install_alias_finder()

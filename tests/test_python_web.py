from __future__ import annotations

from wud_updater import web as web_module
from wud_updater import web_compat
from wud_updater import web_models
from wud_updater.web import PASSWORD_HASHER


def test_web_module_reexports_web_models_for_compatibility() -> None:
    missing = [name for name in web_models.__all__ if not hasattr(web_module, name)]

    assert missing == []


def test_web_module_resolves_legacy_compat_exports() -> None:
    missing = [
        name for name in web_compat.LEGACY_EXPORT_NAMES if not hasattr(web_module, name)
    ]
    mismatched = [
        name
        for name in web_compat.LEGACY_EXPORT_NAMES
        if getattr(web_module, name) is not web_compat.resolve_legacy_export(name)
    ]

    assert missing == []
    assert mismatched == []


def test_web_module_dir_includes_legacy_compat_exports() -> None:
    visible_names = set(dir(web_module))
    missing = [
        name for name in web_compat.LEGACY_EXPORT_NAMES if name not in visible_names
    ]

    assert missing == []


def test_web_module_direct_import_resolves_legacy_compat_export() -> None:
    assert PASSWORD_HASHER is web_compat.resolve_legacy_export("PASSWORD_HASHER")

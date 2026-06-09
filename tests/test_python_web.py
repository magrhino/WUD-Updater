from __future__ import annotations

from wud_updater import web as web_module
from wud_updater import web_models


def test_web_module_reexports_web_models_for_compatibility() -> None:
    missing = [name for name in web_models.__all__ if not hasattr(web_module, name)]

    assert missing == []

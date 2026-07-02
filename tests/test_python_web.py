from __future__ import annotations

from wudup import web as web_module


def test_web_module_keeps_current_public_entrypoints() -> None:
    for name in (
        "DEFAULT_WEB_PORT",
        "create_app",
        "load_web_settings",
        "run_web_from_namespace",
        "run_web_reset_admin_from_namespace",
        "api_status",
    ):
        assert hasattr(web_module, name)


def test_web_module_does_not_expose_legacy_exports() -> None:
    assert not hasattr(web_module, "PASSWORD_HASHER")

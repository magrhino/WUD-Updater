from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
from wud_updater import web as web_module
from tests.web_test_helpers import (
    _web_env,
)


def test_web_startup_rejects_bind_host_missing_from_allowed_hosts(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    for key, value in _web_env(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true"},
    ).items():
        monkeypatch.setenv(key, value)

    status = web_module.run_web_from_namespace(
        SimpleNamespace(
            base=None,
            file=None,
            log_dir=None,
            db_path=None,
            host="192.0.2.10",
            port=None,
            static_dir=None,
        )
    )
    stderr = capsys.readouterr().err

    assert status == 1
    assert "WUD_WEB_ALLOWED_HOSTS must include 192.0.2.10" in stderr

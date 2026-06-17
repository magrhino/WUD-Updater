from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace

import uvicorn

from wud_updater import web as web_module
from tests.web_test_helpers import (
    _client,
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
    assert "WUD_WEB_PUBLIC_ORIGIN" in stderr
    assert "WUD_WEB_ALLOWED_HOSTS" in stderr


def test_web_startup_prints_first_run_summary(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    secret = "github-token-secret"
    for key, value in _web_env(
        tmp_path,
        {
            "GITHUB_TOKEN": secret,
            "WUD_SCRIPT_SYNC_STATUS": "auto-detected",
        },
    ).items():
        monkeypatch.setenv(key, value)
    uvicorn_calls = []
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda app, host, port: uvicorn_calls.append((app, host, port)),
    )

    status = web_module.run_web_from_namespace(
        SimpleNamespace(
            base=None,
            file=None,
            log_dir=None,
            db_path=None,
            host="0.0.0.0",
            port=12735,
            static_dir=None,
        )
    )
    stderr = capsys.readouterr().err

    assert status == 0
    assert uvicorn_calls
    assert "WUD-Updater WebUI startup summary" in stderr
    assert "Setup link: http://127.0.0.1:12735/#/setup?claim=" in stderr
    assert f"Docker base: {tmp_path / 'docker'}" in stderr
    assert f"WUD output: {tmp_path / 'state' / 'images.todo'}" in stderr
    assert "Script sync: auto-detected writable /managed-wud" in stderr
    assert "Doctor: docker compose exec wud-updater doctor" in stderr
    assert secret not in stderr


def test_web_startup_summary_uses_public_origin_when_setup_not_required(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    for key, value in _web_env(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_PUBLIC_ORIGIN": "https://wud.example.test",
            "WUD_SCRIPT_SYNC_STATUS": "auto-not-detected",
        },
    ).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port: None)

    status = web_module.run_web_from_namespace(
        SimpleNamespace(
            base=None,
            file=None,
            log_dir=None,
            db_path=None,
            host="0.0.0.0",
            port=12735,
            static_dir=None,
        )
    )
    stderr = capsys.readouterr().err

    assert status == 0
    assert "Web URL: https://wud.example.test/" in stderr
    assert "Setup link:" not in stderr
    assert "Script sync: auto mode did not detect writable /managed-wud" in stderr


def test_static_spa_mount_serves_index_when_configured(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html><div>spa</div>")
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_STATIC_DIR": str(static_dir),
        },
    )

    response = client.get("/")

    assert response.status_code == 200
    assert "spa" in response.text

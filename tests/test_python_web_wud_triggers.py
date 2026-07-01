from __future__ import annotations

from pathlib import Path

import pytest

from wudup import web_pending_sources
from wudup.config import ConfigError
from wudup.web import load_web_settings

from tests.web_test_helpers import (
    _client,
    _install_wud_api,
    _web_env,
    _wud_api_container,
)

_TRIGGER_PATH = "/api/v1/wud/triggers/update"
_TOKEN = "trigger-secret"
_TRIGGER_ENV = {
    "WUD_WEB_MUTATIONS_ENABLED": "true",
    "WUD_RELEASE_NOTES_ENABLED": "true",
    "WUDUP_TRIGGER_TOKEN": _TOKEN,
    "DISCORD_WEBHOOK": "https://discord.test/webhook-secret",
}


def _auth_headers(token: str = _TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_wud_update_trigger_requires_configured_token(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        _TRIGGER_PATH,
        json={"updateAvailable": True},
        headers=_auth_headers(),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "WUD trigger token is not configured"


def test_wud_update_trigger_rejects_token_env_and_file(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "trigger-token"
    token_file.write_text("file-secret", encoding="utf-8")
    client = _client(
        tmp_path,
        {
            "WUDUP_TRIGGER_TOKEN": _TOKEN,
            "WUDUP_TRIGGER_TOKEN_FILE": str(token_file),
        },
    )

    response = client.post(
        _TRIGGER_PATH,
        json={"updateAvailable": True},
        headers=_auth_headers(),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "WUD trigger token is misconfigured"


def test_wud_update_trigger_rejects_missing_token_file(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        {"WUDUP_TRIGGER_TOKEN_FILE": str(tmp_path / "missing-trigger-token")},
    )

    response = client.post(
        _TRIGGER_PATH,
        json={"updateAvailable": True},
        headers=_auth_headers(),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "WUD trigger token file could not be read"


def test_wud_update_trigger_rejects_empty_token_file(tmp_path: Path) -> None:
    token_file = tmp_path / "trigger-token"
    token_file.write_text("", encoding="utf-8")
    client = _client(tmp_path, {"WUDUP_TRIGGER_TOKEN_FILE": str(token_file)})

    response = client.post(
        _TRIGGER_PATH,
        json={"updateAvailable": True},
        headers=_auth_headers(),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "WUD trigger token file is empty"


def test_wud_update_trigger_rejects_wrong_token(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUDUP_TRIGGER_TOKEN": _TOKEN})

    response = client.post(
        _TRIGGER_PATH,
        json={"updateAvailable": True},
        headers=_auth_headers("wrong"),
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_wud_update_trigger_skips_release_notification_delivery(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUDUP_TRIGGER_TOKEN": _TOKEN})

    response = client.post(
        _TRIGGER_PATH,
        json={"updateAvailable": True},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "status": "skipped",
        "reason": "trigger-based release notifications are not enabled",
        "line_numbers": [],
        "release_notifications": None,
    }


def test_wud_update_trigger_accepts_token_file_noop(tmp_path: Path) -> None:
    token_file = tmp_path / "trigger-token"
    token_file.write_text(f"{_TOKEN}\n", encoding="utf-8")
    client = _client(tmp_path, {"WUDUP_TRIGGER_TOKEN_FILE": str(token_file)})

    response = client.post(
        _TRIGGER_PATH,
        json={"updateAvailable": False},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "status": "skipped",
        "reason": "updateAvailable is not true",
        "line_numbers": [],
        "release_notifications": None,
    }


def test_wud_update_trigger_requires_true_update_available(tmp_path: Path) -> None:
    client = _client(tmp_path, _TRIGGER_ENV)

    response = client.post(
        _TRIGGER_PATH,
        json={"id": "docker.local.app"},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "skipped"
    assert response.json()["reason"] == "updateAvailable is not true"


def test_legacy_disabled_forces_api_pending_source_without_wud_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, containers=[_wud_api_container(name="app")])

    def fail_file_read(_path: Path):
        raise AssertionError("legacy-disabled WebUI should not read images.todo")

    monkeypatch.setattr(web_pending_sources, "_read_pending_file", fail_file_read)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUDUP_LEGACY_SCRIPTS": "FALSE",
            "WUD_PENDING_SOURCE": "file",
        },
    )

    response = client.get("/api/v1/pending")
    body = response.json()

    assert response.status_code == 200
    assert body["source"]["configured"] == "api"
    assert body["source"]["active"] == "api"
    assert body["count"] == 1


def test_legacy_scripts_rejects_invalid_bool(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="WUDUP_LEGACY_SCRIPTS"):
        load_web_settings(
            environ=_web_env(
                tmp_path,
                {"WUDUP_LEGACY_SCRIPTS": "treu"},
            ),
        )

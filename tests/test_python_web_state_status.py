from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from wudup.web import create_app


from tests.web_test_helpers import (
    _client,
    _fake_docker_calls,
    _fake_docker_env,
    _install_wud_api,
    _make_fake_stack,
    _web_env,
    _wud_api_container,
)


def test_status_reports_missing_database_without_creating_it(tmp_path: Path) -> None:
    root = tmp_path / "state"
    db_path = root / "wud.sqlite"
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_API_BASE_URL": "http://127.0.0.1:1",
            "WUD_PENDING_SOURCE": "file",
        },
        create_root=False,
    )

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    body = response.json()
    assert body["db_ready"] is False
    assert body["ok"] is False
    assert body["wud_api"]["state"] == "unavailable"
    assert body["wud_api"]["metadata_available"] is False
    assert body["warnings"] == [f"database file does not exist: {db_path}"]
    assert not root.exists()
    assert not db_path.exists()


def test_status_counts_pending_without_resolving_groups(tmp_path: Path) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_API_BASE_URL": "http://127.0.0.1:1",
            "WUD_PENDING_SOURCE": "file",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:latest\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    body = response.json()
    assert body["pending_count"] == 1
    assert body["pending_source"]["configured"] == "file"
    assert body["pending_source"]["active"] == "file"
    assert body["pending_source"]["label"] == "Pending file"
    assert body["wud_api"]["metadata_available"] is False
    assert _fake_docker_calls(fake_root) == ""


def test_pending_endpoint_defaults_to_wud_api_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, containers=[_wud_api_container(name="app")])
    client = TestClient(
        create_app(
            environ=_web_env(
                tmp_path,
                {
                    "WUD_WEB_DEV_NO_AUTH": "true",
                    "WUD_API_BASE_URL": "https://wud.default-source.test:3000",
                },
            )
        )
    )

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["source"] == {
        "configured": "api",
        "active": "api",
        "label": "WUD API",
        "fresh": True,
        "degraded": False,
        "fallback_reason": "",
        "detail": "",
    }
    assert body["items"][0]["wud_metadata"]["name"] == "app"


def test_status_reports_wud_api_metadata_for_file_pending_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, containers=[_wud_api_container(name="app")])
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_PENDING_SOURCE": "file",
            "WUD_API_BASE_URL": "https://wud.status-file-metadata.test:3000",
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:1.0\n", encoding="utf-8")

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    body = response.json()
    assert body["pending_source"]["active"] == "file"
    assert body["pending_count"] == 1
    assert body["wud_api"]["state"] == "ready"
    assert body["wud_api"]["metadata_available"] is True


def test_status_reports_current_pending_source_hash_and_wud_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, containers=[_wud_api_container(name="app")])
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_PENDING_SOURCE": "api",
            "WUD_API_BASE_URL": "https://wud.status-source.test:3000",
        },
    )

    pending = client.get("/api/v1/pending").json()
    response = client.get("/api/v1/status")

    assert response.status_code == 200
    body = response.json()
    assert body["pending_count"] == pending["count"]
    assert body["source_hash"] == pending["source_hash"]
    assert body["wud_api"]["last_checked_at"] == pending["wud_api"]["last_checked_at"]

from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from wud_updater import web_self_update as self_update_module
from wud_updater.db import (
    open_db,
)
from tests.web_test_helpers import (
    _client,
    _csrf_headers,
    _self_update_payload,
    _fake_docker_env,
    _fake_docker_calls,
)

def test_self_update_endpoint_rejects_stale_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    monkeypatch.setattr(
        self_update_module,
        "current_container_image",
        lambda _env: "ghcr.io/magrhino/wud-updater:latest",
    )
    monkeypatch.setattr(
        self_update_module,
        "_fetch_self_update_release_notes",
        lambda *_args, **_kwargs: ([], False, []),
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
            **fake_env,
        },
    )

    response = client.post(
        "/api/v1/self-update",
        json=_self_update_payload(latest_tag="v0.24.9"),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "self-update target is stale"
    assert _fake_docker_calls(fake_root) == ""


def test_self_update_endpoint_pulls_image_and_audits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    monkeypatch.setattr(
        self_update_module,
        "current_container_image",
        lambda _env: "ghcr.io/magrhino/wud-updater:latest",
    )
    monkeypatch.setattr(
        self_update_module,
        "_fetch_self_update_release_notes",
        lambda *_args, **_kwargs: ([], False, []),
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
            **fake_env,
        },
    )
    (fake_root / "containers" / "wud-updater.summary").write_text(
        "/wud-updater|running|healthy|0|0\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/self-update",
        json=_self_update_payload(),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "image_pulled"
    assert body["target_image"] == "ghcr.io/magrhino/wud-updater:latest"
    assert body["container"] == "wud-updater"
    calls = _fake_docker_calls(fake_root)
    assert "pull ghcr.io/magrhino/wud-updater:latest" in calls
    assert "restart --time 10 wud-updater" not in calls
    assert client.app.state.web_self_update_running is False

    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        row = conn.execute(
            "SELECT mode, status, finished_at, metadata_json FROM update_runs WHERE id = ?",
            (body["audit_run_id"],),
        ).fetchone()
        event = conn.execute(
            "SELECT status, metadata_json FROM update_events WHERE run_id = ?",
            (body["audit_run_id"],),
        ).fetchone()
    assert row["mode"] == "web-self-update"
    assert row["status"] == "image_pulled"
    assert row["finished_at"]
    assert event["status"] == "image_pulled"
    metadata = json.loads(row["metadata_json"])
    assert metadata["operation"] == "self_update"
    assert metadata["current_tag"] == "v0.24.2"
    assert metadata["latest_tag"] == "v0.25.0"
    assert metadata["status"] == "image_pulled"
    assert metadata["target"] == {
        "container": "wud-updater",
        "image": "ghcr.io/magrhino/wud-updater:latest",
    }


def test_self_update_endpoint_inspects_restart_container_before_pull(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    monkeypatch.setattr(
        self_update_module,
        "current_container_image",
        lambda _env: "ghcr.io/magrhino/wud-updater:latest",
    )
    monkeypatch.setattr(
        self_update_module,
        "_fetch_self_update_release_notes",
        lambda *_args, **_kwargs: ([], False, []),
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "missing-wud-updater",
            **fake_env,
        },
    )

    response = client.post(
        "/api/v1/self-update",
        json=_self_update_payload(restart_container="missing-wud-updater"),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 500
    assert response.json()["detail"].startswith("could not inspect restart container")
    calls = _fake_docker_calls(fake_root)
    assert "inspect missing-wud-updater" in calls
    assert "pull ghcr.io/magrhino/wud-updater:latest" not in calls
    assert client.app.state.web_self_update_running is False
    try:
        with open_db(tmp_path / "state" / "wud.sqlite") as conn:
            row = conn.execute(
                "SELECT id FROM update_runs WHERE mode = 'web-self-update'",
            ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table: update_runs" not in str(exc):
            raise
        row = None
    assert row is None


def test_self_update_endpoint_marks_audit_failed_when_pull_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    (fake_root / "pull_fail").write_text("pull failed\n", encoding="utf-8")
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    monkeypatch.setattr(
        self_update_module,
        "current_container_image",
        lambda _env: "ghcr.io/magrhino/wud-updater:latest",
    )
    monkeypatch.setattr(
        self_update_module,
        "_fetch_self_update_release_notes",
        lambda *_args, **_kwargs: ([], False, []),
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
            **fake_env,
        },
    )
    (fake_root / "containers" / "wud-updater.summary").write_text(
        "/wud-updater|running|healthy|0|0\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/self-update",
        json=_self_update_payload(),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 500
    assert response.json()["detail"].startswith("could not pull self-update image")
    calls = _fake_docker_calls(fake_root)
    assert "pull ghcr.io/magrhino/wud-updater:latest" in calls
    assert "restart --time 10 wud-updater" not in calls
    assert client.app.state.web_self_update_running is False

    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        row = conn.execute(
            "SELECT status, finished_at, metadata_json FROM update_runs WHERE mode = 'web-self-update'",
        ).fetchone()
    assert row["status"] == "failure"
    assert row["finished_at"]
    metadata = json.loads(row["metadata_json"])
    assert metadata["status"] == "failure"
    assert "docker pull ghcr.io/magrhino/wud-updater:latest" in metadata["error"]


def test_self_update_endpoint_rejects_active_self_update(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
            **fake_env,
        },
    )
    client.app.state.web_self_update_running = True

    response = client.post(
        "/api/v1/self-update",
        json=_self_update_payload(),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "self-update is already running"
    assert _fake_docker_calls(fake_root) == ""

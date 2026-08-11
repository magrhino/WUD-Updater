from __future__ import annotations

import json
from pathlib import Path

from tests.web_test_helpers import (
    _client,
    _csrf_headers,
    _fake_docker_calls,
    _fake_docker_env,
)

from wudup.db import (
    open_db,
)
from wudup.web_models import WebApplyJob


def test_container_restart_endpoint_enforces_auth_csrf_read_only_and_post(
    tmp_path: Path,
) -> None:
    payload = {"confirmation": "restart_container"}
    unauthenticated = _client(tmp_path, {"WUD_WEB_MUTATIONS_ENABLED": "true"})
    read_only = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_RESTART_CONTAINER": "wudup",
        },
    )
    mutating = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wudup",
        },
    )

    unauthenticated_response = unauthenticated.post(
        "/api/v1/container/restart",
        json=payload,
        headers=_csrf_headers(unauthenticated),
    )
    missing_csrf = mutating.post("/api/v1/container/restart", json=payload)
    read_only_response = read_only.post(
        "/api/v1/container/restart",
        json=payload,
        headers=_csrf_headers(read_only),
    )
    get_response = mutating.get("/api/v1/container/restart")

    assert unauthenticated_response.status_code == 403
    assert unauthenticated_response.json()["detail"] == "setup required"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "origin header is required"
    assert read_only_response.status_code == 403
    assert read_only_response.json()["detail"] == "mutations are disabled"
    assert get_response.status_code == 405


def test_container_restart_endpoint_requires_configured_target(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )

    response = client.post(
        "/api/v1/container/restart",
        json={"confirmation": "restart_container"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "container restart target is not configured"


def test_container_restart_endpoint_rejects_active_apply_job(tmp_path: Path) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wudup",
            **fake_env,
        },
    )
    client.app.state.web_apply_jobs["job-active"] = WebApplyJob(
        id="job-active",
        status="running",
        selected_line_numbers=(1,),
    )

    response = client.post(
        "/api/v1/container/restart",
        json={"confirmation": "restart_container"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "an apply job is already running"
    assert _fake_docker_calls(fake_root) == ""


def test_container_restart_endpoint_schedules_docker_restart_and_audit(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wudup",
            **fake_env,
        },
    )
    (fake_root / "containers" / "wudup.summary").write_text(
        "/wudup|running|healthy|0|0\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/container/restart",
        json={"confirmation": "restart_container"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "scheduled"
    assert body["container"] == "wudup"
    calls = _fake_docker_calls(fake_root)
    assert "inspect wudup" in calls
    assert "restart --time 10 wudup" in calls

    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        row = conn.execute(
            "SELECT mode, status, finished_at, metadata_json FROM update_runs WHERE id = ?",
            (body["audit_run_id"],),
        ).fetchone()
        event = conn.execute(
            "SELECT status, metadata_json FROM update_events WHERE run_id = ?",
            (body["audit_run_id"],),
        ).fetchone()
    assert row["mode"] == "web-container-restart"
    assert row["status"] == "success"
    assert row["finished_at"]
    assert event["status"] == "success"
    metadata = json.loads(row["metadata_json"])
    assert metadata["operation"] == "restart_container"
    assert metadata["target"] == {"container": "wudup"}
    assert metadata["status"] == "success"
    assert json.loads(event["metadata_json"]) == metadata


def test_container_restart_endpoint_marks_audit_failed_when_restart_fails(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wudup",
            **fake_env,
        },
    )
    (fake_root / "containers" / "wudup.summary").write_text(
        "/wudup|running|healthy|0|0\n",
        encoding="utf-8",
    )
    (fake_root / "restart_fail").write_text("restart failed\n", encoding="utf-8")

    response = client.post(
        "/api/v1/container/restart",
        json={"confirmation": "restart_container"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 202
    audit_run_id = response.json()["audit_run_id"]
    assert "restart --time 10 wudup" in _fake_docker_calls(fake_root)

    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        row = conn.execute(
            "SELECT status, finished_at, metadata_json FROM update_runs WHERE id = ?",
            (audit_run_id,),
        ).fetchone()
        event = conn.execute(
            "SELECT status, metadata_json FROM update_events WHERE run_id = ?",
            (audit_run_id,),
        ).fetchone()

    assert row["status"] == "failure"
    assert row["finished_at"]
    assert event["status"] == "failure"
    metadata = json.loads(row["metadata_json"])
    assert metadata["status"] == "failure"
    assert "error" in metadata
    assert json.loads(event["metadata_json"]) == metadata

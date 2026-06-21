from __future__ import annotations
import sqlite3
import stat
from pathlib import Path
from wudup import web as web_module
from wudup import web_pending as pending_module
from wudup.locks import lock_dir_for
from tests.web_test_helpers import (
    _client,
    _csrf_headers,
    _fake_docker_env,
    _make_fake_stack,
    _fake_docker_calls,
    _install_wud_api,
    _wud_api_container,
)

def test_pending_cleanup_endpoint_enforces_auth_csrf_and_read_only(
    tmp_path: Path,
) -> None:
    payload = {
        "cleanup_id": "cleanup",
        "lines": [{"line_no": 1, "raw": "repo/old:latest"}],
        "confirmation": "remove_unmatched",
    }
    unauthenticated = _client(tmp_path, {"WUD_WEB_MUTATIONS_ENABLED": "true"})
    mutating = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    read_only = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    auth_response = unauthenticated.post(
        "/api/v1/pending/cleanup",
        json=payload,
        headers=_csrf_headers(unauthenticated),
    )
    missing_csrf = mutating.post("/api/v1/pending/cleanup", json=payload)
    read_only_response = read_only.post(
        "/api/v1/pending/cleanup",
        json=payload,
        headers=_csrf_headers(read_only),
    )

    assert auth_response.status_code == 403
    assert auth_response.json()["detail"] == "setup required"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "origin header is required"
    assert read_only_response.status_code == 403
    assert read_only_response.json()["detail"] == "mutations are disabled"


def test_pending_cleanup_removes_unmatched_entries_and_records_audit(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    original = "repo/old:latest\nrepo/app:latest\n"
    wud_file.write_text(original, encoding="utf-8")
    wud_file.chmod(0o640)
    original_stat = wud_file.stat()
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1, 2]},
        headers=headers,
    ).json()
    wud_file.write_text(original + "repo/new:latest\n", encoding="utf-8")

    response = client.post(
        "/api/v1/pending/cleanup",
        json={
            "cleanup_id": plan["cleanup"]["cleanup_id"],
            "lines": [
                {
                    "line_no": plan["cleanup"]["items"][0]["line_no"],
                    "raw": plan["cleanup"]["items"][0]["raw"],
                }
            ],
            "confirmation": "remove_unmatched",
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["removed_count"] == 1
    assert body["removed"][0]["line_no"] == 1
    assert body["audit_run_id"]
    assert wud_file.read_text(encoding="utf-8") == "repo/app:latest\nrepo/new:latest\n"
    updated_stat = wud_file.stat()
    assert stat.S_IMODE(updated_stat.st_mode) == stat.S_IMODE(original_stat.st_mode)
    assert (updated_stat.st_uid, updated_stat.st_gid) == (
        original_stat.st_uid,
        original_stat.st_gid,
    )
    detail = client.get(f"/api/v1/runs/{body['audit_run_id']}").json()
    assert detail["mode"] == "web-pending-cleanup"
    assert detail["metadata"]["operation"] == "remove_unmatched_pending"
    assert detail["pending_updates"][0]["status"] == "resolved"
    assert detail["pending_updates"][0]["status_reason"] == "removed-unmatched"
    assert detail["pending_updates"][0]["line_no"] == 1
    assert detail["events"][0]["status"] == "success"
    calls = _fake_docker_calls(fake_root)
    assert " pull " not in calls
    assert " up -d " not in calls
    assert not lock_dir_for(wud_file).exists()


def test_pending_cleanup_audit_failure_does_not_remove_wud_lines(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    original = "repo/old:latest\nrepo/app:latest\n"
    wud_file.write_text(original, encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1, 2]},
        headers=headers,
    ).json()
    original_init_db = pending_module.init_db

    def failing_init_db(conn: sqlite3.Connection) -> None:
        raise pending_module.DatabaseError("audit database unavailable")

    pending_module.init_db = failing_init_db
    try:
        response = client.post(
            "/api/v1/pending/cleanup",
            json={
                "cleanup_id": plan["cleanup"]["cleanup_id"],
                "lines": [
                    {
                        "line_no": plan["cleanup"]["items"][0]["line_no"],
                        "raw": plan["cleanup"]["items"][0]["raw"],
                    }
                ],
                "confirmation": "remove_unmatched",
            },
            headers=headers,
        )
    finally:
        pending_module.init_db = original_init_db

    assert response.status_code == 500
    assert "could not record cleanup audit" in response.json()["detail"]
    assert wud_file.read_text(encoding="utf-8") == original
    assert not lock_dir_for(wud_file).exists()


def test_pending_cleanup_rejects_stale_raw_line_without_mutation(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/old:latest\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()
    wud_file.write_text("repo/changed:latest\n", encoding="utf-8")

    response = client.post(
        "/api/v1/pending/cleanup",
        json={
            "cleanup_id": plan["cleanup"]["cleanup_id"],
            "lines": [{"line_no": 1, "raw": "repo/old:latest"}],
            "confirmation": "remove_unmatched",
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "cleanup is stale"
    assert wud_file.read_text(encoding="utf-8") == "repo/changed:latest\n"


def test_pending_cleanup_rejects_now_matched_line_without_mutation(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/old:latest\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()
    _make_fake_stack(
        tmp_path,
        fake_root,
        "restored",
        [("old", "repo/old:latest", "cid-old")],
    )

    response = client.post(
        "/api/v1/pending/cleanup",
        json={
            "cleanup_id": plan["cleanup"]["cleanup_id"],
            "lines": [{"line_no": 1, "raw": "repo/old:latest"}],
            "confirmation": "remove_unmatched",
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "cleanup is stale"
    assert wud_file.read_text(encoding="utf-8") == "repo/old:latest\n"


def test_pending_cleanup_rejects_active_apply_job_without_mutation(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/old:latest\n", encoding="utf-8")
    client.app.state.web_apply_jobs["job-active"] = web_module.WebApplyJob(
        id="job-active",
        status="running",
        selected_line_numbers=(1,),
    )

    response = client.post(
        "/api/v1/pending/cleanup",
        json={
            "cleanup_id": "cleanup",
            "lines": [{"line_no": 1, "raw": "repo/old:latest"}],
            "confirmation": "remove_unmatched",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "an apply job is already running"
    assert wud_file.read_text(encoding="utf-8") == "repo/old:latest\n"


def test_pending_cleanup_rejects_noop_request(tmp_path: Path) -> None:
    fake_env, _fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/old:latest\n", encoding="utf-8")

    response = client.post(
        "/api/v1/pending/cleanup",
        json={
            "cleanup_id": "cleanup",
            "lines": [],
            "confirmation": "remove_unmatched",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 422
    assert any(
        item["loc"] == ["body", "lines"] and item["type"] == "too_short"
        for item in response.json()["detail"]
    )
    assert wud_file.read_text(encoding="utf-8") == "repo/old:latest\n"


def test_pending_cleanup_rejects_api_pending_source_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(
        monkeypatch,
        containers=[
            _wud_api_container(tag="latest", remote_tag="", update_kind="digest")
        ],
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_PENDING_SOURCE": "api",
            "WUD_API_BASE_URL": "http://wud.cleanup-api-source.test:3000",
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/file:latest\n", encoding="utf-8")

    response = client.post(
        "/api/v1/pending/cleanup",
        json={
            "cleanup_id": "cleanup",
            "lines": [{"line_no": 1, "raw": "repo/app:latest"}],
            "confirmation": "remove_unmatched",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "pending cleanup only supports WUD_OUT_FILE source"
    )
    assert wud_file.read_text(encoding="utf-8") == "repo/file:latest\n"

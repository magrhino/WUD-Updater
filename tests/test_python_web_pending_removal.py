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
    _fake_docker_calls,
    _install_wud_api,
    _wud_api_container,
)

def test_pending_removal_plan_endpoint_enforces_auth_csrf_and_previews_read_only(
    tmp_path: Path,
) -> None:
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.parent.mkdir(parents=True)
    wud_file.write_text("repo/app:latest\n", encoding="utf-8")
    payload = {"line_numbers": [1]}
    unauthenticated = _client(tmp_path)
    read_only = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    mutating = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )

    auth_response = unauthenticated.post(
        "/api/v1/pending/removal-plan",
        json=payload,
        headers=_csrf_headers(unauthenticated),
    )
    missing_csrf = mutating.post("/api/v1/pending/removal-plan", json=payload)
    read_only_response = read_only.post(
        "/api/v1/pending/removal-plan",
        json=payload,
        headers=_csrf_headers(read_only),
    )

    assert auth_response.status_code == 403
    assert auth_response.json()["detail"] == "setup required"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "origin header is required"
    assert read_only_response.status_code == 200
    assert read_only_response.json()["can_remove"] is False
    assert read_only_response.json()["lines"][0]["raw"] == "repo/app:latest"


def test_pending_removal_endpoint_enforces_auth_csrf_and_read_only(
    tmp_path: Path,
) -> None:
    payload = {
        "removal_id": "removal",
        "lines": [{"line_no": 1, "raw": "repo/app:latest"}],
        "confirmation": "remove_selected",
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
        "/api/v1/pending/removal",
        json=payload,
        headers=_csrf_headers(unauthenticated),
    )
    missing_csrf = mutating.post("/api/v1/pending/removal", json=payload)
    read_only_response = read_only.post(
        "/api/v1/pending/removal",
        json=payload,
        headers=_csrf_headers(read_only),
    )

    assert auth_response.status_code == 403
    assert auth_response.json()["detail"] == "setup required"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "origin header is required"
    assert read_only_response.status_code == 403
    assert read_only_response.json()["detail"] == "mutations are disabled"


def test_pending_removal_removes_selected_entries_and_records_audit(
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
    original = "repo/app:latest\nrepo/old:latest\n"
    wud_file.write_text(original, encoding="utf-8")
    wud_file.chmod(0o640)
    original_stat = wud_file.stat()
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/pending/removal-plan",
        json={"line_numbers": [1, 2]},
        headers=headers,
    ).json()
    wud_file.write_text(original + "repo/new:latest\n", encoding="utf-8")

    response = client.post(
        "/api/v1/pending/removal",
        json={
            "removal_id": plan["removal_id"],
            "lines": [
                {"line_no": item["line_no"], "raw": item["raw"]}
                for item in plan["lines"]
            ],
            "confirmation": "remove_selected",
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["removed_count"] == 2
    assert [item["line_no"] for item in body["removed"]] == [1, 2]
    assert [item["reason"] for item in body["removed"]] == ["selected", "selected"]
    assert wud_file.read_text(encoding="utf-8") == "repo/new:latest\n"
    updated_stat = wud_file.stat()
    assert stat.S_IMODE(updated_stat.st_mode) == stat.S_IMODE(original_stat.st_mode)
    assert (updated_stat.st_uid, updated_stat.st_gid) == (
        original_stat.st_uid,
        original_stat.st_gid,
    )
    detail = client.get(f"/api/v1/runs/{body['audit_run_id']}").json()
    assert detail["mode"] == "web-pending-removal"
    assert detail["metadata"]["operation"] == "remove_selected_pending"
    assert [item["status_reason"] for item in detail["pending_updates"]] == [
        "removed-selected",
        "removed-selected",
    ]
    calls = _fake_docker_calls(fake_root)
    assert " pull " not in calls
    assert " up -d " not in calls
    assert not lock_dir_for(wud_file).exists()


def test_pending_removal_audit_failure_does_not_remove_wud_lines(
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
    original = "repo/app:latest\n"
    wud_file.write_text(original, encoding="utf-8")
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/pending/removal-plan",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()
    original_init_db = pending_module.init_db

    def failing_init_db(conn: sqlite3.Connection) -> None:
        raise pending_module.DatabaseError("audit database unavailable")

    pending_module.init_db = failing_init_db
    try:
        response = client.post(
            "/api/v1/pending/removal",
            json={
                "removal_id": plan["removal_id"],
                "lines": [{"line_no": 1, "raw": "repo/app:latest"}],
                "confirmation": "remove_selected",
            },
            headers=headers,
        )
    finally:
        pending_module.init_db = original_init_db

    assert response.status_code == 500
    assert "could not record removal audit" in response.json()["detail"]
    assert wud_file.read_text(encoding="utf-8") == original
    assert not lock_dir_for(wud_file).exists()


def test_pending_removal_rejects_stale_raw_line_without_mutation(
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
    wud_file.write_text("repo/app:latest\n", encoding="utf-8")
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/pending/removal-plan",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()
    wud_file.write_text("repo/changed:latest\n", encoding="utf-8")

    response = client.post(
        "/api/v1/pending/removal",
        json={
            "removal_id": plan["removal_id"],
            "lines": [{"line_no": 1, "raw": "repo/app:latest"}],
            "confirmation": "remove_selected",
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "removal is stale"
    assert wud_file.read_text(encoding="utf-8") == "repo/changed:latest\n"


def test_pending_removal_rejects_missing_line_without_mutation(
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
    wud_file.write_text("repo/app:latest\nrepo/old:latest\n", encoding="utf-8")
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/pending/removal-plan",
        json={"line_numbers": [1, 2]},
        headers=headers,
    ).json()
    wud_file.write_text("repo/app:latest\n", encoding="utf-8")

    response = client.post(
        "/api/v1/pending/removal",
        json={
            "removal_id": plan["removal_id"],
            "lines": [
                {"line_no": 1, "raw": "repo/app:latest"},
                {"line_no": 2, "raw": "repo/old:latest"},
            ],
            "confirmation": "remove_selected",
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "removal is stale"
    assert wud_file.read_text(encoding="utf-8") == "repo/app:latest\n"


def test_pending_removal_rejects_active_apply_job_without_mutation(
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
    wud_file.write_text("repo/app:latest\n", encoding="utf-8")
    client.app.state.web_apply_jobs["job-active"] = web_module.WebApplyJob(
        id="job-active",
        status="running",
        selected_line_numbers=(1,),
    )

    response = client.post(
        "/api/v1/pending/removal",
        json={
            "removal_id": "removal",
            "lines": [{"line_no": 1, "raw": "repo/app:latest"}],
            "confirmation": "remove_selected",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "an apply job is already running"
    assert wud_file.read_text(encoding="utf-8") == "repo/app:latest\n"


def test_pending_removal_rejects_duplicate_and_noop_requests(
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
    wud_file.write_text("repo/app:latest\n", encoding="utf-8")
    headers = _csrf_headers(client)

    duplicate_plan = client.post(
        "/api/v1/pending/removal-plan",
        json={"line_numbers": [1, 1]},
        headers=headers,
    )
    empty_removal = client.post(
        "/api/v1/pending/removal",
        json={
            "removal_id": "removal",
            "lines": [],
            "confirmation": "remove_selected",
        },
        headers=headers,
    )
    duplicate_removal = client.post(
        "/api/v1/pending/removal",
        json={
            "removal_id": "removal",
            "lines": [
                {"line_no": 1, "raw": "repo/app:latest"},
                {"line_no": 1, "raw": "repo/app:latest"},
            ],
            "confirmation": "remove_selected",
        },
        headers=headers,
    )

    assert duplicate_plan.status_code == 422
    assert "provided more than once" in duplicate_plan.json()["detail"]
    assert empty_removal.status_code == 422
    assert any(
        item["loc"] == ["body", "lines"] and item["type"] == "too_short"
        for item in empty_removal.json()["detail"]
    )
    assert duplicate_removal.status_code == 422
    assert duplicate_removal.json()["detail"] == (
        "removal line 1 was provided more than once"
    )
    assert wud_file.read_text(encoding="utf-8") == "repo/app:latest\n"


def test_pending_removal_rejects_api_pending_source_without_mutation(
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
            "WUD_API_BASE_URL": "http://wud.removal-api-source.test:3000",
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/file:latest\n", encoding="utf-8")
    headers = _csrf_headers(client)

    plan_response = client.post(
        "/api/v1/pending/removal-plan",
        json={"line_numbers": [1]},
        headers=headers,
    )
    removal_response = client.post(
        "/api/v1/pending/removal",
        json={
            "removal_id": "removal",
            "lines": [{"line_no": 1, "raw": "repo/app:latest"}],
            "confirmation": "remove_selected",
        },
        headers=headers,
    )

    assert plan_response.status_code == 409
    assert plan_response.json()["detail"] == (
        "pending removal only supports WUD_OUT_FILE source"
    )
    assert removal_response.status_code == 409
    assert removal_response.json()["detail"] == (
        "pending removal only supports WUD_OUT_FILE source"
    )
    assert wud_file.read_text(encoding="utf-8") == "repo/file:latest\n"


def test_pending_removal_wraps_source_read_errors_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = "removal-source-secret"
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "GITHUB_TOKEN": secret,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:latest\n", encoding="utf-8")
    headers = _csrf_headers(client)

    def fail_source_read(*_args, **_kwargs):
        raise OSError(f"open failed for {wud_file} with {secret}")

    monkeypatch.setattr(
        pending_module.web_pending_sources,
        "resolve_pending_source",
        fail_source_read,
    )

    plan_response = client.post(
        "/api/v1/pending/removal-plan",
        json={"line_numbers": [1]},
        headers=headers,
    )
    removal_response = client.post(
        "/api/v1/pending/removal",
        json={
            "removal_id": "removal",
            "lines": [{"line_no": 1, "raw": "repo/app:latest"}],
            "confirmation": "remove_selected",
        },
        headers=headers,
    )

    for response in (plan_response, removal_response):
        assert response.status_code == 500
        detail = response.json()["detail"]
        assert detail.startswith("could not verify pending removal source: ")
        assert secret not in detail
        assert str(tmp_path) not in detail
        assert "<redacted>" in detail
        assert "[REDACTED_PATH]" in detail
    assert wud_file.read_text(encoding="utf-8") == "repo/app:latest\n"
    assert not lock_dir_for(wud_file).exists()

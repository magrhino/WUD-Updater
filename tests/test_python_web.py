from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from wud_updater.db import (
    connect_db,
    init_db,
    insert_pending_update,
    insert_update_event,
    insert_update_run,
)
from wud_updater.web import create_app


def _web_env(
    tmp_path: Path,
    env: dict[str, str] | None = None,
    *,
    create_root: bool = True,
) -> dict[str, str]:
    root = tmp_path / "state"
    if create_root:
        root.mkdir(exist_ok=True)
    wud_file = root / "images.todo"
    db_path = root / "wud.sqlite"
    values = {
        "HOME": str(tmp_path),
        "DOCKER_BASE": str(tmp_path / "docker"),
        "WUD_OUT_FILE": str(wud_file),
        "WUD_LOG_DIR": str(root / "logs"),
        "WUD_DB_PATH": str(db_path),
    }
    if env:
        values.update(env)
    return values


def _client(
    tmp_path: Path,
    env: dict[str, str] | None = None,
    *,
    create_root: bool = True,
) -> TestClient:
    values = _web_env(tmp_path, env, create_root=create_root)
    return TestClient(create_app(environ=values))


def _csrf_headers(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return {
        "Origin": "http://testserver",
        "x-wud-csrf-token": response.json()["csrf_token"],
    }


def _insert_run(tmp_path: Path, *, log_file: str = "") -> int:
    db_path = tmp_path / "state" / "wud.sqlite"
    with connect_db(db_path) as conn:
        init_db(conn)
        return insert_update_run(
            conn,
            started_at="2026-05-27T12:00:00+00:00",
            status="success",
            dry_run=True,
            mode="stop",
            wud_file="/out/images.todo",
            log_file=log_file,
            metadata_json='{"source":"test"}',
        )


def test_api_rejects_unauthenticated_requests_without_dev_bypass(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, {"WUD_WEB_TOKEN": "secret"})

    response = client.get("/api/v1/status")

    assert response.status_code == 401
    assert response.json()["detail"] == "authentication required"


def test_api_accepts_bearer_token(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_TOKEN": "secret"})

    response = client.get(
        "/api/v1/status",
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200
    assert response.json()["auth_required"] is True


def test_csrf_endpoint_sets_double_submit_cookie(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_TOKEN": "secret"})

    response = client.get("/api/v1/auth/csrf")

    assert response.status_code == 200
    assert response.json()["csrf_token"]
    assert client.cookies.get("wud_csrf_token") == response.json()["csrf_token"]


def test_login_sets_http_only_session_cookie(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_TOKEN": "secret"})
    headers = _csrf_headers(client)

    login_response = client.post(
        "/api/v1/auth/login",
        json={"token": "secret"},
        headers=headers,
    )
    status_response = client.get("/api/v1/status")

    assert login_response.status_code == 200
    assert login_response.json()["authenticated"] is True
    assert "wud_session=" in login_response.headers["set-cookie"]
    assert "HttpOnly" in login_response.headers["set-cookie"]
    assert status_response.status_code == 200


def test_login_rejects_wrong_token(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_TOKEN": "secret"})
    headers = _csrf_headers(client)

    response = client.post(
        "/api/v1/auth/login",
        json={"token": "wrong"},
        headers=headers,
    )

    assert response.status_code == 401
    assert client.cookies.get("wud_session") is None


def test_login_requires_csrf_origin_headers(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_TOKEN": "secret"})

    response = client.post("/api/v1/auth/login", json={"token": "secret"})

    assert response.status_code == 403
    assert response.json()["detail"] == "origin header is required"


def test_session_endpoint_reports_cookie_auth_state(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_TOKEN": "secret"})
    before = client.get("/api/v1/auth/session")
    headers = _csrf_headers(client)

    client.post("/api/v1/auth/login", json={"token": "secret"}, headers=headers)
    after = client.get("/api/v1/auth/session")

    assert before.status_code == 200
    assert before.json()["authenticated"] is False
    assert after.status_code == 200
    assert after.json()["authenticated"] is True


def test_logout_clears_session_and_csrf_cookies(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_TOKEN": "secret"})
    headers = _csrf_headers(client)
    client.post("/api/v1/auth/login", json={"token": "secret"}, headers=headers)

    response = client.post("/api/v1/auth/logout", headers=headers)
    status_response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert client.cookies.get("wud_session") is None
    assert client.cookies.get("wud_csrf_token") is None
    assert status_response.status_code == 401


def test_api_rejects_missing_token_configuration_without_dev_bypass(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    response = client.get("/api/v1/status")

    assert response.status_code == 503
    assert response.json()["detail"] == "web auth token is not configured"


def test_api_allows_dev_auth_bypass_only_when_explicitly_enabled(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["auth_required"] is False
    assert response.json()["dev_auth_bypass"] is True


def test_status_reports_missing_database_without_creating_it(tmp_path: Path) -> None:
    root = tmp_path / "state"
    db_path = root / "wud.sqlite"
    client = _client(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true"},
        create_root=False,
    )

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    body = response.json()
    assert body["db_ready"] is False
    assert body["ok"] is False
    assert body["warnings"] == [f"database file does not exist: {db_path}"]
    assert not root.exists()
    assert not db_path.exists()


def test_pending_endpoint_reads_wud_file_without_mutation(tmp_path: Path) -> None:
    wud_file = tmp_path / "state" / "images.todo"
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    original = "# ignored\nnginx:1.25 tag=1.26\nredis@sha256:abc\n"
    wud_file.write_text(original, encoding="utf-8")

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["count"] == 2
    assert body["items"][0]["image"] == "nginx:1.25"
    assert body["items"][0]["desired_tag"] == "1.26"
    assert wud_file.read_text(encoding="utf-8") == original


def test_runs_list_returns_empty_without_creating_missing_database(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    db_path = root / "wud.sqlite"
    client = _client(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true"},
        create_root=False,
    )

    response = client.get("/api/v1/runs")

    assert response.status_code == 200
    assert response.json() == []
    assert not root.exists()
    assert not db_path.exists()


def test_run_detail_returns_not_found_without_creating_missing_database(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    db_path = root / "wud.sqlite"
    client = _client(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true"},
        create_root=False,
    )

    response = client.get("/api/v1/runs/1")

    assert response.status_code == 404
    assert response.json()["detail"] == "run not found"
    assert not root.exists()
    assert not db_path.exists()


def test_runs_endpoints_read_existing_sqlite_state(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    db_path = tmp_path / "state" / "wud.sqlite"
    with connect_db(db_path) as conn:
        init_db(conn)
        run_id = insert_update_run(
            conn,
            started_at="2026-05-27T12:00:00+00:00",
            status="success",
            dry_run=True,
            mode="stop",
            wud_file="/out/images.todo",
            log_file="/logs/run.log",
            metadata_json='{"source":"test"}',
        )
        insert_pending_update(
            conn,
            run_id=run_id,
            line_no=1,
            raw="nginx:1.25",
            image="nginx:1.25",
            status="success",
        )
        insert_update_event(
            conn,
            run_id=run_id,
            service_name="web",
            image="nginx:1.25",
            status="success",
        )

    runs_response = client.get("/api/v1/runs")
    detail_response = client.get(f"/api/v1/runs/{run_id}")

    assert runs_response.status_code == 200
    assert runs_response.json()[0]["id"] == run_id
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["metadata"] == {"source": "test"}
    assert detail["pending_updates"][0]["image"] == "nginx:1.25"
    assert detail["events"][0]["service_name"] == "web"


def test_run_log_endpoint_tails_configured_log_file(tmp_path: Path) -> None:
    log_dir = tmp_path / "state" / "logs"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "run.log"
    log_file.write_text("0123456789", encoding="utf-8")
    run_id = _insert_run(tmp_path, log_file=str(log_file))
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get(f"/api/v1/runs/{run_id}/log?tail_bytes=4")

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["content"] == "6789"
    assert body["truncated"] is True
    assert body["max_bytes"] == 4


def test_run_log_endpoint_caps_tail_size(tmp_path: Path) -> None:
    log_dir = tmp_path / "state" / "logs"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "run.log"
    log_file.write_text("log", encoding="utf-8")
    run_id = _insert_run(tmp_path, log_file=str(log_file))
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get(f"/api/v1/runs/{run_id}/log?tail_bytes=9999999")

    assert response.status_code == 200
    assert response.json()["max_bytes"] == 1_048_576


def test_run_log_endpoint_reports_missing_log_file(tmp_path: Path) -> None:
    log_file = tmp_path / "state" / "logs" / "missing.log"
    run_id = _insert_run(tmp_path, log_file=str(log_file))
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get(f"/api/v1/runs/{run_id}/log")

    assert response.status_code == 200
    assert response.json()["exists"] is False
    assert response.json()["content"] == ""


def test_run_log_endpoint_rejects_logs_outside_configured_dir(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.log"
    outside.write_text("secret", encoding="utf-8")
    run_id = _insert_run(tmp_path, log_file=str(outside))
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get(f"/api/v1/runs/{run_id}/log")

    assert response.status_code == 403
    assert response.json()["detail"] == "log file is outside WUD_LOG_DIR"


def test_run_log_endpoint_returns_not_found_for_unknown_run(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get("/api/v1/runs/404/log")

    assert response.status_code == 404
    assert response.json()["detail"] == "run not found"


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


def test_csrf_origin_scaffold_rejects_unsafe_api_requests(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.post("/api/v1/runs")

    assert response.status_code == 403
    assert response.json()["detail"] == "origin header is required"

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
        root.mkdir()
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


def test_csrf_origin_scaffold_rejects_unsafe_api_requests(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.post("/api/v1/runs")

    assert response.status_code == 403
    assert response.json()["detail"] == "origin header is required"

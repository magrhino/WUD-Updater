from __future__ import annotations
import json
from pathlib import Path

from fastapi import HTTPException

from wud_updater import web_runs as runs_module
from wud_updater.db import (
    open_db,
    init_db,
    insert_pending_update,
    insert_update_event,
    insert_update_run,
)
from wud_updater.digest_provenance import DigestTagProvenance
from wud_updater.web_models import LogTail
from tests.web_test_helpers import (
    _client,
    _insert_run,
)


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


def test_runs_database_errors_are_sanitized(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = "github-secret-token"
    leaked_path = tmp_path / "state" / "wud.sqlite"
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "GITHUB_TOKEN": secret,
        },
    )

    def fail_connect(_settings: object) -> object:
        raise OSError(f"cannot open {leaked_path} with {secret}")

    monkeypatch.setattr(runs_module, "_connect_readonly_db", fail_connect)

    response = client.get("/api/v1/runs")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail.startswith("could not read database: ")
    assert str(leaked_path) not in detail
    assert secret not in detail
    assert "[REDACTED_PATH]" in detail
    assert "<redacted>" in detail


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
    with open_db(db_path) as conn:
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
        run_id_2 = insert_update_run(
            conn,
            started_at="2026-05-27T13:00:00+00:00",
            status="success",
            dry_run=False,
            mode="auto-update",
            wud_file="/out/images.todo",
            log_file="/logs/run2.log",
        )
        insert_update_event(
            conn,
            run_id=run_id_2,
            service_name="db",
            image="postgres:15",
            status="success",
        )

    runs_response = client.get("/api/v1/runs")
    detail_response = client.get(f"/api/v1/runs/{run_id}")

    assert runs_response.status_code == 200
    runs_data = runs_response.json()
    assert len(runs_data) == 2

    # Verify the batched event mapping works correctly
    run_2 = next(r for r in runs_data if r["id"] == run_id_2)
    assert run_2["events"][0]["service_name"] == "db"
    run_1 = next(r for r in runs_data if r["id"] == run_id)
    assert run_1["events"][0]["service_name"] == "web"

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["metadata"] == {"source": "test"}
    assert detail["pending_updates"][0]["image"] == "nginx:1.25"
    assert detail["events"][0]["service_name"] == "web"


def test_runs_endpoints_serialize_digest_provenance(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    db_path = tmp_path / "state" / "wud.sqlite"
    provenance = DigestTagProvenance(
        source_image="repo/app:latest",
        resolved_tag="latest",
        watch_tag="latest",
        target_digest="sha256:new",
        final_image="repo/app@sha256:new",
        provenance_source="apply",
        provenance_confidence="verified",
    )
    expected_provenance = {
        "source_image": "repo/app:latest",
        "resolved_tag": "latest",
        "watch_tag": "latest",
        "target_digest": "sha256:new",
        "final_image": "repo/app@sha256:new",
        "provenance_source": "apply",
        "provenance_confidence": "verified",
    }
    with open_db(db_path) as conn:
        init_db(conn)
        run_id = insert_update_run(
            conn,
            started_at="2026-05-27T12:00:00+00:00",
            status="success",
            dry_run=False,
            mode="apply",
            wud_file="/out/images.todo",
            log_file="/logs/run.log",
        )
        insert_pending_update(
            conn,
            run_id=run_id,
            line_no=1,
            raw="repo/app:latest@sha256:new",
            image="repo/app:latest",
            target_digest="sha256:new",
            service_key="stack/app",
            stack_name="stack",
            service_name="app",
            status="success",
            digest_provenance=provenance,
        )
        insert_update_event(
            conn,
            run_id=run_id,
            service_name="app",
            stack_name="stack",
            image="repo/app:latest",
            target_image="repo/app@sha256:new",
            new_digest="sha256:new",
            status="success",
            digest_provenance=provenance,
        )

    runs_response = client.get("/api/v1/runs")
    detail_response = client.get(f"/api/v1/runs/{run_id}")

    assert runs_response.status_code == 200
    assert detail_response.status_code == 200
    run = runs_response.json()[0]
    detail = detail_response.json()
    assert run["events"][0]["digest_provenance"] == expected_provenance
    assert detail["events"][0]["digest_provenance"] == expected_provenance
    assert detail["pending_updates"][0]["digest_provenance"] == expected_provenance


def test_runs_endpoints_sanitize_run_and_event_metadata(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    db_path = tmp_path / "state" / "wud.sqlite"
    wud_file = tmp_path / "state" / "images.todo"
    log_file = tmp_path / "state" / "logs" / "run.log"
    compose_file = tmp_path / "docker" / "media" / "compose.yml"
    with open_db(db_path) as conn:
        init_db(conn)
        run_id = insert_update_run(
            conn,
            started_at="2026-05-27T12:00:00+00:00",
            status="success",
            dry_run=False,
            mode="web-settings",
            wud_file=str(wud_file),
            log_file=str(log_file),
            metadata_json=json.dumps(
                {
                    "source": "webui",
                    "path": str(wud_file),
                    "nested": {"stack": str(compose_file.parent)},
                }
            ),
        )
        insert_pending_update(
            conn,
            run_id=run_id,
            line_no=1,
            raw="nginx:1.25",
            image="nginx:1.25",
            status="success",
            metadata_json=json.dumps(
                {
                    "log": str(log_file),
                    "target": {"compose_file": str(compose_file)},
                }
            ),
        )
        insert_update_event(
            conn,
            run_id=run_id,
            service_name="settings",
            stack_name="webui",
            image="managed-settings",
            status="success",
            metadata_json=json.dumps(
                {
                    "operation": "update_managed_settings",
                    "before": {"compose_file": str(compose_file)},
                }
            ),
        )

    runs_response = client.get("/api/v1/runs")
    detail_response = client.get(f"/api/v1/runs/{run_id}")

    assert runs_response.status_code == 200
    assert detail_response.status_code == 200
    run = runs_response.json()[0]
    detail = detail_response.json()

    for payload in (run, detail):
        assert payload["metadata"]["path"] == "<WUD_OUT_FILE>"
        assert payload["metadata"]["nested"]["stack"] == "<DOCKER_BASE>/media"
        assert (
            payload["events"][0]["metadata"]["before"]["compose_file"]
            == "<DOCKER_BASE>/media/compose.yml"
        )
    assert detail["pending_updates"][0]["metadata"]["log"] == "<WUD_LOG_DIR>/run.log"
    assert (
        detail["pending_updates"][0]["metadata"]["target"]["compose_file"]
        == "<DOCKER_BASE>/media/compose.yml"
    )


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


def test_run_log_endpoint_uses_runs_module_tail_reader_seam(
    tmp_path: Path,
    monkeypatch,
) -> None:
    log_dir = tmp_path / "state" / "logs"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "run.log"
    log_file.write_text("original", encoding="utf-8")
    run_id = _insert_run(tmp_path, log_file=str(log_file))
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    def fake_read_log_tail(
        _log_path: Path,
        _max_bytes: int,
    ) -> LogTail:
        return LogTail(
            exists=True,
            content="web tail seam used",
            truncated=False,
        )

    monkeypatch.setattr(runs_module, "_read_log_tail", fake_read_log_tail)

    response = client.get(f"/api/v1/runs/{run_id}/log?tail_bytes=4")

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["content"] == "web tail seam used"
    assert body["truncated"] is False
    assert body["max_bytes"] == 4


def test_run_log_endpoint_rejects_missing_log_file(tmp_path: Path) -> None:
    log_file = tmp_path / "state" / "logs" / "missing.log"
    run_id = _insert_run(tmp_path, log_file=str(log_file))
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get(f"/api/v1/runs/{run_id}/log")

    assert response.status_code == 404
    assert response.json()["detail"] == "log file not found"


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


def test_safe_log_path_uses_resolved_path_after_symlink_swap(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    log_dir = tmp_path / "state" / "logs"
    log_dir.mkdir(parents=True)
    allowed = log_dir / "allowed.log"
    outside = tmp_path / "outside.log"
    link = log_dir / "run.log"
    allowed.write_text("allowed", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    link.symlink_to(allowed)

    log_path = runs_module._safe_log_path(client.app.state.web_settings, "run.log")
    link.unlink()
    link.symlink_to(outside)
    tail = runs_module._read_log_tail(log_path, 1024)

    assert log_path == allowed.resolve()
    assert tail.exists is True
    assert tail.content == "allowed"


def test_read_log_tail_hides_os_error_detail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    log_path = tmp_path / "state" / "logs" / "run.log"

    def fail_is_file(_path: Path) -> bool:
        raise OSError(f"permission denied: {tmp_path / 'private.log'}")

    monkeypatch.setattr(Path, "is_file", fail_is_file)

    try:
        runs_module._read_log_tail(log_path, 1024)
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail == "could not read log file"
    else:
        raise AssertionError("expected log tail read to fail")


def test_run_log_endpoint_returns_not_found_for_unknown_run(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get("/api/v1/runs/404/log")

    assert response.status_code == 404
    assert response.json()["detail"] == "run not found"

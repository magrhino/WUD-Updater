from __future__ import annotations

import json
from pathlib import Path

from wud_updater import web_settings
from wud_updater.db import open_db

from tests.web_test_helpers import (
    _client,
    _doctor_client,
    _insert_run,
)


def test_diagnostics_support_bundle_returns_semantically_redacted_payload(
    tmp_path: Path,
) -> None:
    secret = "github-token-secret"
    client = _doctor_client(
        tmp_path,
        {
            "GITHUB_TOKEN": secret,
            "FAKE_DOCKER_INFO_SECRET": secret,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:latest\n", encoding="utf-8")
    log_file = tmp_path / "state" / "logs" / "run.log"
    log_file.write_text(
        (
            f"checking {tmp_path / 'docker' / 'app' / 'compose.yml'}\n"
            f"wud file {wud_file}\n"
            f"log file {log_file}\n"
            f"secret {secret}\n"
        ),
        encoding="utf-8",
    )
    _insert_run(tmp_path, log_file="run.log")

    response = client.get("/api/v1/diagnostics/support-bundle")
    body = response.json()
    serialized = json.dumps(body)
    doctor_codes = {check["code"] for check in body["doctor_result"]["checks"]}

    assert response.status_code == 200
    assert str(tmp_path) not in serialized
    assert secret not in serialized
    assert "<redacted>" in serialized
    assert "<DOCKER_BASE>/app/compose.yml" in serialized
    assert "<WUD_OUT_FILE>" in serialized
    assert "<WUD_LOG_DIR>/run.log" in serialized
    assert "wud-out-file" in doctor_codes
    assert "compose-discovery" in doctor_codes
    assert body["pending_summary"]["source_file"] == "<WUD_OUT_FILE>"
    assert body["log_tail"]["exists"] is True


def test_diagnostics_support_bundle_reuses_resolved_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    observed: list[bool] = []
    original_settings_response = web_settings.settings_response

    def wrapped_settings_response(settings, request):
        observed.append(settings is client.app.state.web_settings)
        return original_settings_response(settings, request)

    monkeypatch.setattr(web_settings, "settings_response", wrapped_settings_response)

    response = client.get("/api/v1/diagnostics/support-bundle")

    assert response.status_code == 200
    assert observed == [True]


def test_diagnostics_support_bundle_warns_for_log_file_outside_configured_dir(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.log"
    outside.write_text("secret", encoding="utf-8")
    _insert_run(tmp_path, log_file=str(outside))
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get("/api/v1/diagnostics/support-bundle")
    body = response.json()

    assert response.status_code == 200
    assert body["log_tail"] is None
    assert body["diagnostics_warnings"] == [
        "log tail unavailable: log file is outside WUD_LOG_DIR"
    ]

def test_diagnostics_support_bundle_reports_last_run_metadata_errors(
    tmp_path: Path,
) -> None:
    run_id = _insert_run(tmp_path, log_file="run.log")
    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        with conn:
            conn.execute(
                """
                UPDATE update_runs
                SET metadata_json = ?
                WHERE id = ?
                """,
                ("not-json", run_id),
            )
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get("/api/v1/diagnostics/support-bundle")

    assert response.status_code == 200
    body = response.json()
    assert body["last_run_status"] is None
    assert body["log_tail"] is None
    assert body["diagnostics_warnings"] == [
        "last run status unavailable: invalid metadata JSON in database"
    ]

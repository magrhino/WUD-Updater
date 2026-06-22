from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from wudup import web_settings
from wudup.db import open_db

from tests.web_test_helpers import (
    WUD_API_AUTH_CONFIG_KEY,
    WUD_API_AUTHORIZATION_HEADER,
    _client,
    _doctor_client,
    _install_wud_api,
    _insert_run,
)


def _build_support_bundle(
    tmp_path: Path,
    *,
    wud_api_base_url: str = "https://wud.support-config.test:3000",
) -> tuple[dict[str, Any], set[str], str]:
    client = _doctor_client(
        tmp_path,
        {"WUD_API_BASE_URL": wud_api_base_url},
    )

    response = client.get("/api/v1/diagnostics/support-bundle")
    body = response.json()
    serialized = json.dumps(body)
    doctor_codes = {check["code"] for check in body["doctor_result"]["checks"]}

    assert response.status_code == 200
    return body, doctor_codes, serialized


def test_diagnostics_support_bundle_returns_semantically_redacted_payload(
    tmp_path: Path,
) -> None:
    secret = "github-token-secret"
    wud_api_header_secret = "wud-api-header-secret"
    wud_api_headers_file = tmp_path / "wud-api-headers.json"
    wud_api_headers_file.write_text(
        json.dumps({"X-Api-Key": wud_api_header_secret}),
        encoding="utf-8",
    )
    client = _doctor_client(
        tmp_path,
        {
            "GITHUB_TOKEN": secret,
            "FAKE_DOCKER_INFO_SECRET": secret,
            "WUD_API_HEADERS_FILE": str(wud_api_headers_file),
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
            f"wud api header {wud_api_header_secret}\n"
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
    assert wud_api_header_secret not in serialized
    assert "<redacted>" in serialized
    assert "<DOCKER_BASE>/app/compose.yml" in serialized
    assert "<WUD_OUT_FILE>" in serialized
    assert "<WUD_LOG_DIR>/run.log" in serialized
    assert "wud-out-file" in doctor_codes
    assert "compose-discovery" in doctor_codes
    assert "wud_api_diagnostics" in body
    assert body["pending_summary"]["source_file"] == "<WUD_OUT_FILE>"
    assert body["log_tail"]["exists"] is True


def test_diagnostics_support_bundle_includes_sanitized_wud_api_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    redaction_value = "registry-redaction-value"
    _install_wud_api(
        monkeypatch,
        watchers=(
            200,
            [
                {
                    "id": "docker.local",
                    "type": "docker",
                    "name": "local",
                    "configuration": {
                        "socket": "/var/run/docker.sock",
                        "headers": {WUD_API_AUTHORIZATION_HEADER: redaction_value},
                        "cron": "0 * * * *",
                        "watchbydefault": True,
                    },
                }
            ],
        ),
        registries=(
            200,
            [
                {
                    "id": "hub.private",
                    "type": "hub",
                    "name": "private",
                    "configuration": {
                        "region": "eu-west-1",
                        WUD_API_AUTH_CONFIG_KEY: redaction_value,
                    },
                }
            ],
        ),
    )

    body, _doctor_codes, serialized = _build_support_bundle(tmp_path)
    diagnostics = body["wud_api_diagnostics"]

    assert diagnostics["app"]["name"] == "wud"
    assert diagnostics["watchers"][0]["configuration"]["socket"] == "[REDACTED_PATH]"
    assert diagnostics["watchers"][0]["configuration"]["headers"] == "<redacted>"
    assert diagnostics["registries"][0]["configuration"]["region"] == "eu-west-1"
    assert (
        diagnostics["registries"][0]["configuration"][WUD_API_AUTH_CONFIG_KEY]
        == "<redacted>"
    )
    assert redaction_value not in serialized


@pytest.mark.parametrize(
    ("health", "expected_state", "expected_available"),
    [
        ((401, {"error": "authentication required"}), "auth_required", True),
        (OSError("connection refused"), "unavailable", False),
    ],
)
def test_diagnostics_support_bundle_includes_degraded_wud_api_diagnostics(
    tmp_path: Path,
    monkeypatch,
    health,
    expected_state: str,
    expected_available: bool,
) -> None:
    _install_wud_api(monkeypatch, health=health)

    body, _doctor_codes, serialized = _build_support_bundle(
        tmp_path,
        wud_api_base_url=f"https://wud.support-{expected_state}.test:3000",
    )
    diagnostics = body["wud_api_diagnostics"]

    assert diagnostics["health"]["state"] == expected_state
    assert diagnostics["health"]["available"] is expected_available
    assert diagnostics["app"]["status"]["state"] == expected_state
    assert diagnostics["registries_status"]["state"] == expected_state
    assert isinstance(serialized, str)
    assert "wud_api_diagnostics" in serialized


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

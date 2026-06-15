from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from wud_updater import web_settings as settings_module
from wud_updater import web_state as state_module
from wud_updater.db import (
    open_db,
    init_db,
)

from tests.web_test_helpers import (
    _client,
    _fake_docker_calls,
    _fake_docker_env,
    _make_fake_stack,
    _csrf_headers,
    _setup_admin,
)


def _store_web_setting(tmp_path: Path, key: str, value: str) -> None:
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        init_db(conn)
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO web_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, "2026-06-08T00:00:00+00:00"),
            )


def test_state_read_database_errors_are_sanitized(
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

    monkeypatch.setattr(state_module, "_connect_readonly_db", fail_connect)

    response = client.get("/api/v1/service-policies")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail.startswith("could not read database: ")
    assert str(leaked_path) not in detail
    assert secret not in detail
    assert "[REDACTED_PATH]" in detail
    assert "<redacted>" in detail


def test_settings_rejects_unauthenticated_requests_without_dev_bypass(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    response = client.get("/api/v1/settings")

    assert response.status_code == 403
    assert response.json()["detail"] == "setup required"


def test_settings_reports_effective_non_secret_configuration(
    tmp_path: Path,
) -> None:
    secret_values = {
        "WUD_WEB_TOKEN": "web-token-secret",
        "GITHUB_TOKEN": "github-token-secret",
        "DISCORD_WEBHOOK": "discord-webhook-secret",
        "ADMIN_WEBHOOK": "admin-webhook-secret",
    }
    client = _client(
        tmp_path,
        {
            "DOCKER_BASE": str(tmp_path / "docker-root"),
            "HOST_DOCKER_BASE": str(tmp_path / "docker-root"),
            "WUD_OUT_FILE": str(tmp_path / "state" / "custom.todo"),
            "WUD_LOG_DIR": str(tmp_path / "state" / "custom-logs"),
            "WUD_MAX_WAIT": "240",
            "WUD_WEB_PUBLIC_ORIGIN": "https://wud.example.test",
            "WUD_WEB_ALLOWED_ORIGINS": "http://testserver",
            "WUD_WEB_ALLOWED_HOSTS": "testserver,wud.example.test,updates.example.test",
            "WUD_WEB_TRUSTED_PROXIES": "127.0.0.1/32",
            "WUD_WEB_SECURE_COOKIES": "false",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
            **secret_values,
        },
    )
    _setup_admin(client)

    response = client.get("/api/v1/settings")
    body = response.json()
    updater = {entry["name"]: entry for entry in body["updater"]}
    webui = {entry["name"]: entry for entry in body["webui"]}
    secrets = {entry["name"]: entry for entry in body["secrets"]}
    serialized = json.dumps(body)

    assert response.status_code == 200
    managed = {entry["key"]: entry for entry in body["managed"]}

    assert set(body) == {"updater", "webui", "secrets", "managed"}
    assert updater["DOCKER_BASE"]["value"] == str(tmp_path / "docker-root")
    assert updater["DOCKER_BASE"]["configured"] is True
    assert updater["DOCKER_BASE"]["source"] == "configured"
    assert updater["WUD_OUT_FILE"]["default_value"] == str(
        tmp_path / "docker-root" / "wud" / "out" / "images.todo"
    )
    assert updater["WUD_MAX_WAIT"]["value"] == "240"
    assert updater["WUD_MAX_WAIT"]["source"] == "configured"
    assert updater["WUD_LOCK_TIMEOUT"] == {
        "name": "WUD_LOCK_TIMEOUT",
        "value": "30",
        "default_value": "30",
        "configured": False,
        "source": "default",
    }
    assert webui["WUD_WEB_PUBLIC_ORIGIN"]["value"] == "https://wud.example.test"
    assert webui["WUD_WEB_MUTATIONS_ENABLED"]["value"] == "true"
    assert webui["WUD_WEB_RESTART_CONTAINER"]["value"] == "wud-updater"
    assert webui["WUD_WEB_RESTART_CONTAINER"]["source"] == "configured"
    assert webui["WUD_WEB_SECURE_COOKIES"]["value"] == "false"
    assert webui["WUD_WEB_SECURE_COOKIES_EFFECTIVE"]["value"] == "false"
    assert webui["WUD_WEB_SECURE_COOKIES_EFFECTIVE"]["source"] == "request"
    assert webui["WUD_WEB_AUTO_UPDATE_SCHEDULER_ENABLED"]["value"] == "true"
    assert secrets["WUD_WEB_TOKEN"]["configured"] is True
    assert secrets["GITHUB_TOKEN"]["configured"] is True
    assert secrets["DISCORD_RELEASES_WEBHOOK"]["configured"] is False
    assert secrets["DISCORD_WEBHOOK"]["configured"] is True
    assert secrets["ADMIN_WEBHOOK"]["configured"] is True
    assert managed["theme_preference"] == {
        "key": "theme_preference",
        "value": "system",
        "default_value": "system",
        "source": "default",
        "editable": True,
        "allowed_values": ["system", "light", "dark"],
        "restart_required": False,
        "disabled_reason": "",
    }
    assert managed["onboarding_checklist"] == {
        "key": "onboarding_checklist",
        "value": "visible",
        "default_value": "visible",
        "source": "default",
        "editable": True,
        "allowed_values": ["visible", "dismissed"],
        "restart_required": False,
        "disabled_reason": "",
    }
    assert managed["compose_ignore_paths"] == {
        "key": "compose_ignore_paths",
        "value": "old",
        "default_value": "old",
        "source": "default",
        "editable": True,
        "allowed_values": [],
        "restart_required": False,
        "disabled_reason": "",
    }
    assert managed["digest_pin_updates"] == {
        "key": "digest_pin_updates",
        "value": "false",
        "default_value": "false",
        "source": "default",
        "editable": True,
        "allowed_values": ["false", "true"],
        "restart_required": False,
        "disabled_reason": "",
    }
    for value in secret_values.values():
        assert value not in serialized


def test_settings_wraps_invalid_managed_setting_config_error(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    _store_web_setting(tmp_path, "compose.digest_pin_updates", "maybe")

    response = client.get("/api/v1/settings")
    detail = response.json()["detail"]

    assert response.status_code == 500
    assert detail.startswith("could not read managed settings: ")
    assert "true or false" in detail


def test_managed_settings_endpoint_enforces_auth_csrf_read_only_and_post(
    tmp_path: Path,
) -> None:
    payload = {"values": {"theme_preference": "dark"}}
    unauthenticated = _client(tmp_path, {"WUD_WEB_MUTATIONS_ENABLED": "true"})
    read_only = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    mutating = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )

    unauthenticated_response = unauthenticated.post(
        "/api/v1/settings/managed",
        json=payload,
        headers=_csrf_headers(unauthenticated),
    )
    missing_csrf = mutating.post("/api/v1/settings/managed", json=payload)
    read_only_response = read_only.post(
        "/api/v1/settings/managed",
        json=payload,
        headers=_csrf_headers(read_only),
    )
    get_response = mutating.get("/api/v1/settings/managed")

    assert unauthenticated_response.status_code == 403
    assert unauthenticated_response.json()["detail"] == "setup required"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "origin header is required"
    assert read_only_response.status_code == 403
    assert read_only_response.json()["detail"] == "mutations are disabled"
    assert get_response.status_code == 405


def test_managed_settings_rejects_uneditable_or_invalid_values_without_partial_write(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)

    invalid_key = client.post(
        "/api/v1/settings/managed",
        json={"values": {"theme_preference": "dark", "WUD_WEB_TOKEN": "secret"}},
        headers=headers,
    )
    path_key = client.post(
        "/api/v1/settings/managed",
        json={"values": {"DOCKER_BASE": "/srv/docker"}},
        headers=headers,
    )
    command_value = client.post(
        "/api/v1/settings/managed",
        json={"values": {"theme_preference": "dark; rm -rf /"}},
        headers=headers,
    )
    invalid_compose_ignore = client.post(
        "/api/v1/settings/managed",
        json={"values": {"compose_ignore_paths": "old,,archive"}},
        headers=headers,
    )
    empty_payload = client.post(
        "/api/v1/settings/managed",
        json={"values": {}},
        headers=headers,
    )
    settings_response = client.get("/api/v1/settings")
    managed = {entry["key"]: entry for entry in settings_response.json()["managed"]}

    assert invalid_key.status_code == 422
    assert invalid_key.json()["detail"] == "managed setting is not editable: WUD_WEB_TOKEN"
    assert path_key.status_code == 422
    assert path_key.json()["detail"] == "managed setting is not editable: DOCKER_BASE"
    assert command_value.status_code == 422
    assert command_value.json()["detail"] == (
        "theme_preference must be one of: system, light, dark"
    )
    assert invalid_compose_ignore.status_code == 422
    assert "non-empty relative paths" in invalid_compose_ignore.json()["detail"]
    assert empty_payload.status_code == 422
    assert empty_payload.json()["detail"] == "at least one managed setting is required"
    assert managed["theme_preference"]["value"] == "system"
    assert managed["theme_preference"]["source"] == "default"


def test_managed_settings_endpoint_uses_settings_module_validation_seam(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)

    def fail_validation(*_args: object, **_kwargs: object) -> dict[str, str]:
        raise HTTPException(status_code=409, detail="web validation seam used")

    monkeypatch.setattr(
        settings_module,
        "_validated_managed_setting_updates",
        fail_validation,
    )

    response = client.post(
        "/api/v1/settings/managed",
        json={"values": {"theme_preference": "dark"}},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "web validation seam used"


def test_managed_settings_update_wraps_invalid_existing_config_error(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    _store_web_setting(tmp_path, "compose.digest_pin_updates", "maybe")

    response = client.post(
        "/api/v1/settings/managed",
        json={"values": {"theme_preference": "dark"}},
        headers=_csrf_headers(client),
    )
    detail = response.json()["detail"]

    assert response.status_code == 500
    assert detail.startswith("could not read managed settings: ")
    assert "true or false" in detail


def test_effective_config_wraps_invalid_stored_compose_ignore_paths_error(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    _store_web_setting(tmp_path, "compose.ignore_paths", "old,,archive")

    try:
        settings_module._effective_config(client.app.state.web_settings)
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail.startswith("stored compose_ignore_paths is invalid: ")
        assert "non-empty relative paths" in exc.detail
    else:
        raise AssertionError("expected invalid stored compose ignore paths to fail")


def test_effective_config_wraps_invalid_stored_digest_pin_error(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    _store_web_setting(tmp_path, "compose.digest_pin_updates", "maybe")

    try:
        settings_module._effective_config(client.app.state.web_settings)
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail.startswith("stored digest_pin_updates is invalid: ")
        assert "true or false" in exc.detail
    else:
        raise AssertionError("expected invalid stored digest-pin setting to fail")


def test_managed_digest_pin_updates_env_guard_disables_webui_edit(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_DIGEST_PIN_UPDATES": "true",
        },
    )
    headers = _csrf_headers(client)

    settings_response = client.get("/api/v1/settings")
    managed = {entry["key"]: entry for entry in settings_response.json()["managed"]}
    response = client.post(
        "/api/v1/settings/managed",
        json={"values": {"digest_pin_updates": "false"}},
        headers=headers,
    )

    assert managed["digest_pin_updates"]["value"] == "true"
    assert managed["digest_pin_updates"]["editable"] is False
    assert "Unset it to manage digest-pin updates" in managed[
        "digest_pin_updates"
    ]["disabled_reason"]
    assert response.status_code == 422
    assert response.json()["detail"] == managed["digest_pin_updates"]["disabled_reason"]


def test_managed_compose_ignore_paths_env_guard_disables_webui_edit(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_COMPOSE_IGNORE_PATHS": "old",
        },
    )
    headers = _csrf_headers(client)

    settings_response = client.get("/api/v1/settings")
    managed = {entry["key"]: entry for entry in settings_response.json()["managed"]}
    response = client.post(
        "/api/v1/settings/managed",
        json={"values": {"compose_ignore_paths": "archive"}},
        headers=headers,
    )

    assert managed["compose_ignore_paths"]["value"] == "old"
    assert managed["compose_ignore_paths"]["editable"] is False
    assert "Unset it to manage compose ignore paths" in managed[
        "compose_ignore_paths"
    ]["disabled_reason"]
    assert response.status_code == 422
    assert response.json()["detail"] == managed["compose_ignore_paths"]["disabled_reason"]


def test_managed_settings_persist_and_write_audit_records(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)

    response = client.post(
        "/api/v1/settings/managed",
        json={
            "values": {
                "theme_preference": "dark",
                "onboarding_checklist": "dismissed",
                "compose_ignore_paths": "old, archive/disabled",
                "digest_pin_updates": "true",
            }
        },
        headers=headers,
    )
    body = response.json()
    managed = {entry["key"]: entry for entry in body["managed"]}

    assert response.status_code == 200
    assert body["audit_run_id"]
    assert managed["theme_preference"]["value"] == "dark"
    assert managed["theme_preference"]["source"] == "configured"
    assert managed["onboarding_checklist"]["value"] == "dismissed"
    assert managed["onboarding_checklist"]["source"] == "configured"
    assert managed["compose_ignore_paths"]["value"] == "old, archive/disabled"
    assert managed["compose_ignore_paths"]["source"] == "configured"
    assert managed["digest_pin_updates"]["value"] == "true"
    assert managed["digest_pin_updates"]["source"] == "configured"

    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        theme = conn.execute(
            "SELECT value FROM web_settings WHERE key = 'ui.theme_preference'"
        ).fetchone()
        onboarding = conn.execute(
            "SELECT value FROM web_settings WHERE key = 'onboarding_checklist_dismissed_at'"
        ).fetchone()
        compose_ignore_paths = conn.execute(
            "SELECT value FROM web_settings WHERE key = 'compose.ignore_paths'"
        ).fetchone()
        digest_pin_updates = conn.execute(
            "SELECT value FROM web_settings WHERE key = 'compose.digest_pin_updates'"
        ).fetchone()
        run = conn.execute(
            "SELECT * FROM update_runs WHERE id = ?",
            (body["audit_run_id"],),
        ).fetchone()
        event = conn.execute(
            "SELECT * FROM update_events WHERE run_id = ?",
            (body["audit_run_id"],),
        ).fetchone()

    run_metadata = json.loads(run["metadata_json"])
    event_metadata = json.loads(event["metadata_json"])
    assert theme["value"] == "dark"
    assert onboarding["value"]
    assert compose_ignore_paths["value"] == "old, archive/disabled"
    assert digest_pin_updates["value"] == "true"
    assert run["mode"] == "web-settings"
    assert run_metadata["operation"] == "update_managed_settings"
    assert run_metadata["target"] == {
        "keys": [
            "compose_ignore_paths",
            "digest_pin_updates",
            "onboarding_checklist",
            "theme_preference",
        ]
    }
    assert event_metadata["before"] == {
        "theme_preference": "system",
        "onboarding_checklist": "visible",
        "compose_ignore_paths": "old",
        "digest_pin_updates": "false",
    }
    assert event_metadata["after"] == {
        "theme_preference": "dark",
        "onboarding_checklist": "dismissed",
        "compose_ignore_paths": "old, archive/disabled",
        "digest_pin_updates": "true",
    }

    reset = client.post(
        "/api/v1/settings/managed",
        json={"values": {"onboarding_checklist": "visible"}},
        headers=headers,
    )
    reset_managed = {entry["key"]: entry for entry in reset.json()["managed"]}
    assert reset.status_code == 200
    assert reset_managed["onboarding_checklist"]["value"] == "visible"
    with open_db(db_path) as conn:
        onboarding_row = conn.execute(
            "SELECT value FROM web_settings WHERE key = 'onboarding_checklist_dismissed_at'"
        ).fetchone()
    assert onboarding_row is None


def test_state_read_endpoints_return_empty_without_creating_missing_database(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    db_path = root / "wud.sqlite"
    client = _client(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true"},
        create_root=False,
    )

    policies = client.get("/api/v1/service-policies")
    snoozes = client.get("/api/v1/snoozes?state=all")
    exclusions = client.get("/api/v1/tag-exclusions?status=all")

    assert policies.status_code == 200
    assert policies.json() == []
    assert snoozes.status_code == 200
    assert snoozes.json() == []
    assert exclusions.status_code == 200
    assert exclusions.json() == []
    assert not root.exists()
    assert not db_path.exists()


def test_state_read_endpoints_list_existing_sqlite_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "state" / "wud.sqlite"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    past = (now - timedelta(hours=1)).isoformat()
    future = (now + timedelta(hours=1)).isoformat()
    with open_db(db_path) as conn:
        init_db(conn)
        with conn:
            conn.execute(
                """
                INSERT INTO service_policy (
                    service_key,
                    update_mode,
                    auto_update,
                    snooze_default_seconds,
                    auto_update_time,
                    auto_update_days_json,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES (
                    'stack/app',
                    'stop',
                    0,
                    3600,
                    '09:30',
                    '["mon","wed"]',
                    '2026-05-28T12:00:00+00:00',
                    '2026-05-28T12:01:00+00:00',
                    '{"source":"test"}'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO snoozes (
                    service_key,
                    snoozed_until,
                    reason,
                    created_at,
                    metadata_json
                )
                VALUES ('stack/app', ?, 'maintenance', ?, '{}')
                """,
                (future, now.isoformat()),
            )
            conn.execute(
                """
                INSERT INTO snoozes (
                    service_key,
                    snoozed_until,
                    reason,
                    created_at,
                    metadata_json
                )
                VALUES ('stack/old', ?, 'expired', ?, '{}')
                """,
                (past, past),
            )
            cursor = conn.execute(
                """
                INSERT INTO update_runs (
                    started_at,
                    finished_at,
                    status,
                    dry_run,
                    mode,
                    wud_file,
                    log_file,
                    metadata_json
                )
                VALUES (?, ?, 'success', 0, 'apply', '', '', '{}')
                """,
                (now.isoformat(), now.isoformat()),
            )
            run_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO update_events (
                    run_id,
                    created_at,
                    service_name,
                    stack_name,
                    image,
                    target_image,
                    status,
                    metadata_json
                )
                VALUES (?, ?, 'db', 'stack', 'repo/db:latest', '', 'success', '{}')
                """,
                (run_id, now.isoformat()),
            )
            conn.execute(
                """
                INSERT INTO dependency_snoozes (
                    service_key,
                    wait_for_service_key,
                    reason,
                    created_at,
                    metadata_json
                )
                VALUES ('stack/worker', 'stack/cache', 'wait for cache', ?, '{}')
                """,
                (past,),
            )
            conn.execute(
                """
                INSERT INTO dependency_snoozes (
                    service_key,
                    wait_for_service_key,
                    reason,
                    created_at,
                    metadata_json
                )
                VALUES ('stack/satisfied', 'stack/db', 'wait for db', ?, '{}')
                """,
                (past,),
            )
            conn.execute(
                """
                INSERT INTO tag_exclusion_rules (
                    scope,
                    image_repo,
                    service_key,
                    match_type,
                    tag,
                    regex_fragment,
                    status,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES
                    (
                        'image_repo',
                        'repo/app',
                        '',
                        'exact',
                        '2.0',
                        '2\\.0',
                        'active',
                        ?,
                        ?,
                        '{}'
                    ),
                    (
                        'service',
                        'repo/app',
                        'stack/app',
                        'exact',
                        '3.0',
                        '3\\.0',
                        'disabled',
                        ?,
                        ?,
                        '{}'
                    )
                """,
                (now.isoformat(), now.isoformat(), now.isoformat(), now.isoformat()),
            )
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    policies = client.get("/api/v1/service-policies")
    active_snoozes = client.get("/api/v1/snoozes")
    expired_snoozes = client.get("/api/v1/snoozes?state=expired")
    all_exclusions = client.get("/api/v1/tag-exclusions?status=all")
    disabled_exclusions = client.get("/api/v1/tag-exclusions?status=disabled")

    assert policies.status_code == 200
    assert policies.json()[0]["service_key"] == "stack/app"
    assert policies.json()[0]["auto_update"] is False
    assert policies.json()[0]["auto_update_time"] == "09:30"
    assert policies.json()[0]["auto_update_days"] == ["mon", "wed"]
    assert policies.json()[0]["metadata"] == {"source": "test"}
    assert active_snoozes.status_code == 200
    assert [row["service_key"] for row in active_snoozes.json()] == [
        "stack/app",
        "stack/worker",
    ]
    assert active_snoozes.json()[0]["active"] is True
    assert active_snoozes.json()[0]["kind"] == "time"
    assert active_snoozes.json()[1]["kind"] == "dependency"
    assert active_snoozes.json()[1]["wait_for_service_key"] == "stack/cache"
    assert expired_snoozes.status_code == 200
    assert [row["service_key"] for row in expired_snoozes.json()] == [
        "stack/old",
        "stack/satisfied",
    ]
    assert expired_snoozes.json()[0]["active"] is False
    assert expired_snoozes.json()[1]["active"] is False
    assert all_exclusions.status_code == 200
    assert [row["status"] for row in all_exclusions.json()] == [
        "active",
        "disabled",
    ]
    assert disabled_exclusions.status_code == 200
    assert disabled_exclusions.json()[0]["service_key"] == "stack/app"


def test_state_operation_endpoint_enforces_auth_csrf_and_read_only(
    tmp_path: Path,
) -> None:
    payload = {
        "kind": "upsert_service_policy",
        "service_key": "stack/app",
        "update_mode": "stop",
    }
    unauthenticated = _client(tmp_path, {"WUD_WEB_MUTATIONS_ENABLED": "true"})
    read_only = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    mutating = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )

    unauthenticated_response = unauthenticated.post(
        "/api/v1/state/operations",
        json=payload,
        headers=_csrf_headers(unauthenticated),
    )
    missing_csrf = mutating.post("/api/v1/state/operations", json=payload)
    read_only_response = read_only.post(
        "/api/v1/state/operations",
        json=payload,
        headers=_csrf_headers(read_only),
    )

    assert unauthenticated_response.status_code == 403
    assert unauthenticated_response.json()["detail"] == "setup required"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "origin header is required"
    assert read_only_response.status_code == 403
    assert read_only_response.json()["detail"] == "mutations are disabled"


def test_state_operations_write_rows_and_audit_entries(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)
    future = (
        datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=1)
    ).isoformat()

    policy = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "pause",
            "auto_update": False,
            "snooze_default_seconds": 600,
            "auto_update_time": "09:30",
            "auto_update_days": ["mon", "wed"],
        },
        headers=headers,
    )
    deleted_policy = client.post(
        "/api/v1/state/operations",
        json={"kind": "delete_service_policy", "service_key": "stack/app"},
        headers=headers,
    )
    snooze = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "create_snooze",
            "service_key": "stack/app",
            "snoozed_until": future,
            "reason": "maintenance",
        },
        headers=headers,
    )
    snooze_id = snooze.json()["resource"]["id"]
    deleted_snooze = client.post(
        "/api/v1/state/operations",
        json={"kind": "delete_snooze", "snooze_id": snooze_id},
        headers=headers,
    )
    dependency_snooze = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "create_dependency_snooze",
            "service_key": "stack/app",
            "wait_for_service_key": "stack/db",
            "reason": "wait for db",
        },
        headers=headers,
    )
    dependency_snooze_id = dependency_snooze.json()["resource"]["id"]
    deleted_dependency_snooze = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "delete_dependency_snooze",
            "snooze_id": dependency_snooze_id,
        },
        headers=headers,
    )
    exclusion = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_tag_exclusion",
            "scope": "service",
            "image_repo": "repo/app",
            "service_key": "stack/app",
            "tag": "2.0",
        },
        headers=headers,
    )
    rule_id = exclusion.json()["resource"]["id"]
    disabled_exclusion = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "set_tag_exclusion_status",
            "rule_id": rule_id,
            "status": "disabled",
        },
        headers=headers,
    )

    assert policy.status_code == 200
    assert policy.json()["resource"]["auto_update"] is False
    assert policy.json()["resource"]["snooze_default_seconds"] == 600
    assert policy.json()["resource"]["auto_update_time"] == "09:30"
    assert policy.json()["resource"]["auto_update_days"] == ["mon", "wed"]
    assert deleted_policy.status_code == 200
    assert deleted_policy.json()["resource"] is None
    assert snooze.status_code == 200
    assert snooze.json()["resource"]["reason"] == "maintenance"
    assert snooze.json()["resource"]["kind"] == "time"
    assert deleted_snooze.status_code == 200
    assert deleted_snooze.json()["resource"] is None
    assert dependency_snooze.status_code == 200
    assert dependency_snooze.json()["resource"]["kind"] == "dependency"
    assert dependency_snooze.json()["resource"]["wait_for_service_key"] == "stack/db"
    assert dependency_snooze.json()["resource"]["active"] is True
    assert deleted_dependency_snooze.status_code == 200
    assert deleted_dependency_snooze.json()["resource"] is None
    assert exclusion.status_code == 200
    assert exclusion.json()["resource"]["regex_fragment"] == "2\\.0"
    assert disabled_exclusion.status_code == 200
    assert disabled_exclusion.json()["resource"]["status"] == "disabled"

    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        service_policies = conn.execute("SELECT * FROM service_policy").fetchall()
        snoozes = conn.execute("SELECT * FROM snoozes").fetchall()
        dependency_snoozes = conn.execute(
            "SELECT * FROM dependency_snoozes"
        ).fetchall()
        tag_exclusion = conn.execute(
            "SELECT * FROM tag_exclusion_rules WHERE id = ?",
            (rule_id,),
        ).fetchone()
        runs = conn.execute(
            "SELECT * FROM update_runs ORDER BY id"
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM update_events ORDER BY id"
        ).fetchall()

    operation_kinds = [
        "upsert_service_policy",
        "delete_service_policy",
        "create_snooze",
        "delete_snooze",
        "create_dependency_snooze",
        "delete_dependency_snooze",
        "upsert_tag_exclusion",
        "set_tag_exclusion_status",
    ]
    run_metadata = [json.loads(row["metadata_json"]) for row in runs]
    event_metadata = [json.loads(row["metadata_json"]) for row in events]
    assert service_policies == []
    assert snoozes == []
    assert dependency_snoozes == []
    assert tag_exclusion["status"] == "disabled"
    assert [row["mode"] for row in runs] == ["web-state"] * 8
    assert [item["operation"] for item in run_metadata] == operation_kinds
    assert [item["operation"] for item in event_metadata] == operation_kinds
    assert event_metadata[0]["before"] is None
    assert event_metadata[1]["before"]["service_key"] == "stack/app"
    assert event_metadata[-1]["after"]["status"] == "disabled"


def test_service_policy_upsert_preserves_omitted_existing_fields(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)

    created = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "stop",
            "auto_update": False,
            "snooze_default_seconds": 600,
            "auto_update_time": "09:30",
            "auto_update_days": ["mon", "wed"],
        },
        headers=headers,
    )
    mode_only_update = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "live",
        },
        headers=headers,
    )
    auto_only_update = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "auto_update": True,
        },
        headers=headers,
    )
    explicit_clear = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "snooze_default_seconds": None,
        },
        headers=headers,
    )

    assert created.status_code == 200
    assert mode_only_update.status_code == 200
    mode_resource = mode_only_update.json()["resource"]
    assert mode_resource["update_mode"] == "live"
    assert mode_resource["auto_update"] is False
    assert mode_resource["snooze_default_seconds"] == 600
    assert mode_resource["auto_update_time"] == "09:30"
    assert mode_resource["auto_update_days"] == ["mon", "wed"]
    assert auto_only_update.status_code == 200
    auto_resource = auto_only_update.json()["resource"]
    assert auto_resource["update_mode"] == "live"
    assert auto_resource["auto_update"] is True
    assert auto_resource["snooze_default_seconds"] == 600
    assert auto_resource["auto_update_time"] == "09:30"
    assert auto_resource["auto_update_days"] == ["mon", "wed"]
    assert explicit_clear.status_code == 200
    clear_resource = explicit_clear.json()["resource"]
    assert clear_resource["update_mode"] == "live"
    assert clear_resource["auto_update"] is True
    assert clear_resource["snooze_default_seconds"] is None
    assert clear_resource["auto_update_time"] == "09:30"
    assert clear_resource["auto_update_days"] == ["mon", "wed"]


def test_state_operation_rolls_back_when_audit_insert_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = "github-secret-token"
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "GITHUB_TOKEN": secret,
        },
    )
    headers = _csrf_headers(client)

    def fail_audit(*_args: object, **_kwargs: object) -> int:
        raise sqlite3.OperationalError(
            f"audit failed for {tmp_path / 'state' / 'wud.sqlite'} with {secret}"
        )

    monkeypatch.setattr(state_module, "_insert_state_audit", fail_audit)

    response = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "stop",
        },
        headers=headers,
    )

    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        rows = conn.execute("SELECT * FROM service_policy").fetchall()
        runs = conn.execute("SELECT * FROM update_runs").fetchall()

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail.startswith("could not update database: audit failed for ")
    assert str(tmp_path) not in detail
    assert secret not in detail
    assert "[REDACTED_PATH]" in detail
    assert "<redacted>" in detail
    assert rows == []
    assert runs == []


def test_state_operation_uses_state_module_audit_seam(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)

    def fail_audit(*_args: object, **_kwargs: object) -> int:
        raise sqlite3.OperationalError("web audit seam used")

    monkeypatch.setattr(state_module, "_insert_state_audit", fail_audit)

    response = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "stop",
        },
        headers=headers,
    )

    assert response.status_code == 500
    assert response.json()["detail"].startswith(
        "could not update database: web audit seam used"
    )


def test_state_operations_validate_inputs(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)
    past = "2000-01-01T00:00:00+00:00"
    invalid_payloads = [
        {
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "restart",
        },
        {
            "kind": "create_snooze",
            "service_key": "stack/app",
            "snoozed_until": past,
        },
        {
            "kind": "create_dependency_snooze",
            "service_key": "stack/app",
            "wait_for_service_key": "stack/app",
        },
        {
            "kind": "upsert_tag_exclusion",
            "scope": "global",
            "image_repo": "repo/app",
            "tag": "2.0",
        },
        {
            "kind": "upsert_tag_exclusion",
            "scope": "service",
            "image_repo": "repo/app",
            "tag": "2.0",
        },
        {
            "kind": "upsert_tag_exclusion",
            "scope": "image_repo",
            "image_repo": "repo/app",
            "tag": "bad:value",
        },
        {
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "auto_update_time": "9:30",
        },
    ]

    responses = [
        client.post("/api/v1/state/operations", json=payload, headers=headers)
        for payload in invalid_payloads
    ]

    assert [response.status_code for response in responses] == [422] * len(
        invalid_payloads
    )


def test_managed_digest_pin_updates_persists_true_and_reloads(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)

    write_response = client.post(
        "/api/v1/settings/managed",
        json={"values": {"digest_pin_updates": "true"}},
        headers=headers,
    )
    reload_response = client.get("/api/v1/settings")
    managed = {entry["key"]: entry for entry in reload_response.json()["managed"]}

    assert write_response.status_code == 200
    write_managed = {entry["key"]: entry for entry in write_response.json()["managed"]}
    assert write_managed["digest_pin_updates"]["value"] == "true"
    assert write_managed["digest_pin_updates"]["source"] == "configured"
    assert managed["digest_pin_updates"]["value"] == "true"
    assert managed["digest_pin_updates"]["source"] == "configured"


def test_managed_digest_pin_updates_can_be_reset_to_false(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)

    initial_response = client.post(
        "/api/v1/settings/managed",
        json={"values": {"digest_pin_updates": "true"}},
        headers=headers,
    )
    initial_managed = {
        entry["key"]: entry for entry in initial_response.json()["managed"]
    }

    assert initial_response.status_code == 200
    assert initial_managed["digest_pin_updates"]["value"] == "true"
    assert initial_managed["digest_pin_updates"]["source"] == "configured"

    reset_response = client.post(
        "/api/v1/settings/managed",
        json={"values": {"digest_pin_updates": "false"}},
        headers=headers,
    )
    managed = {entry["key"]: entry for entry in reset_response.json()["managed"]}

    assert reset_response.status_code == 200
    assert managed["digest_pin_updates"]["value"] == "false"
    assert managed["digest_pin_updates"]["source"] == "configured"


def test_managed_digest_pin_updates_rejects_invalid_value(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)

    response = client.post(
        "/api/v1/settings/managed",
        json={"values": {"digest_pin_updates": "maybe"}},
        headers=headers,
    )

    assert response.status_code == 422
    assert "maybe" in response.json()["detail"] or "digest_pin_updates" in response.json()["detail"]


def test_digest_pin_updates_env_false_shows_as_not_editable(
    tmp_path: Path,
) -> None:
    """When WUD_DIGEST_PIN_UPDATES=false is set in env, webui editing is disabled."""
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_DIGEST_PIN_UPDATES": "false",
        },
    )

    settings_response = client.get("/api/v1/settings")
    managed = {entry["key"]: entry for entry in settings_response.json()["managed"]}

    assert managed["digest_pin_updates"]["value"] == "false"
    assert managed["digest_pin_updates"]["editable"] is False
    assert "WUD_DIGEST_PIN_UPDATES" in managed["digest_pin_updates"]["disabled_reason"]


def test_updater_settings_entry_includes_digest_pin_updates(
    tmp_path: Path,
) -> None:
    """WUD_DIGEST_PIN_UPDATES should appear in the updater settings section."""
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_DIGEST_PIN_UPDATES": "true",
        },
    )

    response = client.get("/api/v1/settings")
    body = response.json()
    updater = {entry["name"]: entry for entry in body["updater"]}

    assert "WUD_DIGEST_PIN_UPDATES" in updater
    assert updater["WUD_DIGEST_PIN_UPDATES"]["value"] == "true"
    assert updater["WUD_DIGEST_PIN_UPDATES"]["configured"] is True


def test_updater_settings_entry_digest_pin_updates_default_is_false(
    tmp_path: Path,
) -> None:
    """Without WUD_DIGEST_PIN_UPDATES in env, the updater settings entry shows false."""
    client = _client(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true"},
    )

    response = client.get("/api/v1/settings")
    body = response.json()
    updater = {entry["name"]: entry for entry in body["updater"]}

    assert "WUD_DIGEST_PIN_UPDATES" in updater
    assert updater["WUD_DIGEST_PIN_UPDATES"]["value"] == "false"
    assert updater["WUD_DIGEST_PIN_UPDATES"]["source"] == "default"
    assert updater["WUD_DIGEST_PIN_UPDATES"]["configured"] is False


def test_managed_digest_pin_default_value_is_false(
    tmp_path: Path,
) -> None:
    """The digest_pin_updates managed setting defaults to false with no config."""
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get("/api/v1/settings")
    managed = {entry["key"]: entry for entry in response.json()["managed"]}

    assert managed["digest_pin_updates"]["default_value"] == "false"
    assert managed["digest_pin_updates"]["value"] == "false"
    assert managed["digest_pin_updates"]["source"] == "default"
    assert managed["digest_pin_updates"]["allowed_values"] == ["false", "true"]
    assert managed["digest_pin_updates"]["editable"] is True
    assert managed["digest_pin_updates"]["restart_required"] is False


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

def test_status_counts_pending_without_resolving_groups(tmp_path: Path) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
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
    assert _fake_docker_calls(fake_root) == ""

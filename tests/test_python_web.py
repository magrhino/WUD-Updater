from __future__ import annotations

import json
import logging
from pathlib import Path


from wud_updater import web as web_module
from wud_updater import web_jobs
from wud_updater import web_models
from wud_updater.db import open_db
from wud_updater.release_notes import ReleaseNoteInfo as ReleaseNoteData


from tests.web_test_helpers import (
    _client,
    _doctor_client,
    _csrf_headers,
    _setup_admin,
    _insert_run,
    _fake_docker_env,
    _make_fake_stack,
    _fake_docker_calls,
    _assert_pending_grouping_did_not_mutate,
    _fake_image_state_file,
    _wait_apply_job,
)

def test_web_module_reexports_web_models_for_compatibility() -> None:
    missing = [name for name in web_models.__all__ if not hasattr(web_module, name)]

    assert missing == []


def test_healthz_is_unauthenticated_before_setup(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/healthz")

    assert response.status_code == 200


def test_healthz_response_shape_is_minimal(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/healthz")
    body = response.json()

    assert response.status_code == 200
    assert body == {"ok": True, "version": web_module.__version__}
    assert set(body) == {"ok", "version"}
    sensitive_keys = {
        "wud_file",
        "db_path",
        "pending_count",
        "auth_required",
        "dev_auth_bypass",
        "setup_required",
        "mutations_enabled",
        "public_origin",
        "trusted_proxies",
    }
    assert sensitive_keys.isdisjoint(body)


def test_readyz_is_unauthenticated_and_reports_local_readiness(
    tmp_path: Path,
) -> None:
    client = _doctor_client(tmp_path, client=("127.0.0.1", 50000))

    response = client.get("/readyz")
    body = response.json()
    codes = {check["code"] for check in body["checks"]}

    assert response.status_code == 200
    assert body["ok"] is True
    assert set(body) == {"ok", "version", "checks"}
    assert {
        "docker-endpoint",
        "docker-daemon-version",
        "docker-daemon-info",
        "docker-container-listing",
        "wud-out-file-directory",
        "wud-out-file",
        "webui-database",
    }.issubset(codes)
    sensitive_keys = {
        "wud_file",
        "db_path",
        "pending_count",
        "auth_required",
        "dev_auth_bypass",
        "setup_required",
        "mutations_enabled",
        "public_origin",
        "trusted_proxies",
    }
    assert sensitive_keys.isdisjoint(body)


def test_readyz_rejects_non_loopback_client(
    tmp_path: Path,
) -> None:
    client = _doctor_client(tmp_path, client=("203.0.113.10", 50000))

    response = client.get("/readyz")

    assert response.status_code == 404
    assert response.content == b""


def test_readyz_ignores_forwarded_loopback_from_trusted_proxy(
    tmp_path: Path,
) -> None:
    client = _doctor_client(
        tmp_path,
        {"WUD_WEB_TRUSTED_PROXIES": "203.0.113.10/32"},
        client=("203.0.113.10", 50000),
    )

    response = client.get("/readyz", headers={"X-Forwarded-For": "127.0.0.1"})

    assert response.status_code == 404
    assert response.content == b""


def test_ready_api_requires_auth_and_returns_local_readiness(
    tmp_path: Path,
) -> None:
    unauthenticated = _client(tmp_path)
    client = _doctor_client(tmp_path, client=("203.0.113.10", 50000))

    auth_response = unauthenticated.get("/api/v1/ready")
    ready_response = client.get("/api/v1/ready")

    assert auth_response.status_code == 403
    assert auth_response.json()["detail"] == "setup required"
    assert ready_response.status_code == 200
    body = ready_response.json()
    codes = {check["code"] for check in body["checks"]}
    assert body["ok"] is True
    assert "docker-daemon-info" in codes
    assert "webui-database" in codes


def test_readyz_fails_when_required_local_check_fails(
    tmp_path: Path,
) -> None:
    secret = "docker-info-secret"
    client = _doctor_client(
        tmp_path,
        {
            "GITHUB_TOKEN": secret,
            "FAKE_DOCKER_INFO_SECRET": secret,
        },
        client=("127.0.0.1", 50000),
    )

    response = client.get("/readyz")
    body = response.json()
    checks = {check["code"]: check for check in body["checks"]}

    assert response.status_code == 503
    assert body["ok"] is False
    assert checks["docker-daemon-info"]["status"] == "FAIL"
    assert checks["docker-daemon-info"]["detail"] == "exit 17: info failed: <redacted>"
    assert secret not in json.dumps(body)


def test_readyz_fails_when_required_checks_are_missing(
    tmp_path: Path,
) -> None:
    client = _doctor_client(
        tmp_path,
        {"WUD_UPDATER_USE_SUDO": "treu"},
        client=("127.0.0.1", 50000),
    )

    response = client.get("/readyz")
    body = response.json()
    checks = {check["code"]: check for check in body["checks"]}

    assert response.status_code == 503
    assert body["ok"] is False
    assert checks["configuration"]["status"] == "FAIL"
    assert checks["readiness-missing-checks"]["status"] == "FAIL"
    assert "docker socket or endpoint" in checks["readiness-missing-checks"]["detail"]


def test_doctor_endpoint_enforces_auth_csrf_and_post(
    tmp_path: Path,
) -> None:
    unauthenticated = _client(tmp_path)
    doctor = _doctor_client(tmp_path)

    auth_response = unauthenticated.post(
        "/api/v1/doctor",
        headers=_csrf_headers(unauthenticated),
    )
    missing_csrf = doctor.post("/api/v1/doctor")
    get_response = doctor.get("/api/v1/doctor")

    assert auth_response.status_code == 403
    assert auth_response.json()["detail"] == "setup required"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "origin header is required"
    assert get_response.status_code == 405
    assert get_response.headers["allow"] == "POST"


def test_doctor_endpoint_returns_structured_redacted_results(
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

    response = client.post("/api/v1/doctor", headers=_csrf_headers(client))
    body = response.json()
    checks = {check["code"]: check for check in body["checks"]}
    serialized = json.dumps(body)

    assert response.status_code == 200
    assert body["ok"] is False
    assert body["failures"] >= 1
    assert body["warnings"] >= 1
    assert checks["docker-daemon-info"]["status"] == "FAIL"
    assert checks["docker-daemon-info"]["detail"] == "exit 17: info failed: <redacted>"
    assert checks["docker-daemon-info"]["suggestions"]
    assert checks["webui-database"]["status"] == "PASS"
    assert checks["webui-authentication"]["status"] == "WARN"
    assert secret not in serialized
    assert "<redacted>" in serialized


def test_onboarding_endpoints_enforce_auth_csrf_and_post(
    tmp_path: Path,
) -> None:
    unauthenticated = _client(tmp_path)
    post_setup = _client(tmp_path)
    client = _doctor_client(tmp_path)

    auth_response = unauthenticated.post(
        "/api/v1/onboarding/checklist",
        headers=_csrf_headers(unauthenticated),
    )
    _setup_admin(post_setup)
    post_setup.cookies.clear()
    post_setup_auth_response = post_setup.post(
        "/api/v1/onboarding/checklist",
        headers=_csrf_headers(post_setup),
    )
    missing_csrf = client.post("/api/v1/onboarding/checklist")
    dismiss_missing_csrf = client.post("/api/v1/onboarding/dismiss")
    get_response = client.get("/api/v1/onboarding/checklist")
    dismiss_get_response = client.get("/api/v1/onboarding/dismiss")

    assert auth_response.status_code == 403
    assert auth_response.json()["detail"] == "setup required"
    assert post_setup_auth_response.status_code == 401
    assert post_setup_auth_response.json()["detail"] == "authentication required"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "origin header is required"
    assert dismiss_missing_csrf.status_code == 403
    assert dismiss_missing_csrf.json()["detail"] == "origin header is required"
    assert get_response.status_code == 405
    assert get_response.headers["allow"] == "POST"
    assert dismiss_get_response.status_code == 405
    assert dismiss_get_response.headers["allow"] == "POST"


def test_onboarding_checklist_returns_redacted_setup_items(
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

    response = client.post(
        "/api/v1/onboarding/checklist",
        headers=_csrf_headers(client),
    )
    body = response.json()
    items = {item["key"]: item for item in body["items"]}
    serialized = json.dumps(body)

    assert response.status_code == 200
    assert body["dismissed"] is False
    assert body["visible"] is True
    assert body["all_passed"] is False
    assert {
        "admin-setup",
        "wud-output",
        "wud-scripts",
        "docker-access",
        "compose-discovery",
        "persistence",
        "browser-access",
        "mutation-mode",
    }.issubset(items)
    assert items["docker-access"]["status"] == "FAIL"
    assert items["docker-access"]["suggestions"]
    assert "docker-daemon-info" in items["docker-access"]["check_codes"]
    assert items["mutation-mode"]["status"] == "PASS"
    assert secret not in serialized
    assert "<redacted>" in serialized


def test_onboarding_checklist_uses_default_compose_ignore_paths(
    tmp_path: Path,
) -> None:
    client = _doctor_client(tmp_path)
    docker_base = client.app.state.web_settings.config.docker_base
    ignored_stack = docker_base / "old" / "ignored"
    ignored_stack.mkdir(parents=True)
    (ignored_stack / "docker-compose.yml").write_text(
        "services:\n  ignored:\n    image: repo/ignored:latest\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/onboarding/checklist",
        headers=_csrf_headers(client),
    )
    body = response.json()
    compose_item = next(
        item for item in body["items"] if item["key"] == "compose-discovery"
    )

    assert response.status_code == 200
    assert compose_item["status"] == "PASS"
    assert all("old-ignored" not in code for code in compose_item["check_codes"])


def test_onboarding_dismissal_persists_in_sqlite(
    tmp_path: Path,
) -> None:
    client = _doctor_client(tmp_path)

    before = client.post(
        "/api/v1/onboarding/checklist",
        headers=_csrf_headers(client),
    )
    dismiss = client.post(
        "/api/v1/onboarding/dismiss",
        headers=_csrf_headers(client),
    )
    after = client.post(
        "/api/v1/onboarding/checklist",
        headers=_csrf_headers(client),
    )

    assert before.status_code == 200
    assert before.json()["visible"] is True
    assert dismiss.status_code == 200
    assert dismiss.json()["dismissed"] is True
    assert dismiss.json()["dismissed_at"]
    assert after.status_code == 200
    assert after.json()["dismissed"] is True
    assert after.json()["visible"] is False
    assert after.json()["dismissed_at"] == dismiss.json()["dismissed_at"]


def test_onboarding_checklist_skips_doctor_after_dismissal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _doctor_client(tmp_path)
    dismiss = client.post(
        "/api/v1/onboarding/dismiss",
        headers=_csrf_headers(client),
    )

    def fail_doctor(*_args, **_kwargs):
        raise AssertionError("dismissed onboarding should not run doctor")

    monkeypatch.setattr(web_module, "_web_doctor_result", fail_doctor)
    after = client.post(
        "/api/v1/onboarding/checklist",
        headers=_csrf_headers(client),
    )

    assert dismiss.status_code == 200
    assert after.status_code == 200
    assert after.json()["dismissed"] is True
    assert after.json()["visible"] is False
    assert after.json()["items"] == []


def test_onboarding_checklist_hides_when_required_items_pass(
    tmp_path: Path,
) -> None:
    client = _doctor_client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "false",
            "WUD_WEB_PUBLIC_ORIGIN": "http://testserver",
        },
    )
    _setup_admin(client)

    response = client.post(
        "/api/v1/onboarding/checklist",
        headers=_csrf_headers(client),
    )
    body = response.json()
    required = {
        item["key"]: item["status"]
        for item in body["items"]
        if item["key"] != "mutation-mode"
    }

    assert response.status_code == 200
    assert body["dismissed"] is False
    assert body["all_passed"] is True
    assert body["visible"] is False
    assert set(required.values()) == {"PASS"}


def test_onboarding_checklist_stays_visible_when_mutations_enabled(
    tmp_path: Path,
) -> None:
    client = _doctor_client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "false",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_PUBLIC_ORIGIN": "http://testserver",
        },
    )
    _setup_admin(client)

    response = client.post(
        "/api/v1/onboarding/checklist",
        headers=_csrf_headers(client),
    )
    body = response.json()
    items = {item["key"]: item for item in body["items"]}

    assert response.status_code == 200
    assert items["mutation-mode"]["status"] == "WARN"
    assert body["all_passed"] is False
    assert body["visible"] is True


def test_core_update_tour_endpoint_enforces_auth_csrf_and_post(
    tmp_path: Path,
) -> None:
    unauthenticated_root = tmp_path / "unauthenticated"
    post_setup_root = tmp_path / "post-setup"
    read_only_root = tmp_path / "read-only"
    unauthenticated_root.mkdir()
    post_setup_root.mkdir()
    read_only_root.mkdir()
    unauthenticated = _client(unauthenticated_root)
    post_setup = _client(post_setup_root)
    read_only = _client(
        read_only_root,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "false",
        },
    )

    auth_response = unauthenticated.get("/api/v1/onboarding/core-update-tour")
    _setup_admin(post_setup)
    post_setup.cookies.clear()
    post_setup_auth_response = post_setup.get("/api/v1/onboarding/core-update-tour")
    missing_csrf = read_only.post(
        "/api/v1/onboarding/core-update-tour",
        json={"status": "in_progress", "step": "dashboard"},
    )
    origin_without_csrf = read_only.post(
        "/api/v1/onboarding/core-update-tour",
        json={"status": "in_progress", "step": "dashboard"},
        headers={"Origin": "http://testserver"},
    )
    csrf_headers = _csrf_headers(read_only)
    bad_origin = read_only.post(
        "/api/v1/onboarding/core-update-tour",
        json={"status": "in_progress", "step": "dashboard"},
        headers={**csrf_headers, "Origin": "http://evil.example"},
    )
    bad_host = read_only.post(
        "/api/v1/onboarding/core-update-tour",
        json={"status": "in_progress", "step": "dashboard"},
        headers={**csrf_headers, "Host": "evil.test"},
    )
    get_response = read_only.get("/api/v1/onboarding/core-update-tour")

    assert auth_response.status_code == 403
    assert auth_response.json()["detail"] == "setup required"
    assert post_setup_auth_response.status_code == 401
    assert post_setup_auth_response.json()["detail"] == "authentication required"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "origin header is required"
    assert origin_without_csrf.status_code == 403
    assert origin_without_csrf.json()["detail"] == "csrf token is required"
    assert bad_origin.status_code == 403
    assert bad_origin.json()["detail"] == "origin is not allowed"
    assert bad_host.status_code == 400
    assert bad_host.json()["detail"] == "host is not allowed"
    assert get_response.status_code == 200
    assert get_response.json() == {
        "status": "not_started",
        "step": "dashboard",
        "updated_at": "",
    }
    assert not (read_only_root / "state" / "wud.sqlite").exists()


def test_core_update_tour_persists_in_read_only_mode(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "false",
        },
    )
    db_path = tmp_path / "state" / "wud.sqlite"

    before = client.get("/api/v1/onboarding/core-update-tour")
    update = client.post(
        "/api/v1/onboarding/core-update-tour",
        json={"status": "in_progress", "step": "pending_preflight"},
        headers=_csrf_headers(client),
    )
    after = client.get("/api/v1/onboarding/core-update-tour")

    assert before.status_code == 200
    assert before.json()["status"] == "not_started"
    assert update.status_code == 200
    assert update.json()["status"] == "in_progress"
    assert update.json()["step"] == "pending_preflight"
    assert update.json()["updated_at"]
    assert after.json() == update.json()
    with open_db(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM web_settings WHERE key = 'onboarding_core_update_tour'"
        ).fetchone()
    stored = json.loads(row["value"])
    assert stored == {"status": "in_progress", "step": "pending_preflight"}


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


def test_update_targets_endpoint_lists_compose_service_images_without_mutation(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [
            ("app", "ghcr.io/acme/app:1.0", "cid-app"),
            ("db", "postgres:16@sha256:abc", "cid-db"),
        ],
    )

    response = client.get("/api/v1/update-targets")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["count"] == 2
    assert body["warnings"] == []
    assert [
        (item["service_key"], item["image"], item["image_repo"], item["current_tag"])
        for item in body["items"]
    ] == [
        ("stack/app", "ghcr.io/acme/app:1.0", "acme/app", "1.0"),
        ("stack/db", "postgres:16@sha256:abc", "postgres", "16"),
    ]
    assert all(item["compose_file"] == "docker-compose.yml" for item in body["items"])
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_release_notes_get_returns_placeholders_without_creating_database(
    tmp_path: Path,
) -> None:
    wud_file = tmp_path / "state" / "images.todo"
    db_path = tmp_path / "state" / "wud.sqlite"
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    wud_file.write_text("ghcr.io/acme/app:1.0.0\n", encoding="utf-8")

    response = client.get("/api/v1/release-notes")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["line_no"] == 1
    assert body["items"][0]["status"] == "missing"
    assert body["items"][0]["provider"] == "github"
    assert not db_path.exists()


def test_release_notes_get_uses_docker_source_label_without_creating_database(
    tmp_path: Path,
) -> None:
    wud_file = tmp_path / "state" / "images.todo"
    db_path = tmp_path / "state" / "wud.sqlite"
    docker_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            **docker_env,
        },
    )
    image = "advplyr/audiobookshelf:latest"
    wud_file.write_text(f"{image}\n", encoding="utf-8")
    _fake_image_state_file(fake_root, image, "labels").write_text(
        "org.opencontainers.image.source=https://github.com/advplyr/audiobookshelf\n",
        encoding="utf-8",
    )

    response = client.get("/api/v1/release-notes")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["status"] == "missing"
    assert body["items"][0]["provider"] == "github"
    assert body["items"][0]["upstream_repo"] == "advplyr/audiobookshelf"
    assert f"image inspect {image}" in _fake_docker_calls(fake_root)
    assert not db_path.exists()


def test_release_notes_get_recovers_ghcr_repo_from_running_image(
    tmp_path: Path,
) -> None:
    wud_file = tmp_path / "state" / "images.todo"
    db_path = tmp_path / "state" / "wud.sqlite"
    docker_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            **docker_env,
        },
    )
    image = "advplyr/audiobookshelf:latest"
    wud_file.write_text(f"{image}\n", encoding="utf-8")
    (fake_root / "containers.tsv").write_text(
        "audiobookshelf\tghcr.io/advplyr/audiobookshelf:latest\n",
        encoding="utf-8",
    )

    response = client.get("/api/v1/release-notes")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["status"] == "missing"
    assert body["items"][0]["provider"] == "github"
    assert body["items"][0]["image_repo"] == "advplyr/audiobookshelf"
    assert body["items"][0]["upstream_repo"] == "advplyr/audiobookshelf"
    calls = _fake_docker_calls(fake_root)
    assert f"image inspect {image}" in calls
    assert "ps --format" in calls
    assert not db_path.exists()


def test_release_notes_get_recovers_ghcr_repo_from_running_container_name(
    tmp_path: Path,
) -> None:
    wud_file = tmp_path / "state" / "images.todo"
    db_path = tmp_path / "state" / "wud.sqlite"
    docker_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            **docker_env,
        },
    )
    container = "audiobookshelf"
    wud_file.write_text(f"{container}\n", encoding="utf-8")
    (fake_root / "containers.tsv").write_text(
        "audiobookshelf\tghcr.io/advplyr/audiobookshelf:latest\n",
        encoding="utf-8",
    )

    response = client.get("/api/v1/release-notes")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["status"] == "missing"
    assert body["items"][0]["provider"] == "github"
    assert body["items"][0]["image_repo"] == "advplyr/audiobookshelf"
    assert body["items"][0]["upstream_repo"] == "advplyr/audiobookshelf"
    calls = _fake_docker_calls(fake_root)
    assert f"image inspect {container}" in calls
    assert "ps --format" in calls
    assert not db_path.exists()


def test_release_notes_get_logs_when_docker_source_label_inspect_fails(
    tmp_path: Path,
    caplog,
) -> None:
    wud_file = tmp_path / "state" / "images.todo"
    no_docker_bin = tmp_path / "no-docker-bin"
    no_docker_bin.mkdir()
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "PATH": str(no_docker_bin),
        },
    )
    image = "advplyr/audiobookshelf:latest"
    wud_file.write_text(f"{image}\n", encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="wud_updater.web"):
        response = client.get("/api/v1/release-notes")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["status"] == "unsupported"
    assert body["items"][0]["error"] == "no supported GitHub release source found"
    assert (
        "WebUI release-note fallback: Docker inspect failed for "
        "advplyr/audiobookshelf:latest"
    ) in caplog.text
    assert "cannot read org.opencontainers.image.source" in caplog.text


def test_release_notes_refresh_requires_csrf(tmp_path: Path) -> None:
    wud_file = tmp_path / "state" / "images.todo"
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    wud_file.write_text("docker.io/library/redis:latest\n", encoding="utf-8")

    response = client.post("/api/v1/release-notes/refresh")

    assert response.status_code == 403
    assert response.json()["detail"] == "origin header is required"

    response = client.post(
        "/api/v1/release-notes/refresh",
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "csrf token is required"


def test_release_notes_refresh_works_when_mutations_are_disabled(
    tmp_path: Path,
) -> None:
    wud_file = tmp_path / "state" / "images.todo"
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    wud_file.write_text("docker.io/library/redis:latest\n", encoding="utf-8")

    response = client.post(
        "/api/v1/release-notes/refresh",
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["status"] == "unsupported"
    assert body["items"][0]["error"] == "no supported GitHub release source found"


def test_release_note_error_metadata_redacts_configured_secrets(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    github_token = "github-token-secret-value"
    release_webhook = "https://discord.test/fail/release-secret-token"
    admin_webhook = "https://discord.test/fail/admin-secret-token"
    wud_file = tmp_path / "state" / "images.todo"
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "GITHUB_TOKEN": github_token,
            "DISCORD_RELEASES_WEBHOOK": release_webhook,
            "ADMIN_WEBHOOK": admin_webhook,
        },
    )
    wud_file.write_text("ghcr.io/acme/app:1.0.0 tag=2.0.0\n", encoding="utf-8")

    def fake_refresh_release_notes(
        _conn,
        _targets,
        _environ,
        *,
        redact_error=None,
        **_kwargs,
    ):
        error = (
            f"request failed with {github_token} via {release_webhook} "
            f"and {admin_webhook}"
        )
        if redact_error is not None:
            error = redact_error(error)
        return [
            ReleaseNoteData(
                line_no=1,
                status="error",
                provider="github",
                image_repo="acme/app",
                upstream_repo="acme/app",
                error=error,
            )
        ]

    monkeypatch.setattr(
        web_module,
        "refresh_release_notes",
        fake_refresh_release_notes,
    )

    with caplog.at_level(logging.DEBUG):
        response = client.post(
            "/api/v1/release-notes/refresh",
            headers=_csrf_headers(client),
        )

    assert response.status_code == 200
    assert "<redacted>" in response.text
    for secret in (
        github_token,
        release_webhook,
        "release-secret-token",
        admin_webhook,
        "admin-secret-token",
    ):
        assert secret not in response.text
        assert secret not in caplog.text


def test_container_restart_endpoint_enforces_auth_csrf_read_only_and_post(
    tmp_path: Path,
) -> None:
    payload = {"confirmation": "restart_container"}
    unauthenticated = _client(tmp_path, {"WUD_WEB_MUTATIONS_ENABLED": "true"})
    read_only = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
        },
    )
    mutating = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
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
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
            **fake_env,
        },
    )
    client.app.state.web_apply_jobs["job-active"] = web_module.WebApplyJob(
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
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
            **fake_env,
        },
    )
    (fake_root / "containers" / "wud-updater.summary").write_text(
        "/wud-updater|running|healthy|0|0\n",
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
    assert body["container"] == "wud-updater"
    calls = _fake_docker_calls(fake_root)
    assert "inspect wud-updater" in calls
    assert "restart --time 10 wud-updater" in calls

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
    assert metadata["target"] == {"container": "wud-updater"}
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
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
            **fake_env,
        },
    )
    (fake_root / "containers" / "wud-updater.summary").write_text(
        "/wud-updater|running|healthy|0|0\n",
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
    assert "restart --time 10 wud-updater" in _fake_docker_calls(fake_root)

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


def test_legacy_apply_routes_remain_compatible(
    tmp_path: Path,
    monkeypatch,
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
    wud_file.write_text("repo/app:latest\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )

    monkeypatch.setattr(web_jobs.UpdateFromWudRunner, "run", lambda _runner: 0)
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()

    apply_response = client.post(
        "/api/v1/plans/apply",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1],
            "confirmation": "apply",
        },
        headers=headers,
    )
    job = _wait_apply_job(client, apply_response.json()["job_id"])
    legacy_status = client.get(f"/api/v1/apply-jobs/{job['job_id']}")

    assert apply_response.status_code == 202
    assert job["status"] == "success"
    assert legacy_status.status_code == 200
    assert legacy_status.json()["job_id"] == job["job_id"]
    calls = _fake_docker_calls(fake_root)
    assert " pull " not in calls
    assert " up -d " not in calls


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

from __future__ import annotations
import json
from pathlib import Path
from wud_updater import web as web_module
from wud_updater import web_jobs
from wud_updater import web_plans as plans_module
from wud_updater import web_self_update as self_update_module
from wud_updater.config import ConfigError
from wud_updater.db import DatabaseError, init_db, open_db, upsert_known_image
from wud_updater.digest_provenance import DigestTagProvenance
from wud_updater.locks import DirectoryLock, WudLockError, lock_dir_for
from tests.web_test_helpers import (
    _client,
    _csrf_headers,
    _fake_docker_env,
    _make_fake_stack,
    _write_fake_container_labels,
    _fake_docker_calls,
    _write_fake_manifest,
    _write_fake_image_after_pull,
    _manifest_index_digest,
    _wait_apply_job,
)


def _seed_known_digest_provenance(
    tmp_path: Path,
    *,
    service_key: str = "stack/app",
    image: str = "repo/app@sha256:old",
    tag: str = "latest",
) -> None:
    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        init_db(conn)
        upsert_known_image(
            conn,
            service_key=service_key,
            image=image,
            image_id="sha256:old-id",
            digest=image,
            digest_provenance=DigestTagProvenance(
                source_image=f"repo/app:{tag}",
                resolved_tag=tag,
                watch_tag=tag,
                target_digest="sha256:old",
                final_image=image,
                provenance_source="apply",
                provenance_confidence="verified",
            ),
        )


def test_self_update_plan_endpoint_returns_pinned_tag_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    monkeypatch.setattr(
        self_update_module,
        "current_container_image",
        lambda _env: "ghcr.io/magrhino/wud-updater:v0.24.2",
    )
    monkeypatch.setattr(
        self_update_module,
        "_fetch_self_update_release_notes",
        lambda *_args, **_kwargs: ([], False, []),
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
            **fake_env,
        },
    )
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "wud",
        [
            (
                "wud-updater",
                "ghcr.io/magrhino/wud-updater:v0.24.2",
                "wud-updater",
            ),
        ],
    )
    compose_before = (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")

    response = client.post(
        "/api/v1/self-update/plan",
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "prepare_tag_update"
    assert body["external_recreate_required"] is True
    assert body["target_image"] == "ghcr.io/magrhino/wud-updater:v0.25.0"
    assert body["plan"]["status"] == "ready"
    assert body["plan"]["can_apply"] is True
    stack = body["plan"]["stacks"][0]
    assert stack["services"] == ["wud-updater"]
    assert stack["tag_updates"] == [
        {
            "old_image": "ghcr.io/magrhino/wud-updater:v0.24.2",
            "desired_tag": "v0.25.0",
            "new_image": "ghcr.io/magrhino/wud-updater:v0.25.0",
            "services": ["wud-updater"],
        }
    ]
    assert (compose_dir / "docker-compose.yml").read_text(encoding="utf-8") == compose_before
    calls = _fake_docker_calls(fake_root)
    assert "manifest inspect ghcr.io/magrhino/wud-updater:v0.25.0" in calls
    assert " pull " not in calls
    assert " up -d " not in calls
    assert "restart " not in calls


def test_self_update_prepare_endpoint_rejects_stale_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    monkeypatch.setattr(
        self_update_module,
        "current_container_image",
        lambda _env: "ghcr.io/magrhino/wud-updater:v0.24.2",
    )
    monkeypatch.setattr(
        self_update_module,
        "_fetch_self_update_release_notes",
        lambda *_args, **_kwargs: ([], False, []),
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
            **fake_env,
        },
    )

    response = client.post(
        "/api/v1/self-update/prepare",
        json={
            "confirmation": "prepare_tag_update",
            "plan_id": "missing-plan",
            "current_tag": "v0.24.2",
            "latest_tag": "v0.25.0",
            "target_image": "ghcr.io/magrhino/wud-updater:v0.25.0",
            "restart_container": "wud-updater",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "self-update plan is stale"
    assert client.app.state.web_self_update_running is False
    assert _fake_docker_calls(fake_root) == ""


def test_self_update_plan_and_prepare_enforce_auth_csrf_read_only_and_active_job(
    tmp_path: Path,
) -> None:
    prepare_payload = {
        "confirmation": "prepare_tag_update",
        "plan_id": "plan",
        "current_tag": "v0.24.2",
        "latest_tag": "v0.25.0",
        "target_image": "ghcr.io/magrhino/wud-updater:v0.25.0",
        "restart_container": "wud-updater",
    }
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
    mutating.app.state.web_apply_jobs["job-active"] = web_module.WebApplyJob(
        id="job-active",
        status="running",
        selected_line_numbers=(1,),
    )

    unauthenticated_plan = unauthenticated.post(
        "/api/v1/self-update/plan",
        headers=_csrf_headers(unauthenticated),
    )
    missing_csrf_plan = mutating.post("/api/v1/self-update/plan")
    read_only_plan = read_only.post(
        "/api/v1/self-update/plan",
        headers=_csrf_headers(read_only),
    )
    active_job_plan = mutating.post(
        "/api/v1/self-update/plan",
        headers=_csrf_headers(mutating),
    )
    unauthenticated_prepare = unauthenticated.post(
        "/api/v1/self-update/prepare",
        json=prepare_payload,
        headers=_csrf_headers(unauthenticated),
    )
    missing_csrf_prepare = mutating.post(
        "/api/v1/self-update/prepare",
        json=prepare_payload,
    )
    read_only_prepare = read_only.post(
        "/api/v1/self-update/prepare",
        json=prepare_payload,
        headers=_csrf_headers(read_only),
    )
    active_job_prepare = mutating.post(
        "/api/v1/self-update/prepare",
        json=prepare_payload,
        headers=_csrf_headers(mutating),
    )

    assert unauthenticated_plan.status_code == 403
    assert unauthenticated_plan.json()["detail"] == "setup required"
    assert missing_csrf_plan.status_code == 403
    assert missing_csrf_plan.json()["detail"] == "origin header is required"
    assert read_only_plan.status_code == 403
    assert read_only_plan.json()["detail"] == "mutations are disabled"
    assert active_job_plan.status_code == 409
    assert active_job_plan.json()["detail"] == "an apply job is already running"
    assert unauthenticated_prepare.status_code == 403
    assert unauthenticated_prepare.json()["detail"] == "setup required"
    assert missing_csrf_prepare.status_code == 403
    assert missing_csrf_prepare.json()["detail"] == "origin header is required"
    assert read_only_prepare.status_code == 403
    assert read_only_prepare.json()["detail"] == "mutations are disabled"
    assert active_job_prepare.status_code == 409
    assert active_job_prepare.json()["detail"] == "an apply job is already running"


def test_plan_endpoint_rejects_unauthenticated_requests(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "setup required"


def test_plan_endpoint_requires_csrf_origin_headers(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.post("/api/v1/plans", json={"line_numbers": [1]})

    assert response.status_code == 403
    assert response.json()["detail"] == "origin header is required"


def test_plan_endpoint_wraps_config_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = "plan-secret-token"

    def invalid_config(_settings):
        raise ConfigError(
            f"failed to parse {tmp_path / 'state' / 'config.env'} with {secret}"
        )

    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_TOKEN": secret,
        },
    )
    monkeypatch.setattr(plans_module, "_effective_config_loader", invalid_config)

    response = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=_csrf_headers(client),
    )
    detail = response.json()["detail"]

    assert response.status_code == 500
    assert detail.startswith("could not create plan: ")
    assert secret not in detail
    assert str(tmp_path) not in detail
    assert "<redacted>" in detail
    assert "[REDACTED_PATH]" in detail


def test_plan_endpoint_returns_selected_dry_run_without_mutation(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    wud_file = tmp_path / "state" / "images.todo"
    db_path = tmp_path / "state" / "wud.sqlite"
    log_dir = tmp_path / "state" / "logs"
    original = "repo/app:latest\nrepo/db:latest\n"
    wud_file.write_text(original, encoding="utf-8")
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [
            ("app", "repo/app:latest", "cid-app"),
            ("db", "repo/db:latest", "cid-db"),
        ],
    )
    compose_before = (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")

    response = client.post(
        "/api/v1/plans",
        json={"line_numbers": [2]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["can_apply"] is False
    assert body["plan_id"]
    assert body["status"] == "ready"
    assert body["selected_line_numbers"] == [2]
    assert body["summary"]["target_count"] == 1
    assert body["summary"]["matched_target_count"] == 1
    assert [target["line_no"] for target in body["targets"]] == [2]
    assert body["stacks"][0]["name"] == "stack"
    assert body["stacks"][0]["services"] == ["db"]
    assert body["stacks"][0]["lines"][0]["service"] == "db"
    assert body["stacks"][0]["actions"][0]["kind"] == "pull"
    assert body["stacks"][0]["actions"][0]["args"][-1] == "db"
    assert body["issues"] == []
    assert wud_file.read_text(encoding="utf-8") == original
    assert (compose_dir / "docker-compose.yml").read_text(encoding="utf-8") == compose_before
    assert not db_path.exists()
    assert not log_dir.exists()
    calls = _fake_docker_calls(fake_root)
    assert " pull " not in calls
    assert " up -d " not in calls


def test_plan_endpoint_returns_apply_preflight_summary(tmp_path: Path) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "TRUENAS_STATUS_CHECK": "false",
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

    response = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    preflight = body["apply_preflight"]
    assert body["can_apply"] is True
    assert preflight["ok"] is True
    assert preflight["failures"] == 0
    assert preflight["warnings"] == 0
    assert [check["code"] for check in preflight["checks"]] == [
        "docker-reachable",
        "compose-renders",
        "wud-file-writable",
        "database-ready",
        "logs-writable",
        "mutations-enabled",
        "bind-mounts-safe",
        "selected-services-matched",
    ]
    assert {check["status"] for check in preflight["checks"]} == {"PASS"}


def test_plan_apply_preflight_ignores_unselected_compose_render_failure(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "TRUENAS_STATUS_CHECK": "false",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:latest\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "selected",
        [("app", "repo/app:latest", "cid-app")],
    )
    _make_fake_stack(
        tmp_path,
        fake_root,
        "broken",
        [("ignored", "repo/ignored:latest", "cid-ignored")],
    )
    (fake_root / "stacks" / "broken" / "config_fail").write_text(
        "",
        encoding="utf-8",
    )
    (fake_root / "stacks" / "broken" / "config_stderr").write_text(
        "broken compose config\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    checks = {check["code"]: check for check in body["apply_preflight"]["checks"]}
    assert body["status"] == "ready"
    assert body["can_apply"] is True
    assert checks["compose-renders"]["status"] == "PASS"
    assert "broken compose config" not in json.dumps(body["apply_preflight"])


def test_plan_endpoint_normalizes_digest_line_when_pinning_disabled(
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
    wud_file.write_text("repo/app:latest@sha256:new\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )

    response = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    line = body["stacks"][0]["lines"][0]
    assert body["digest_pin_updates"] is False
    assert body["stacks"][0]["digest_pin_updates"] == []
    assert body["stacks"][0]["digest_unpin_updates"] == []
    assert line["image"] == "repo/app:latest@sha256:new"
    assert line["resolved_image"] == "repo/app:latest"
    assert line["target_image"] == "repo/app:latest"
    assert line["action"] == "update"
    assert not any(
        action["kind"] == "compose-digest-pin"
        for action in body["stacks"][0]["actions"]
    )


def test_plan_endpoint_uses_known_image_provenance_for_digest_unpin(
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
    _seed_known_digest_provenance(tmp_path)
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:latest@sha256:new\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app@sha256:old", "cid-app")],
    )

    response = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    stack = body["stacks"][0]
    line = stack["lines"][0]
    unpin = stack["digest_unpin_updates"][0]
    assert body["status"] == "ready"
    assert body["can_apply"] is True
    assert stack["digest_pin_updates"] == []
    assert unpin["source_image"] == "repo/app@sha256:old"
    assert unpin["resolved_tag"] == "latest"
    assert unpin["tag_image"] == "repo/app:latest"
    assert unpin["current_digest"] == "sha256:old"
    assert unpin["target_digest"] == "sha256:new"
    assert unpin["services"] == ["app"]
    assert stack["actions"][0]["kind"] == "compose-digest-unpin"
    assert line["action"] == "digest-unpin"
    assert line["target_image"] == "repo/app:latest"
    assert line["digest_provenance"]["target_digest"] == "sha256:new"
    assert line["digest_provenance"]["provenance_source"] == "plan"


def test_plan_endpoint_treats_digest_provenance_lookup_failure_as_best_effort(
    tmp_path: Path,
    monkeypatch,
    caplog,
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

    def fail_connect(_settings):
        raise DatabaseError("database schema version 1 requires migration")

    monkeypatch.setattr(
        plans_module.web_database,
        "connect_readonly_db",
        fail_connect,
    )
    caplog.set_level("WARNING", logger="wud_updater.web_database")

    response = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["issues"] == []
    assert any(
        "failed to read digest provenance from database" in record.message
        for record in caplog.records
    )


def test_known_digest_provenance_closes_connection_after_query_failure(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )

    class FailingConnection:
        closed = False

        def execute(self, _query: str):
            raise DatabaseError("known_images table is missing")

        def close(self) -> None:
            self.closed = True

    conn = FailingConnection()
    monkeypatch.setattr(
        plans_module.web_database,
        "connect_readonly_db",
        lambda _settings: conn,
    )
    caplog.set_level("WARNING", logger="wud_updater.web_database")

    result = plans_module.web_database.known_digest_provenance_by_service(
        client.app.state.web_settings,
    )

    assert result == {}
    assert conn.closed is True
    assert any(
        "failed to read digest provenance from database" in record.message
        for record in caplog.records
    )


def test_plan_endpoint_blocks_conflicting_digest_unpin_db_provenance(
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
    _seed_known_digest_provenance(
        tmp_path,
        image="repo/app@sha256:other",
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:latest@sha256:new\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app@sha256:old", "cid-app")],
    )

    response = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["can_apply"] is False
    assert any(
        issue["code"] == "digest-unpin-db-provenance-conflict"
        for issue in body["issues"]
    )


def test_plan_endpoint_returns_digest_pin_label_rewrite_details(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_DIGEST_PIN_UPDATES": "true",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
    _write_fake_manifest(
        fake_root,
        "docker.io/repo/app:2.0",
        _manifest_index_digest("sha256:index", "sha256:child"),
    )
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:1.0", "cid-app")],
    )
    compose_file = compose_dir / "docker-compose.yml"
    compose_file.write_text(
        compose_file.read_text(encoding="utf-8").replace(
            "  app:\n    image: repo/app:1.0\n",
            "  app:\n"
            "    labels:\n"
            "      - wud.tag.include=^beta|^stable\n"
            "    image: repo/app:1.0\n",
        ),
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1], "allow_tag_updates": True},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    issue = next(
        item
        for item in body["issues"]
        if item["code"] == "compose-digest-pin-label-rewrite-unapproved"
    )
    assert body["status"] == "blocked"
    assert body["can_apply"] is False
    assert issue["stack"] == "stack"
    assert issue["service"] == "app"
    assert issue["details"]["current_label_value"] == "^beta|^stable"
    assert issue["details"]["planned_tag"] == "2.0"
    assert issue["details"]["proposed_label_value"] == "^2\\.0$$"
    assert issue["details"]["proposed_label_regex"] == "^2\\.0$"
    assert issue["details"]["compose_file"] == "docker-compose.yml"


def test_plan_endpoint_accepts_digest_pin_label_rewrite_approval(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_DIGEST_PIN_UPDATES": "true",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
    _write_fake_manifest(
        fake_root,
        "docker.io/repo/app:2.0",
        _manifest_index_digest("sha256:index", "sha256:child"),
    )
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:1.0", "cid-app")],
    )
    compose_file = compose_dir / "docker-compose.yml"
    compose_file.write_text(
        compose_file.read_text(encoding="utf-8").replace(
            "  app:\n    image: repo/app:1.0\n",
            "  app:\n"
            "    labels:\n"
            "      - wud.tag.include=^beta|^stable\n"
            "    image: repo/app:1.0\n",
        ),
        encoding="utf-8",
    )
    headers = _csrf_headers(client)
    initial = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1], "allow_tag_updates": True},
        headers=headers,
    ).json()
    issue = next(
        item
        for item in initial["issues"]
        if item["code"] == "compose-digest-pin-label-rewrite-unapproved"
    )
    approval = {
        "stack": issue["details"]["stack"],
        "service": issue["details"]["service"],
        "label_key": issue["details"]["label_key"],
        "current_label_value": issue["details"]["current_label_value"],
        "planned_tag": issue["details"]["planned_tag"],
        "proposed_label_value": issue["details"]["proposed_label_value"],
    }

    response = client.post(
        "/api/v1/plans",
        json={
            "line_numbers": [1],
            "allow_tag_updates": True,
            "digest_pin_label_rewrite_approvals": [approval],
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["can_apply"] is True
    assert not [
        item
        for item in body["issues"]
        if item["code"] == "compose-digest-pin-label-rewrite-unapproved"
    ]
    rewrite = body["stacks"][0]["digest_pin_updates"][0]["label_rewrites"][0]
    assert rewrite["current_label_value"] == "^beta|^stable"
    assert rewrite["proposed_label_value"] == "^2\\.0$$"
    assert rewrite["approved"] is True
    assert rewrite["reason"] == "approved"
    assert body["plan_id"] != initial["plan_id"]


def test_plan_endpoint_returns_unmatched_cleanup_preview(
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
    wud_file.write_text("homarr-labs/homarr:latest\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "active",
        [("app", "repo/app:latest", "cid-app")],
    )
    archived = tmp_path / "docker" / "homarr" / "docker-compose.archive.yml"
    archived.parent.mkdir(parents=True)
    archived.write_text(
        "services:\n  homarr:\n    image: ghcr.io/homarr-labs/homarr:latest\n",
        encoding="utf-8",
    )
    with (fake_root / "containers.tsv").open("a", encoding="utf-8") as file:
        file.write("homarr\tghcr.io/homarr-labs/homarr:latest\n")
    _write_fake_container_labels(
        fake_root,
        "homarr",
        {
            "com.docker.compose.project": "homarr",
            "com.docker.compose.project.working_dir": str(tmp_path / "docker" / "homarr"),
            "com.docker.compose.project.config_files": str(
                tmp_path / "docker" / "homarr" / "docker-compose.yml"
            ),
            "com.docker.compose.service": "homarr",
        },
    )

    response = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["can_apply"] is False
    assert body["issues"][0]["code"] == "compose-label-active-file-missing"
    assert "homarr/docker-compose.archive.yml" in body["issues"][0]["message"]
    assert body["issues"][0]["hint"]
    assert body["cleanup"]["can_remove_unmatched"] is True
    assert body["cleanup"]["cleanup_id"]
    assert body["cleanup"]["items"][0]["line_no"] == 1
    assert body["cleanup"]["items"][0]["raw"] == "homarr-labs/homarr:latest"
    cleanup_diagnostic = body["cleanup"]["items"][0]["diagnostic"]
    assert cleanup_diagnostic["stack"] == "homarr"
    assert (
        "The active Compose file was renamed to an archived or nonstandard filename."
        in cleanup_diagnostic["details"]["possible_reasons"]
    )
    assert (
        "Update Docker base or ignore paths if the stack moved."
        in cleanup_diagnostic["details"]["recommended_actions"]
    )
    assert str(tmp_path) not in json.dumps(body["cleanup"])
    assert wud_file.read_text(encoding="utf-8") == "homarr-labs/homarr:latest\n"


def test_plan_endpoint_skips_tag_updates_unless_allowed(tmp_path: Path) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:1.0", "cid-app")],
    )
    compose_before = (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")
    headers = _csrf_headers(client)

    skipped = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    )
    allowed = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1], "allow_tag_updates": True},
        headers=headers,
    )

    assert skipped.status_code == 200
    skipped_body = skipped.json()
    assert skipped_body["status"] == "empty"
    assert skipped_body["skipped"][0]["reason"] == "tag-updates-disabled"
    assert skipped_body["stacks"] == []
    assert allowed.status_code == 200
    allowed_body = allowed.json()
    assert allowed_body["status"] == "ready"
    assert allowed_body["stacks"][0]["tag_updates"][0]["old_image"] == "repo/app:1.0"
    assert allowed_body["stacks"][0]["tag_updates"][0]["new_image"] == "repo/app:2.0"
    assert allowed_body["stacks"][0]["lines"][0]["action"] == "tag-update"
    assert (compose_dir / "docker-compose.yml").read_text(encoding="utf-8") == compose_before
    assert "manifest inspect repo/app:2.0" in _fake_docker_calls(fake_root)
    assert "repo/app:1.0 tag=2.0\n" == wud_file.read_text(encoding="utf-8")


def test_plan_endpoint_accepts_digest_pin_for_tagged_digest_only_latest(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_DIGEST_PIN_UPDATES": "true",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:latest@sha256:child\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )
    _write_fake_manifest(
        fake_root,
        "docker.io/repo/app:latest",
        _manifest_index_digest("sha256:index", "sha256:child"),
    )

    response = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["issues"] == []
    assert body["stacks"][0]["lines"][0]["action"] == "digest-pin"
    assert body["stacks"][0]["lines"][0]["target_image"] == "repo/app@sha256:child"
    digest_pin = body["stacks"][0]["digest_pin_updates"][0]
    assert digest_pin["source_image"] == "repo/app:latest"
    assert digest_pin["resolved_tag"] == "latest"
    assert digest_pin["watch_tag"] == "latest"
    assert digest_pin["planned_digest"] == "sha256:child"
    assert digest_pin["final_image"] == "repo/app@sha256:child"
    assert "repo/app:latest@sha256:child\n" == wud_file.read_text(encoding="utf-8")


def test_plan_endpoint_accepts_tag_overrides(tmp_path: Path) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:1.0 tag=wrong\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:1.0", "cid-app")],
    )

    response = client.post(
        "/api/v1/plans",
        json={
            "line_numbers": [1],
            "allow_tag_updates": True,
            "tag_overrides": [{"line_no": 1, "tag": "3.0"}],
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["stacks"][0]["tag_updates"][0]["new_image"] == "repo/app:3.0"
    assert body["stacks"][0]["lines"][0]["desired_tag"] == "3.0"
    assert "manifest inspect repo/app:3.0" in _fake_docker_calls(fake_root)


def test_plan_endpoint_rejects_invalid_tag_overrides(tmp_path: Path) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:latest\nrepo/db:1.0 tag=2.0\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [
            ("app", "repo/app:latest", "cid-app"),
            ("db", "repo/db:1.0", "cid-db"),
        ],
    )
    headers = _csrf_headers(client)

    invalid_tag = client.post(
        "/api/v1/plans",
        json={
            "line_numbers": [2],
            "allow_tag_updates": True,
            "tag_overrides": [{"line_no": 2, "tag": "bad:value"}],
        },
        headers=headers,
    )
    non_selected = client.post(
        "/api/v1/plans",
        json={
            "line_numbers": [2],
            "allow_tag_updates": True,
            "tag_overrides": [{"line_no": 1, "tag": "3.0"}],
        },
        headers=headers,
    )
    non_tag = client.post(
        "/api/v1/plans",
        json={
            "line_numbers": [1],
            "allow_tag_updates": True,
            "tag_overrides": [{"line_no": 1, "tag": "3.0"}],
        },
        headers=headers,
    )

    assert invalid_tag.status_code == 422
    assert "invalid tag" in invalid_tag.json()["detail"]
    assert non_selected.status_code == 422
    assert "selected WUD tag update lines" in non_selected.json()["detail"]
    assert non_tag.status_code == 422
    assert "does not target a tag update" in non_tag.json()["detail"]


def test_plan_endpoint_rejects_duplicate_digest_pin_label_rewrite_approvals(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    (tmp_path / "state" / "images.todo").write_text(
        "repo/app:1.0 tag=2.0\n", encoding="utf-8"
    )
    approval = {
        "stack": "stack",
        "service": "app",
        "label_key": "wud.tag.include",
        "current_label_value": "^beta|^stable",
        "planned_tag": "2.0",
        "proposed_label_value": "^2\\.0$$",
    }

    response = client.post(
        "/api/v1/plans",
        json={
            "line_numbers": [1],
            "digest_pin_label_rewrite_approvals": [approval, approval],
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 422
    assert "duplicate" in response.json()["detail"]


def test_plan_endpoint_rejects_non_include_label_key_in_approval(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    (tmp_path / "state" / "images.todo").write_text(
        "repo/app:1.0 tag=2.0\n", encoding="utf-8"
    )
    approval = {
        "stack": "stack",
        "service": "app",
        "label_key": "wud.tag.exclude",
        "current_label_value": "^beta|^stable",
        "planned_tag": "2.0",
        "proposed_label_value": "^2\\.0$$",
    }

    response = client.post(
        "/api/v1/plans",
        json={
            "line_numbers": [1],
            "digest_pin_label_rewrite_approvals": [approval],
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 422
    assert "wud.tag.include" in response.json()["detail"]


def test_plan_endpoint_rejects_invalid_planned_tag_in_approval(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    (tmp_path / "state" / "images.todo").write_text(
        "repo/app:1.0 tag=2.0\n", encoding="utf-8"
    )
    approval = {
        "stack": "stack",
        "service": "app",
        "label_key": "wud.tag.include",
        "current_label_value": "^beta|^stable",
        "planned_tag": "bad:tag",
        "proposed_label_value": "^2\\.0$$",
    }

    response = client.post(
        "/api/v1/plans",
        json={
            "line_numbers": [1],
            "digest_pin_label_rewrite_approvals": [approval],
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 422
    assert "invalid planned tag" in response.json()["detail"]


def test_apply_endpoint_rejects_mixed_plan_with_skipped_lines_without_mutation(
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
    original = "repo/app:latest\nrepo/worker:1.0 tag=2.0\n"
    wud_file.write_text(original, encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [
            ("app", "repo/app:latest", "cid-app"),
            ("worker", "repo/worker:1.0", "cid-worker"),
        ],
    )
    headers = _csrf_headers(client)

    plan_response = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1, 2]},
        headers=headers,
    )
    plan = plan_response.json()
    apply_response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1, 2],
            "confirmation": "apply",
        },
        headers=headers,
    )

    assert plan_response.status_code == 200
    assert plan["status"] == "blocked"
    assert plan["can_apply"] is False
    assert plan["summary"]["matched_target_count"] == 1
    assert plan["skipped"][0]["line_no"] == 2
    assert plan["skipped"][0]["reason"] == "tag-updates-disabled"
    assert apply_response.status_code == 409
    assert apply_response.json()["detail"] == "plan is not ready to apply"
    assert wud_file.read_text(encoding="utf-8") == original
    calls = _fake_docker_calls(fake_root)
    assert " pull " not in calls
    assert " up -d " not in calls


def test_plan_endpoint_rejects_invalid_or_non_actionable_lines(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("# ignored\nrepo/app:latest\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )
    headers = _csrf_headers(client)

    zero = client.post(
        "/api/v1/plans",
        json={"line_numbers": [0]},
        headers=headers,
    )
    comment = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    )
    missing = client.post(
        "/api/v1/plans",
        json={"line_numbers": [3]},
        headers=headers,
    )

    assert zero.status_code == 422
    assert comment.status_code == 422
    assert "actionable WUD target lines" in comment.json()["detail"]
    assert missing.status_code == 422
    assert "actionable WUD target lines" in missing.json()["detail"]


def test_apply_endpoint_rejects_unauthenticated_requests(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_MUTATIONS_ENABLED": "true"})

    response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": "plan",
            "line_numbers": [1],
            "confirmation": "apply",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "setup required"


def test_apply_endpoint_requires_csrf_origin_headers(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true", "WUD_WEB_MUTATIONS_ENABLED": "true"},
    )

    missing = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": "plan",
            "line_numbers": [1],
            "confirmation": "apply",
        },
    )
    csrf_response = client.get("/api/v1/auth/csrf")
    bad_origin = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": "plan",
            "line_numbers": [1],
            "confirmation": "apply",
        },
        headers={
            "Origin": "http://evil.example",
            "x-wud-csrf-token": csrf_response.json()["csrf_token"],
        },
    )

    assert missing.status_code == 403
    assert missing.json()["detail"] == "origin header is required"
    assert bad_origin.status_code == 403
    assert bad_origin.json()["detail"] == "origin is not allowed"


def test_apply_endpoint_wraps_config_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = "apply-secret-token"

    def invalid_config(_settings):
        raise ConfigError(
            f"failed to parse {tmp_path / 'state' / 'config.env'} with {secret}"
        )

    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_TOKEN": secret,
        },
    )
    monkeypatch.setattr(plans_module, "_effective_config_loader", invalid_config)

    response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": "plan",
            "line_numbers": [1],
            "confirmation": "apply",
        },
        headers=_csrf_headers(client),
    )
    detail = response.json()["detail"]

    assert response.status_code == 409
    assert detail.startswith("could not revalidate plan: ")
    assert secret not in detail
    assert str(tmp_path) not in detail
    assert "<redacted>" in detail
    assert "[REDACTED_PATH]" in detail
    assert not lock_dir_for(tmp_path / "state" / "images.todo").exists()


def test_apply_endpoint_rejects_read_only_mode(tmp_path: Path) -> None:
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
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()

    response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1],
            "confirmation": "apply",
        },
        headers=headers,
    )

    assert plan["can_apply"] is False
    preflight_checks = {
        check["code"]: check for check in plan["apply_preflight"]["checks"]
    }
    assert plan["apply_preflight"]["ok"] is False
    assert preflight_checks["mutations-enabled"]["status"] == "FAIL"
    assert "WUD_WEB_MUTATIONS_ENABLED=true" in preflight_checks["mutations-enabled"]["detail"]
    assert response.status_code == 403
    assert response.json()["detail"] == "mutations are disabled"
    assert " pull " not in _fake_docker_calls(fake_root)


def test_apply_endpoint_rejects_stale_plan_without_mutation(tmp_path: Path) -> None:
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
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()
    wud_file.write_text("repo/app:latest\n# changed\n", encoding="utf-8")

    response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1],
            "confirmation": "apply",
        },
        headers=headers,
    )

    assert plan["can_apply"] is True
    assert response.status_code == 409
    assert response.json()["detail"] == "plan is stale"
    assert " pull " not in _fake_docker_calls(fake_root)


def test_apply_endpoint_rejects_active_self_update(tmp_path: Path) -> None:
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
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()
    client.app.state.web_self_update_running = True

    response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1],
            "confirmation": "apply",
        },
        headers=headers,
    )

    assert plan["can_apply"] is True
    assert response.status_code == 409
    assert response.json()["detail"] == "self-update is already running"
    assert " pull " not in _fake_docker_calls(fake_root)


def test_apply_endpoint_rejects_empty_or_blocked_plan(tmp_path: Path) -> None:
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
    wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:1.0", "cid-app")],
    )
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()

    response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1],
            "confirmation": "apply",
        },
        headers=headers,
    )

    assert plan["status"] == "empty"
    assert plan["can_apply"] is False
    assert response.status_code == 409
    assert response.json()["detail"] == "plan is not ready to apply"
    assert " pull " not in _fake_docker_calls(fake_root)


def test_apply_endpoint_rejects_failed_apply_preflight_without_mutation(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    secret = "github-token-secret"
    log_dir = tmp_path / secret
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "GITHUB_TOKEN": secret,
            "WUD_LOG_DIR": str(log_dir),
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:latest\n", encoding="utf-8")
    log_dir.write_text("not a directory\n", encoding="utf-8")
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

    response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1],
            "confirmation": "apply",
        },
        headers=headers,
    )

    checks = {check["code"]: check for check in plan["apply_preflight"]["checks"]}
    assert plan["status"] == "ready"
    assert plan["can_apply"] is False
    assert checks["logs-writable"]["status"] == "FAIL"
    assert "not a directory" in checks["logs-writable"]["detail"]
    assert secret not in json.dumps(plan["apply_preflight"])
    assert "<redacted>" in checks["logs-writable"]["detail"]
    assert response.status_code == 409
    assert response.json()["detail"] == "apply preflight failed"
    calls = _fake_docker_calls(fake_root)
    assert " pull " not in calls
    assert " up -d " not in calls


def test_apply_endpoint_applies_digest_unpin_plan_and_records_provenance(
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
    _seed_known_digest_provenance(tmp_path)
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:latest@sha256:new\n", encoding="utf-8")
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app@sha256:old", "cid-app")],
    )
    compose_file = compose_dir / "docker-compose.yml"
    compose_file.write_text(
        "services:\n"
        "  app:\n"
        "    # wud-updater.resolved-tag=latest\n"
        "    image: repo/app@sha256:old\n"
        "    labels:\n"
        "      - wud.tag.include=^latest$\n",
        encoding="utf-8",
    )
    _write_fake_image_after_pull(
        fake_root,
        "repo/app:latest",
        "sha256:new-id",
        "sha256:new",
    )
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()

    apply_response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1],
            "confirmation": "apply",
        },
        headers=headers,
    )
    job = _wait_apply_job(client, apply_response.json()["job_id"])

    assert plan["status"] == "ready"
    assert plan["stacks"][0]["digest_unpin_updates"][0]["tag_image"] == "repo/app:latest"
    assert apply_response.status_code == 202
    assert job["status"] == "success"
    rendered = compose_file.read_text(encoding="utf-8")
    assert "image: repo/app:latest" in rendered
    assert "wud-updater.resolved-tag" not in rendered
    assert "wud.tag.include=^latest$" in rendered
    assert wud_file.read_text(encoding="utf-8") == ""
    calls = _fake_docker_calls(fake_root)
    assert " pull app" in calls
    assert " up -d --remove-orphans --no-deps" in calls
    assert " app" in calls
    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        pending = conn.execute("SELECT * FROM pending_updates").fetchone()
        event = conn.execute("SELECT * FROM update_events").fetchone()
        known = conn.execute("SELECT * FROM known_images WHERE service_key = 'stack/app'").fetchone()
    assert pending["status"] == "resolved"
    assert pending["digest_source_image"] == "repo/app@sha256:old"
    assert pending["digest_resolved_tag"] == "latest"
    assert pending["digest_target_digest"] == "sha256:new"
    assert event["image"] == "repo/app@sha256:old"
    assert event["target_image"] == "repo/app:latest"
    assert event["old_digest"] == "sha256:old"
    assert event["new_digest"] == "sha256:new"
    assert known["image"] == "repo/app:latest"
    assert known["digest_source_image"] == "repo/app@sha256:old"
    assert known["digest_target_digest"] == "sha256:new"
    assert known["digest_provenance_source"] == "apply"


def test_apply_endpoint_requires_and_uses_digest_pin_label_rewrite_approval(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    target_image = "repo/app:2.0"
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_DIGEST_PIN_UPDATES": "true",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
    _write_fake_manifest(
        fake_root,
        "docker.io/repo/app:2.0",
        _manifest_index_digest("sha256:index", "sha256:child"),
    )
    _write_fake_image_after_pull(
        fake_root,
        target_image,
        "sha256:config",
        "sha256:index",
    )
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:1.0", "cid-app")],
    )
    compose_file = compose_dir / "docker-compose.yml"
    compose_file.write_text(
        compose_file.read_text(encoding="utf-8").replace(
            "  app:\n    image: repo/app:1.0\n",
            "  app:\n"
            "    labels:\n"
            "      - wud.tag.include=^beta|^stable\n"
            "    image: repo/app:1.0\n",
        ),
        encoding="utf-8",
    )
    headers = _csrf_headers(client)
    initial = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1], "allow_tag_updates": True},
        headers=headers,
    ).json()
    issue = next(
        item
        for item in initial["issues"]
        if item["code"] == "compose-digest-pin-label-rewrite-unapproved"
    )
    approval = {
        "stack": issue["details"]["stack"],
        "service": issue["details"]["service"],
        "label_key": issue["details"]["label_key"],
        "current_label_value": issue["details"]["current_label_value"],
        "planned_tag": issue["details"]["planned_tag"],
        "proposed_label_value": issue["details"]["proposed_label_value"],
    }
    plan = client.post(
        "/api/v1/plans",
        json={
            "line_numbers": [1],
            "allow_tag_updates": True,
            "digest_pin_label_rewrite_approvals": [approval],
        },
        headers=headers,
    ).json()

    stale_apply = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1],
            "allow_tag_updates": True,
            "confirmation": "apply",
        },
        headers=headers,
    )
    apply_response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1],
            "allow_tag_updates": True,
            "digest_pin_label_rewrite_approvals": [approval],
            "confirmation": "apply",
        },
        headers=headers,
    )
    job = _wait_apply_job(client, apply_response.json()["job_id"])

    assert stale_apply.status_code == 409
    assert stale_apply.json()["detail"] == "plan is stale"
    assert apply_response.status_code == 202
    assert job["status"] == "success"
    content = compose_file.read_text(encoding="utf-8")
    assert "# wud-updater.resolved-tag=2.0" in content
    assert "image: repo/app@sha256:index" in content
    assert "wud.tag.include=^2\\.0$$" in content


def test_apply_endpoint_runs_existing_updater_and_records_audit(
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
    original = "repo/app:latest\nrepo/db:latest\n"
    wud_file.write_text(original, encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [
            ("app", "repo/app:latest", "cid-app"),
            ("db", "repo/db:latest", "cid-db"),
        ],
    )
    image_state = fake_root / "images" / "repo_app_latest.id"
    image_state.write_text("old\n", encoding="utf-8")
    (fake_root / "images" / "repo_app_latest.after_id").write_text(
        "new\n",
        encoding="utf-8",
    )
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()

    apply_response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1],
            "confirmation": "apply",
        },
        headers=headers,
    )
    job = _wait_apply_job(client, apply_response.json()["job_id"])

    assert apply_response.status_code == 202
    assert apply_response.json()["status"] == "queued"
    assert plan["can_apply"] is True
    assert job["status"] == "success"
    assert job["run_id"]
    assert job["selected_line_numbers"] == [1]
    assert wud_file.read_text(encoding="utf-8") == "repo/db:latest\n"
    calls = _fake_docker_calls(fake_root)
    assert "compose -f docker-compose.yml pull app" in calls
    assert "compose -f docker-compose.yml stop app" in calls
    assert "compose -f docker-compose.yml up -d --remove-orphans --no-deps app" in calls

    detail = client.get(f"/api/v1/runs/{job['run_id']}").json()
    assert detail["metadata"]["source"] == "webui"
    assert detail["metadata"]["plan_id"] == plan["plan_id"]
    assert detail["metadata"]["selected_line_numbers"] == [1]
    assert detail["pending_updates"][0]["line_no"] == 1
    assert detail["pending_updates"][0]["status"] == "resolved"
    assert not lock_dir_for(wud_file).exists()


def test_apply_endpoint_passes_tag_overrides_to_updater(tmp_path: Path) -> None:
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
    wud_file.write_text("repo/app:1.0 tag=wrong\n", encoding="utf-8")
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:1.0", "cid-app")],
    )
    (fake_root / "images" / "repo_app_3.0.after_id").write_text(
        "new\n",
        encoding="utf-8",
    )
    headers = _csrf_headers(client)
    payload = {
        "line_numbers": [1],
        "allow_tag_updates": True,
        "tag_overrides": [{"line_no": 1, "tag": "3.0"}],
    }
    plan = client.post(
        "/api/v1/plans",
        json=payload,
        headers=headers,
    ).json()

    apply_response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            **payload,
            "confirmation": "apply",
        },
        headers=headers,
    )
    job = _wait_apply_job(client, apply_response.json()["job_id"])

    assert apply_response.status_code == 202
    assert job["status"] == "success"
    assert wud_file.read_text(encoding="utf-8") == ""
    assert "image: repo/app:3.0" in (
        compose_dir / "docker-compose.yml"
    ).read_text(encoding="utf-8")
    calls = _fake_docker_calls(fake_root)
    assert "manifest inspect repo/app:3.0" in calls
    assert "compose -f docker-compose.yml pull app" in calls


def test_apply_endpoint_rejects_changed_tag_override_as_stale(
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
    wud_file.write_text("repo/app:1.0 tag=wrong\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:1.0", "cid-app")],
    )
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={
            "line_numbers": [1],
            "allow_tag_updates": True,
            "tag_overrides": [{"line_no": 1, "tag": "3.0"}],
        },
        headers=headers,
    ).json()

    response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1],
            "allow_tag_updates": True,
            "tag_overrides": [{"line_no": 1, "tag": "2.0"}],
            "confirmation": "apply",
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "plan is stale"
    assert " pull " not in _fake_docker_calls(fake_root)


def test_apply_endpoint_holds_wud_lock_for_worker_handoff(
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
    observed: dict[str, object] = {}

    def fake_run(runner: object) -> int:
        environ = getattr(runner, "environ")
        observed["lock_flag"] = environ.get("WUD_LOCK_HELD_BY_PARENT")
        observed["lock_exists"] = lock_dir_for(wud_file).is_dir()
        contender = DirectoryLock(wud_file, timeout_seconds=0)
        try:
            contender.acquire()
        except WudLockError:
            observed["contended"] = True
        else:
            contender.close()
            observed["contended"] = False
        return 0

    monkeypatch.setattr(web_jobs.UpdateFromWudRunner, "run", fake_run)
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()

    apply_response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1],
            "confirmation": "apply",
        },
        headers=headers,
    )
    job = _wait_apply_job(client, apply_response.json()["job_id"])

    assert apply_response.status_code == 202
    assert job["status"] == "success"
    assert observed == {
        "lock_flag": "1",
        "lock_exists": True,
        "contended": True,
    }
    assert not lock_dir_for(wud_file).exists()
    calls = _fake_docker_calls(fake_root)
    assert " pull " not in calls
    assert " up -d " not in calls


def test_apply_endpoint_releases_wud_lock_when_runner_raises(
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

    def fake_run(_runner: object) -> int:
        assert lock_dir_for(wud_file).is_dir()
        raise RuntimeError("runner exploded")

    monkeypatch.setattr(web_jobs.UpdateFromWudRunner, "run", fake_run)
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()

    apply_response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1],
            "confirmation": "apply",
        },
        headers=headers,
    )
    job = _wait_apply_job(client, apply_response.json()["job_id"])

    assert apply_response.status_code == 202
    assert job["status"] == "failure"
    assert job["error"] == "runner exploded"
    assert not lock_dir_for(wud_file).exists()
    calls = _fake_docker_calls(fake_root)
    assert " pull " not in calls
    assert " up -d " not in calls


def test_apply_endpoint_rejects_existing_wud_lock_without_queueing_job(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_LOCK_TIMEOUT": "0",
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
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()
    external_lock = DirectoryLock(wud_file, timeout_seconds=0)
    external_lock.acquire()
    try:
        response = client.post(
            "/api/v1/jobs",
            json={
                "plan_id": plan["plan_id"],
                "line_numbers": [1],
                "confirmation": "apply",
            },
            headers=headers,
        )
    finally:
        external_lock.close()

    assert response.status_code == 409
    assert response.json()["detail"] == "WUD file is locked"
    assert client.app.state.web_apply_jobs == {}
    calls = _fake_docker_calls(fake_root)
    assert " pull " not in calls
    assert " up -d " not in calls


def test_apply_endpoint_rejects_concurrent_jobs(tmp_path: Path) -> None:
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
    hook = fake_root / "post-pull-hook"
    hook.write_text("#!/usr/bin/env bash\nsleep 0.3\n", encoding="utf-8")
    hook.chmod(0o755)
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()
    payload = {
        "plan_id": plan["plan_id"],
        "line_numbers": [1],
        "confirmation": "apply",
    }

    first = client.post("/api/v1/jobs", json=payload, headers=headers)
    second = client.post("/api/v1/jobs", json=payload, headers=headers)
    job = _wait_apply_job(client, first.json()["job_id"])

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"] == "an apply job is already running"
    assert job["status"] == "success"


def test_apply_endpoint_reports_updater_failure_and_preserves_line(
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
    original = "repo/app:latest\n"
    wud_file.write_text(original, encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )
    (fake_root / "stacks" / "stack" / "pull_fail").write_text("", encoding="utf-8")
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/plans",
        json={"line_numbers": [1]},
        headers=headers,
    ).json()

    apply_response = client.post(
        "/api/v1/jobs",
        json={
            "plan_id": plan["plan_id"],
            "line_numbers": [1],
            "confirmation": "apply",
        },
        headers=headers,
    )
    job = _wait_apply_job(client, apply_response.json()["job_id"])

    assert apply_response.status_code == 202
    assert job["status"] == "failure"
    assert job["run_id"]
    assert "updater exited with status 1" in str(job["error"])
    assert wud_file.read_text(encoding="utf-8") == original
    detail = client.get(f"/api/v1/runs/{job['run_id']}").json()
    assert detail["status"] == "failure"
    assert detail["pending_updates"][0]["status"] == "failed"


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

from __future__ import annotations
import sqlite3
import stat
from pathlib import Path
from wud_updater import web as web_module
from wud_updater.locks import lock_dir_for
from tests.web_test_helpers import (
    _client,
    _csrf_headers,
    _fake_docker_env,
    _make_fake_stack,
    _write_fake_container_labels,
    _fake_docker_calls,
    _assert_pending_grouping_did_not_mutate,
)


def test_pending_endpoint_reads_wud_file_without_mutation(tmp_path: Path) -> None:
    wud_file = tmp_path / "state" / "images.todo"
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    original = "# ignored\nnginx:1.25 tag=1.26\nredis:latest@sha256:abc\n"
    wud_file.write_text(original, encoding="utf-8")

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["count"] == 2
    assert body["items"][0]["image"] == "nginx:1.25"
    assert body["items"][0]["current_tag"] == "1.25"
    assert body["items"][0]["desired_tag"] == "1.26"
    assert body["items"][1]["current_tag"] == "latest"
    assert body["items"][1]["digest"] == "sha256:abc"
    assert body["grouping"]["status"] == "unavailable"
    assert body["grouping"]["groups"] == []
    assert [item["line_no"] for item in body["grouping"]["unmatched"]] == [2, 3]
    assert body["grouping"]["unmatched"][0]["action"] == "tag-update"
    assert body["grouping"]["unmatched"][1]["action"] == "recreate_stack"
    assert body["grouping"]["warnings"]
    assert wud_file.read_text(encoding="utf-8") == original


def test_pending_endpoint_groups_items_by_compose_stack_without_mutation(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    wud_file = tmp_path / "state" / "images.todo"
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

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    body = response.json()
    assert [item["line_no"] for item in body["items"]] == [1, 2]
    grouping = body["grouping"]
    assert grouping["status"] == "ready"
    assert grouping["warnings"] == []
    assert grouping["unmatched"] == []
    assert len(grouping["groups"]) == 1
    group = grouping["groups"][0]
    assert group["name"] == "stack"
    assert group["compose_file"] == "docker-compose.yml"
    assert group["directory"] == str(compose_dir)
    assert group["project_directory"] == ""
    assert group["services"] == ["app", "db"]
    assert group["services_label"] == "app, db"
    assert group["line_numbers"] == [1, 2]
    assert [item["line_no"] for item in group["items"]] == [1, 2]
    assert group["items"][0]["services"] == ["app"]
    assert group["items"][0]["compose_images"] == ["repo/app:latest"]
    assert group["items"][0]["resolved_image"] == "repo/app:latest"
    assert group["items"][0]["target_image"] == "repo/app:latest"
    assert group["items"][0]["action"] == "recreate_service"
    assert wud_file.read_text(encoding="utf-8") == original
    assert (
        (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")
        == compose_before
    )
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_pending_endpoint_marks_recreate_stack_label_action(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:latest\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [
            ("app", "repo/app:latest", "cid-app"),
            ("db", "repo/db:latest", "cid-db"),
        ],
    )
    _write_fake_container_labels(
        fake_root,
        "cid-app",
        {"WUD-UPDATER-RECREATE-STACK": "true"},
    )

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    group = response.json()["grouping"]["groups"][0]
    assert group["items"][0]["services"] == ["app"]
    assert group["items"][0]["action"] == "recreate_stack"
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_pending_endpoint_honors_env_compose_ignore_paths(tmp_path: Path) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_COMPOSE_IGNORE_PATHS": "old",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/ignored:latest\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "active",
        [("app", "repo/app:latest", "cid-app")],
    )
    _make_fake_stack(
        tmp_path,
        fake_root,
        "ignored",
        [("app", "repo/ignored:latest", "cid-ignored")],
        parent=tmp_path / "docker" / "old",
    )

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    grouping = response.json()["grouping"]
    assert grouping["status"] == "ready"
    assert grouping["groups"] == []
    assert [item["line_no"] for item in grouping["unmatched"]] == [1]


def test_pending_endpoint_honors_webui_managed_compose_ignore_paths(
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
    headers = _csrf_headers(client)
    settings_update = client.post(
        "/api/v1/settings/managed",
        json={"values": {"compose_ignore_paths": "old"}},
        headers=headers,
    )
    assert settings_update.status_code == 200
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/ignored:latest\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "active",
        [("app", "repo/app:latest", "cid-app")],
    )
    _make_fake_stack(
        tmp_path,
        fake_root,
        "ignored",
        [("app", "repo/ignored:latest", "cid-ignored")],
        parent=tmp_path / "docker" / "old",
    )

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    grouping = response.json()["grouping"]
    assert grouping["status"] == "ready"
    assert grouping["groups"] == []
    assert [item["line_no"] for item in grouping["unmatched"]] == [1]


def test_pending_endpoint_allows_empty_webui_managed_compose_ignore_paths(
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
    headers = _csrf_headers(client)
    settings_update = client.post(
        "/api/v1/settings/managed",
        json={"values": {"compose_ignore_paths": ""}},
        headers=headers,
    )
    assert settings_update.status_code == 200
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/archived:latest\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "archived",
        [("app", "repo/archived:latest", "cid-archived")],
        parent=tmp_path / "docker" / "old",
    )

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    grouping = response.json()["grouping"]
    assert grouping["status"] == "ready"
    assert len(grouping["groups"]) == 1
    assert grouping["groups"][0]["items"][0]["line_no"] == 1


def test_pending_endpoint_reports_unmatched_grouping_items(tmp_path: Path) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/other:latest\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    grouping = response.json()["grouping"]
    assert grouping["status"] == "ready"
    assert grouping["groups"] == []
    assert len(grouping["unmatched"]) == 1
    assert grouping["unmatched"][0]["line_no"] == 1
    assert grouping["unmatched"][0]["image"] == "repo/other:latest"
    assert grouping["unmatched"][0]["action"] == "unmatched"
    assert grouping["unmatched"][0]["services"] == []
    assert grouping["unmatched"][0]["compose_images"] == []
    diagnostic = grouping["unmatched"][0]["diagnostic"]
    assert diagnostic["code"] == "unmatched"
    assert (
        diagnostic["message"]
        == "This pending update no longer matches any discovered Compose service."
    )
    assert "service removal" in diagnostic["hint"]
    assert "image rename" in diagnostic["hint"]
    assert "No running Docker container matched this pending line." in diagnostic[
        "details"
    ]["preflight_findings"]
    assert "The Compose service was removed or renamed." in diagnostic["details"][
        "possible_reasons"
    ]
    assert "Remove the stale WUD line" in " ".join(
        diagnostic["details"]["recommended_actions"]
    )
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_pending_endpoint_diagnoses_archived_compose_label_stale_entry(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
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

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    diagnostic = response.json()["grouping"]["unmatched"][0]["diagnostic"]
    assert diagnostic["code"] == "compose-label-active-file-missing"
    assert diagnostic["stack"] == "homarr"
    assert diagnostic["service"] == "homarr"
    assert "homarr/docker-compose.yml" in diagnostic["message"]
    assert "homarr/docker-compose.archive.yml" in diagnostic["message"]
    assert str(tmp_path) not in diagnostic["message"]
    assert diagnostic["found_files"] == ["homarr/docker-compose.archive.yml"]
    assert "Running container homarr still matches this pending line." in diagnostic[
        "details"
    ]["preflight_findings"]
    assert (
        "The active Compose file was renamed to an archived or nonstandard filename."
        in diagnostic["details"]["possible_reasons"]
    )
    assert "Update Docker base or ignore paths if the stack moved." in diagnostic[
        "details"
    ]["recommended_actions"]


def test_pending_endpoint_diagnoses_undiscovered_active_compose_label_entry(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_COMPOSE_IGNORE_PATHS": "old",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("homarr-labs/homarr:latest\n", encoding="utf-8")
    ignored_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "homarr",
        [("homarr", "ghcr.io/homarr-labs/homarr:latest", "cid-homarr")],
        parent=tmp_path / "docker" / "old",
    )
    active_file = ignored_dir / "docker-compose.yml"
    _make_fake_stack(
        tmp_path,
        fake_root,
        "active",
        [("app", "repo/app:latest", "cid-app")],
    )
    with (fake_root / "containers.tsv").open("a", encoding="utf-8") as file:
        file.write("homarr\tghcr.io/homarr-labs/homarr:latest\n")
    _write_fake_container_labels(
        fake_root,
        "homarr",
        {
            "com.docker.compose.project": "homarr",
            "com.docker.compose.project.working_dir": str(ignored_dir),
            "com.docker.compose.project.config_files": str(active_file),
            "com.docker.compose.service": "homarr",
        },
    )

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    diagnostic = response.json()["grouping"]["unmatched"][0]["diagnostic"]
    assert diagnostic["code"] == "compose-label-undiscovered-active-file"
    assert "old/homarr/docker-compose.yml" in diagnostic["message"]
    assert str(tmp_path) not in diagnostic["message"]
    assert "Compose discovery did not include that stack." in diagnostic["details"][
        "preflight_findings"
    ]
    assert "The stack is excluded by Compose ignore paths." in diagnostic["details"][
        "possible_reasons"
    ]
    assert "Update Docker base or ignore paths so discovery includes the stack." in (
        diagnostic["details"]["recommended_actions"]
    )


def test_pending_endpoint_groups_tag_updates_without_allowing_tag_updates(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    wud_file = tmp_path / "state" / "images.todo"
    original = "repo/app:1.0 tag=2.0\n"
    wud_file.write_text(original, encoding="utf-8")
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:1.0", "cid-app")],
    )
    compose_before = (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    grouping = response.json()["grouping"]
    assert grouping["status"] == "ready"
    assert grouping["unmatched"] == []
    item = grouping["groups"][0]["items"][0]
    assert item["line_no"] == 1
    assert item["action"] == "tag-update"
    assert item["desired_tag"] == "2.0"
    assert item["resolved_image"] == "repo/app:1.0"
    assert item["target_image"] == "repo/app:2.0"
    assert item["compose_images"] == ["repo/app:1.0"]
    assert item["services"] == ["app"]
    assert wud_file.read_text(encoding="utf-8") == original
    assert (
        (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")
        == compose_before
    )
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


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
    original_init_db = web_module.init_db

    def failing_init_db(conn: sqlite3.Connection) -> None:
        raise web_module.DatabaseError("audit database unavailable")

    web_module.init_db = failing_init_db
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
        web_module.init_db = original_init_db

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
    original_init_db = web_module.init_db

    def failing_init_db(conn: sqlite3.Connection) -> None:
        raise web_module.DatabaseError("audit database unavailable")

    web_module.init_db = failing_init_db
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
        web_module.init_db = original_init_db

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

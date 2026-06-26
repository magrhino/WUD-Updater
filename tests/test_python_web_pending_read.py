from __future__ import annotations
from pathlib import Path
from wudup import web_pending as pending_module
from wudup.config import ConfigError
from tests.web_test_helpers import (
    _client,
    _csrf_headers,
    _fake_docker_env,
    _make_fake_stack,
    _write_fake_container_labels,
    _fake_docker_calls,
    _assert_pending_grouping_did_not_mutate,
    _install_wud_api,
    _wud_api_container,
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
    unavailable_provenance = body["grouping"]["unmatched"][1]["digest_provenance"]
    assert body["items"][1]["digest_provenance"] == unavailable_provenance
    assert unavailable_provenance == {
        "source_image": "redis:latest",
        "resolved_tag": "latest",
        "watch_tag": "latest",
        "target_digest": "sha256:abc",
        "final_image": "redis@sha256:abc",
        "provenance_source": "compose",
        "provenance_confidence": "recovered",
    }
    assert body["grouping"]["warnings"]
    assert wud_file.read_text(encoding="utf-8") == original


def test_pending_endpoint_reads_wud_api_source_without_wud_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    remote_digest = f"sha256:{'b' * 64}"
    _install_wud_api(
        monkeypatch,
        containers=[_wud_api_container(remote_digest=remote_digest)],
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_PENDING_SOURCE": "api",
            "WUD_API_BASE_URL": "https://wud.api-source.test:3000",
            **fake_env,
        },
    )
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:1.0", "cid-app")],
    )

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    body = response.json()
    assert body["source"]["configured"] == "api"
    assert body["source"]["active"] == "api"
    assert body["source"]["label"] == "WUD API"
    assert body["exists"] is True
    assert body["source_file"] == "WUD API"
    assert body["count"] == 1
    assert body["items"][0]["line_no"] == 1
    assert body["items"][0]["raw"] == f"repo/app:1.0 tag=2.0 sha256={remote_digest}"
    assert body["items"][0]["digest"] == remote_digest
    assert body["items"][0]["source"] == "api"
    assert body["items"][0]["source_id"] == "docker.local.app"
    assert body["items"][0]["wud_metadata"]["remote_tag"] == "2.0"
    assert body["grouping"]["status"] == "ready"
    assert body["grouping"]["groups"][0]["items"][0]["source"] == "api"
    assert body["grouping"]["groups"][0]["items"][0]["source_id"] == "docker.local.app"
    assert not (tmp_path / "state" / "images.todo").exists()
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_pending_endpoint_preserves_tag_for_wud_api_digest_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    remote_digest = f"sha256:{'a' * 64}"
    _install_wud_api(
        monkeypatch,
        containers=[
            _wud_api_container(
                tag="latest",
                remote_tag="",
                remote_digest=remote_digest,
                update_kind="digest",
            )
        ],
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_PENDING_SOURCE": "api",
            "WUD_API_BASE_URL": "https://wud.api-digest-source.test:3000",
            **fake_env,
        },
    )
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [
            ("app", "repo/app:latest", "cid-app"),
            ("worker", "repo/app:stable", "cid-worker"),
        ],
    )

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["raw"] == f"repo/app:latest@{remote_digest}"
    assert body["items"][0]["digest"] == remote_digest
    assert body["grouping"]["status"] == "ready"
    assert body["grouping"]["groups"][0]["items"][0]["services"] == ["app"]
    calls = _fake_docker_calls(fake_root)
    assert "worker" not in calls
    _assert_pending_grouping_did_not_mutate(calls)


def test_pending_endpoint_auto_falls_back_to_wud_file_when_api_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(
        monkeypatch,
        containers=[],
        health_error=OSError("connection refused"),
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_PENDING_SOURCE": "auto",
            "WUD_API_BASE_URL": "https://wud.unavailable-source.test:3000",
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/file:latest\n", encoding="utf-8")

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    body = response.json()
    assert body["source"]["configured"] == "auto"
    assert body["source"]["active"] == "file"
    assert body["source"]["degraded"] is True
    assert body["source"]["fresh"] is False
    assert "connection refused" in body["source"]["fallback_reason"]
    assert body["count"] == 1
    assert body["items"][0]["raw"] == "repo/file:latest"
    assert body["items"][0]["source"] == "file"
    assert body["warnings"][0].startswith("WUD API pending source degraded")


def test_pending_endpoint_api_mode_does_not_fallback_to_wud_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(
        monkeypatch,
        containers=[],
        health_error=OSError("connection refused"),
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_PENDING_SOURCE": "api",
            "WUD_API_BASE_URL": "https://wud.api-unavailable.test:3000",
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/file:latest\n", encoding="utf-8")

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    body = response.json()
    assert body["source"]["configured"] == "api"
    assert body["source"]["active"] == "api"
    assert body["source"]["degraded"] is True
    assert body["count"] == 0
    assert body["items"] == []
    assert body["source_file"] == "WUD API"
    assert wud_file.read_text(encoding="utf-8") == "repo/file:latest\n"


def test_pending_endpoint_wraps_effective_config_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = "pending-secret-token"

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
    monkeypatch.setattr(pending_module, "_effective_config_loader", invalid_config)
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:latest\n", encoding="utf-8")

    response = client.get("/api/v1/pending")
    detail = response.json()["detail"]

    assert response.status_code == 400
    assert detail.startswith("could not read effective config: ")
    assert secret not in detail
    assert str(tmp_path) not in detail
    assert "<redacted>" in detail
    assert "[REDACTED_PATH]" in detail


def test_pending_endpoint_sanitizes_wud_file_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = "pending-read-secret"

    def failed_read(_path):
        raise OSError(
            f"open failed for {tmp_path / 'state' / 'images.todo'} with {secret}"
        )

    monkeypatch.setattr(pending_module.web_pending_sources, "_read_pending_file", failed_read)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_TOKEN": secret,
        },
    )

    response = client.get("/api/v1/pending")
    detail = response.json()["detail"]

    assert response.status_code == 500
    assert detail.startswith("could not read pending source: ")
    assert secret not in detail
    assert str(tmp_path) not in detail
    assert "<redacted>" in detail
    assert "[REDACTED_PATH]" in detail


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


def test_pending_endpoint_recovers_digest_pin_provenance_from_compose(
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
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app@sha256:old", "cid-app")],
    )
    (compose_dir / "docker-compose.yml").write_text(
        "\n".join(
            [
                "services:",
                "  app:",
                "    # wudup.resolved-tag=latest",
                "    image: repo/app@sha256:old",
                "    labels:",
                "      - wud.tag.include=^latest$$",
                "",
            ]
        ),
        encoding="utf-8",
    )

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    body = response.json()
    item_provenance = body["items"][0]["digest_provenance"]
    group_provenance = body["grouping"]["groups"][0]["items"][0][
        "digest_provenance"
    ]
    assert item_provenance == group_provenance
    assert item_provenance["source_image"] == "repo/app:latest"
    assert item_provenance["resolved_tag"] == "latest"
    assert item_provenance["watch_tag"] == "latest"
    assert item_provenance["target_digest"] == "sha256:child"
    assert item_provenance["final_image"] == "repo/app@sha256:child"
    assert item_provenance["provenance_source"] == "compose"
    assert item_provenance["provenance_confidence"] == "recovered"
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_pending_endpoint_keeps_digest_pin_provenance_for_unmatched_item(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/other:latest@sha256:child\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    body = response.json()
    grouping = body["grouping"]
    assert grouping["status"] == "ready"
    assert grouping["groups"] == []
    assert len(grouping["unmatched"]) == 1
    unmatched_provenance = grouping["unmatched"][0]["digest_provenance"]
    assert body["items"][0]["digest_provenance"] == unmatched_provenance
    assert unmatched_provenance == {
        "source_image": "repo/other:latest",
        "resolved_tag": "latest",
        "watch_tag": "latest",
        "target_digest": "sha256:child",
        "final_image": "repo/other@sha256:child",
        "provenance_source": "compose",
        "provenance_confidence": "recovered",
    }
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

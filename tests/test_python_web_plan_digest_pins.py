from __future__ import annotations
from pathlib import Path
from wudup import web_plans as plans_module
from wudup.db import DatabaseError
from tests.web_test_helpers import (
    _client,
    _csrf_headers,
    _fake_docker_env,
    _make_fake_stack,
    _write_fake_manifest,
    _manifest_index_digest,
)

from tests.web_plan_test_helpers import _seed_known_digest_provenance

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


def test_plan_endpoint_scopes_digest_unpin_by_selection_id(
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
    _seed_known_digest_provenance(tmp_path, service_key="active/app")
    _seed_known_digest_provenance(tmp_path, service_key="backup/app")
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("repo/app:latest@sha256:new\n", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "active",
        [("app", "repo/app@sha256:old", "cid-active")],
    )
    _make_fake_stack(
        tmp_path,
        fake_root,
        "backup",
        [("app", "repo/app@sha256:old", "cid-backup")],
    )
    pending = client.get("/api/v1/pending").json()
    active_group = next(
        group
        for group in pending["grouping"]["groups"]
        if group["name"] == "active"
    )
    selection = {
        "line_no": active_group["items"][0]["line_no"],
        "selection_id": active_group["items"][0]["selection_id"],
    }

    response = client.post(
        "/api/v1/plans",
        json={"selections": [selection]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["selected_selections"] == [selection]
    assert [stack["name"] for stack in body["stacks"]] == ["active"]
    assert body["stacks"][0]["digest_unpin_updates"][0]["services"] == ["app"]


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
    caplog.set_level("WARNING", logger="wudup.web_database")

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
    caplog.set_level("WARNING", logger="wudup.web_database")

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

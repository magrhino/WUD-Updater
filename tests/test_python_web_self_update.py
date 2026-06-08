from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from wud_updater import web_self_update as self_update_module
from wud_updater.db import (
    open_db,
)
from tests.web_test_helpers import (
    _client,
    _csrf_headers,
    _self_update_payload,
    _fake_docker_env,
    _make_fake_stack,
    _fake_docker_calls,
    _write_fake_manifest,
    _write_fake_image_after_pull,
    _manifest_index_digest,
)


def test_self_update_get_reports_available_up_to_date_disabled_and_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(
        self_update_module,
        "_fetch_self_update_release_notes",
        lambda *_args, **_kwargs: ([], False, []),
    )
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    available = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
        },
    ).get("/api/v1/self-update")

    assert available.status_code == 200
    body = available.json()
    assert body["status"] == "available"
    assert body["current_tag"] == "v0.24.2"
    assert body["latest_tag"] == "v0.25.0"
    assert body["target_image"] == "ghcr.io/magrhino/wud-updater:v0.25.0"
    assert body["can_update"] is False
    assert "Read-only mode" in body["disabled_reason"]

    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.24.2")
    up_to_date = _client(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true"},
    ).get("/api/v1/self-update")
    assert up_to_date.json()["status"] == "up_to_date"

    disabled = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_UPDATER_RELEASE_CHECK": "false",
        },
    ).get("/api/v1/self-update")
    assert disabled.json()["status"] == "disabled"

    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: None)
    unavailable = _client(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true"},
    ).get("/api/v1/self-update")
    assert unavailable.json()["status"] == "unavailable"
    assert unavailable.json()["warnings"]


def test_self_update_get_can_use_local_demo_fixture(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "demo-wud-updater",
            "WUD_WEB_DEMO_SELF_UPDATE": "true",
        },
    )

    response = client.get("/api/v1/self-update")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["current_tag"] == "v0.25.0"
    assert body["latest_tag"] == "v0.26.0"
    assert body["target_image"] == "ghcr.io/magrhino/wud-updater:latest"
    assert body["restart_container"] == "demo-wud-updater"
    assert body["can_update"] is True
    assert body["release_notes_truncated"] is True
    assert len(body["release_notes"]) == 10


def test_self_update_get_reports_prepare_strategy_for_pinned_tag_rewrite_targets(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
    response = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
        },
    ).get("/api/v1/self-update")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["strategy"] == "prepare_tag_update"
    assert body["target_image"] == "ghcr.io/magrhino/wud-updater:v0.25.0"
    assert body["can_update"] is True
    assert body["disabled_reason"] == ""
    assert body["external_recreate_required"] is True


def test_self_update_pull_endpoint_rejects_pinned_tag_prepare_targets(
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
        "/api/v1/self-update",
        json=_self_update_payload(
            target_image="ghcr.io/magrhino/wud-updater:v0.25.0",
        ),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "self-update target requires tag update preparation"
    assert " pull " not in _fake_docker_calls(fake_root)


def test_self_update_prepare_endpoint_rewrites_tag_pulls_and_audits(
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
    plan = client.post(
        "/api/v1/self-update/plan",
        headers=_csrf_headers(client),
    ).json()

    response = client.post(
        "/api/v1/self-update/prepare",
        json={
            "confirmation": "prepare_tag_update",
            "plan_id": plan["plan"]["plan_id"],
            "current_tag": "v0.24.2",
            "latest_tag": "v0.25.0",
            "target_image": "ghcr.io/magrhino/wud-updater:v0.25.0",
            "restart_container": "wud-updater",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "tag_prepared"
    assert body["external_recreate_required"] is True
    assert "image: ghcr.io/magrhino/wud-updater:v0.25.0" in (
        compose_dir / "docker-compose.yml"
    ).read_text(encoding="utf-8")
    calls = _fake_docker_calls(fake_root)
    assert "inspect wud-updater" in calls
    assert "compose -f docker-compose.yml pull wud-updater" in calls
    assert " up -d " not in calls
    assert "restart " not in calls
    assert client.app.state.web_self_update_running is False

    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        row = conn.execute(
            "SELECT mode, status, finished_at, metadata_json FROM update_runs WHERE id = ?",
            (body["audit_run_id"],),
        ).fetchone()
        event = conn.execute(
            "SELECT status, metadata_json FROM update_events WHERE run_id = ?",
            (body["audit_run_id"],),
        ).fetchone()
    assert row["mode"] == "web-self-update"
    assert row["status"] == "tag_prepared"
    assert row["finished_at"]
    assert event["status"] == "tag_prepared"
    metadata = json.loads(row["metadata_json"])
    assert metadata["operation"] == "self_update"
    assert metadata["strategy"] == "prepare_tag_update"
    assert metadata["status"] == "tag_prepared"
    assert metadata["external_recreate_required"] is True
    assert metadata["services"] == ["wud-updater"]
    assert metadata["tag_updates"][0]["new_image"] == (
        "ghcr.io/magrhino/wud-updater:v0.25.0"
    )


def test_self_update_prepare_endpoint_digest_pins_after_verification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    target_image = "ghcr.io/magrhino/wud-updater:v0.25.0"
    _write_fake_manifest(
        fake_root,
        target_image,
        _manifest_index_digest("sha256:index", "sha256:child"),
    )
    _write_fake_image_after_pull(
        fake_root,
        target_image,
        "sha256:config",
        "sha256:index",
    )
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
            "WUD_DIGEST_PIN_UPDATES": "true",
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
    plan = client.post(
        "/api/v1/self-update/plan",
        headers=_csrf_headers(client),
    ).json()

    response = client.post(
        "/api/v1/self-update/prepare",
        json={
            "confirmation": "prepare_tag_update",
            "plan_id": plan["plan"]["plan_id"],
            "current_tag": "v0.24.2",
            "latest_tag": "v0.25.0",
            "target_image": target_image,
            "restart_container": "wud-updater",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    content = (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")
    assert "# wud-updater.resolved-tag=v0.25.0" in content
    assert "image: ghcr.io/magrhino/wud-updater@sha256:index" in content
    assert "wud.tag.include=^v0\\.25\\.0$$" in content

    body = response.json()
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        row = conn.execute(
            "SELECT metadata_json FROM update_runs WHERE id = ?",
            (body["audit_run_id"],),
        ).fetchone()
    metadata = json.loads(row["metadata_json"])
    assert metadata["digest_pin_updates"][0]["final_image"] == (
        "ghcr.io/magrhino/wud-updater@sha256:index"
    )


def test_self_update_prepare_endpoint_rejects_moved_digest_pin_after_pull(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    target_image = "ghcr.io/magrhino/wud-updater:v0.25.0"
    _write_fake_manifest(
        fake_root,
        target_image,
        _manifest_index_digest("sha256:planned", "sha256:child"),
    )
    _write_fake_image_after_pull(
        fake_root,
        target_image,
        "sha256:config",
        "sha256:planned",
    )
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
    original_pull = self_update_module.ComposeCli.pull

    def moving_pull(self, *args, **kwargs):
        result = original_pull(self, *args, **kwargs)
        _write_fake_manifest(
            fake_root,
            target_image,
            _manifest_index_digest("sha256:moved", "sha256:child"),
        )
        return result

    monkeypatch.setattr(self_update_module.ComposeCli, "pull", moving_pull)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
            "WUD_DIGEST_PIN_UPDATES": "true",
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
    plan = client.post(
        "/api/v1/self-update/plan",
        headers=_csrf_headers(client),
    ).json()

    response = client.post(
        "/api/v1/self-update/prepare",
        json={
            "confirmation": "prepare_tag_update",
            "plan_id": plan["plan"]["plan_id"],
            "current_tag": "v0.24.2",
            "latest_tag": "v0.25.0",
            "target_image": target_image,
            "restart_container": "wud-updater",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 500
    assert (compose_dir / "docker-compose.yml").read_text(encoding="utf-8") == compose_before
    assert client.app.state.web_self_update_running is False


def test_self_update_prepare_endpoint_restores_compose_when_pull_fails(
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
    (fake_root / "stacks" / "wud" / "pull_fail").write_text(
        "pull failed\n",
        encoding="utf-8",
    )
    compose_before = (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")
    plan = client.post(
        "/api/v1/self-update/plan",
        headers=_csrf_headers(client),
    ).json()

    response = client.post(
        "/api/v1/self-update/prepare",
        json={
            "confirmation": "prepare_tag_update",
            "plan_id": plan["plan"]["plan_id"],
            "current_tag": "v0.24.2",
            "latest_tag": "v0.25.0",
            "target_image": "ghcr.io/magrhino/wud-updater:v0.25.0",
            "restart_container": "wud-updater",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 500
    assert response.json()["detail"].startswith(
        "could not prepare self-update tag update",
    )
    assert (compose_dir / "docker-compose.yml").read_text(encoding="utf-8") == compose_before
    calls = _fake_docker_calls(fake_root)
    assert "compose -f docker-compose.yml pull wud-updater" in calls
    assert " up -d " not in calls
    assert "restart " not in calls
    assert client.app.state.web_self_update_running is False

    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        row = conn.execute(
            "SELECT status, finished_at, metadata_json FROM update_runs WHERE mode = 'web-self-update'",
        ).fetchone()
    assert row["status"] == "failure"
    assert row["finished_at"]
    metadata = json.loads(row["metadata_json"])
    assert metadata["status"] == "failure"
    assert "docker compose" in metadata["error"]


def test_self_update_release_notes_are_between_versions_and_capped(
    monkeypatch,
) -> None:
    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            releases = [
                {
                    "tag_name": f"v0.{minor}.0",
                    "name": f"v0.{minor}.0",
                    "html_url": f"https://example.test/v0.{minor}.0",
                    "body": "Routine update",
                    "published_at": f"2026-05-{minor:02d}T00:00:00Z",
                }
                for minor in range(10, 25)
            ]
            return json.dumps(releases).encode("utf-8")

    monkeypatch.setattr(self_update_module.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    notes, truncated, warnings = self_update_module._fetch_self_update_release_notes(
        "v0.12.0",
        "v0.24.0",
        {},
        cap=10,
    )

    assert warnings == []
    assert truncated is True
    assert len(notes) == 10
    assert notes[0].tag == "v0.24.0"
    assert notes[-1].tag == "v0.15.0"
    assert all(note.tag not in {"v0.12.0", "v0.11.0"} for note in notes)


def test_self_update_endpoint_rejects_stale_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    monkeypatch.setattr(
        self_update_module,
        "current_container_image",
        lambda _env: "ghcr.io/magrhino/wud-updater:latest",
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
        "/api/v1/self-update",
        json=_self_update_payload(latest_tag="v0.24.9"),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "self-update target is stale"
    assert _fake_docker_calls(fake_root) == ""


def test_self_update_endpoint_pulls_image_and_audits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    monkeypatch.setattr(
        self_update_module,
        "current_container_image",
        lambda _env: "ghcr.io/magrhino/wud-updater:latest",
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
    (fake_root / "containers" / "wud-updater.summary").write_text(
        "/wud-updater|running|healthy|0|0\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/self-update",
        json=_self_update_payload(),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "image_pulled"
    assert body["target_image"] == "ghcr.io/magrhino/wud-updater:latest"
    assert body["container"] == "wud-updater"
    calls = _fake_docker_calls(fake_root)
    assert "pull ghcr.io/magrhino/wud-updater:latest" in calls
    assert "restart --time 10 wud-updater" not in calls
    assert client.app.state.web_self_update_running is False

    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        row = conn.execute(
            "SELECT mode, status, finished_at, metadata_json FROM update_runs WHERE id = ?",
            (body["audit_run_id"],),
        ).fetchone()
        event = conn.execute(
            "SELECT status, metadata_json FROM update_events WHERE run_id = ?",
            (body["audit_run_id"],),
        ).fetchone()
    assert row["mode"] == "web-self-update"
    assert row["status"] == "image_pulled"
    assert row["finished_at"]
    assert event["status"] == "image_pulled"
    metadata = json.loads(row["metadata_json"])
    assert metadata["operation"] == "self_update"
    assert metadata["current_tag"] == "v0.24.2"
    assert metadata["latest_tag"] == "v0.25.0"
    assert metadata["status"] == "image_pulled"
    assert metadata["target"] == {
        "container": "wud-updater",
        "image": "ghcr.io/magrhino/wud-updater:latest",
    }


def test_self_update_endpoint_inspects_restart_container_before_pull(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    monkeypatch.setattr(
        self_update_module,
        "current_container_image",
        lambda _env: "ghcr.io/magrhino/wud-updater:latest",
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
            "WUD_WEB_RESTART_CONTAINER": "missing-wud-updater",
            **fake_env,
        },
    )

    response = client.post(
        "/api/v1/self-update",
        json=_self_update_payload(restart_container="missing-wud-updater"),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 500
    assert response.json()["detail"].startswith("could not inspect restart container")
    calls = _fake_docker_calls(fake_root)
    assert "inspect missing-wud-updater" in calls
    assert "pull ghcr.io/magrhino/wud-updater:latest" not in calls
    assert client.app.state.web_self_update_running is False
    try:
        with open_db(tmp_path / "state" / "wud.sqlite") as conn:
            row = conn.execute(
                "SELECT id FROM update_runs WHERE mode = 'web-self-update'",
            ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table: update_runs" not in str(exc):
            raise
        row = None
    assert row is None


def test_self_update_endpoint_marks_audit_failed_when_pull_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    (fake_root / "pull_fail").write_text("pull failed\n", encoding="utf-8")
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    monkeypatch.setattr(
        self_update_module,
        "current_container_image",
        lambda _env: "ghcr.io/magrhino/wud-updater:latest",
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
    (fake_root / "containers" / "wud-updater.summary").write_text(
        "/wud-updater|running|healthy|0|0\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/self-update",
        json=_self_update_payload(),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 500
    assert response.json()["detail"].startswith("could not pull self-update image")
    calls = _fake_docker_calls(fake_root)
    assert "pull ghcr.io/magrhino/wud-updater:latest" in calls
    assert "restart --time 10 wud-updater" not in calls
    assert client.app.state.web_self_update_running is False

    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        row = conn.execute(
            "SELECT status, finished_at, metadata_json FROM update_runs WHERE mode = 'web-self-update'",
        ).fetchone()
    assert row["status"] == "failure"
    assert row["finished_at"]
    metadata = json.loads(row["metadata_json"])
    assert metadata["status"] == "failure"
    assert "docker pull ghcr.io/magrhino/wud-updater:latest" in metadata["error"]


def test_self_update_endpoint_rejects_active_self_update(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
            **fake_env,
        },
    )
    client.app.state.web_self_update_running = True

    response = client.post(
        "/api/v1/self-update",
        json=_self_update_payload(),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "self-update is already running"
    assert _fake_docker_calls(fake_root) == ""

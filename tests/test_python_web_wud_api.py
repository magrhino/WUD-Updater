from __future__ import annotations

import json
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any

from wudup import web_release_notes as release_notes_module
from wudup import web_wud_api
from wudup.release_notes import (
    ReleaseNoteInfo as ReleaseNoteData,
    release_note_contexts,
)
from wudup.web import load_web_settings

from tests.web_test_helpers import _client, _csrf_headers, _web_env


ResponseSpec = tuple[int, object]


def _settings(tmp_path: Path, base_url: str):
    return load_web_settings(
        environ=_web_env(tmp_path, {"WUD_API_BASE_URL": base_url}),
    )


def _container_payload(
    *,
    name: str = "app",
    image: str = "registry.example/acme/app",
    tag: str = "1.0.0",
    remote_tag: str = "1.1.0",
    source: str = "https://github.com/acme/app",
    link: str = "https://github.com/acme/app/releases/tag/v1.1.0",
    update_available: bool = True,
) -> dict[str, Any]:
    return {
        "id": f"docker.local.{name}",
        "name": name,
        "displayName": name.title(),
        "status": "running",
        "watcher": "local",
        "image": {
            "name": image,
            "tag": {"value": tag},
            "digest": {"value": "sha256:local"},
        },
        "result": {
            "tag": remote_tag,
            "digest": "sha256:remote",
            "link": link,
        },
        "updateKind": {
            "kind": "tag",
            "localValue": tag,
            "remoteValue": remote_tag,
            "semverDiff": "minor",
        },
        "labels": {
            "org.opencontainers.image.source": source,
        },
        "error": {"message": ""},
        "updateAvailable": update_available,
    }


def _install_wud_api(
    monkeypatch,
    *,
    health: ResponseSpec | Exception = (200, {"status": "ok"}),
    containers: ResponseSpec | Exception = (200, ()),
) -> None:
    def fake_request_json(url: str) -> object:
        path = urllib.parse.urlsplit(url).path
        if path == "/health":
            return _wud_response(url, health)
        if path == "/api/containers":
            return _wud_response(url, containers)
        raise AssertionError(f"unexpected WUD API URL: {url}")

    monkeypatch.setattr(web_wud_api, "_request_json", fake_request_json)


def _wud_response(url: str, response: ResponseSpec | Exception) -> object:
    if isinstance(response, Exception):
        raise response
    status, payload = response
    if status >= 400:
        raise urllib.error.HTTPError(url, status, "test WUD API error", {}, None)
    json.dumps(payload)
    return payload


def test_wud_api_snapshot_reads_update_metadata(tmp_path: Path, monkeypatch) -> None:
    _install_wud_api(
        monkeypatch,
        containers=(
            200,
            [
                _container_payload(),
                _container_payload(name="already-current", update_available=False),
            ],
        ),
    )

    snapshot = web_wud_api.get_snapshot(
        _settings(tmp_path, "http://wud.test:3000"),
        include_containers=True,
        force=True,
    )

    assert snapshot.status.state == "ready"
    assert snapshot.status.available is True
    assert snapshot.status.metadata_available is True
    assert len(snapshot.containers) == 1
    container = snapshot.containers[0]
    assert container.name == "app"
    assert container.image == "registry.example/acme/app:1.0.0"
    assert container.remote_tag == "1.1.0"
    assert container.remote_digest == "sha256:remote"
    assert container.update_kind == "tag"
    assert container.semver_diff == "minor"


def test_wud_api_snapshot_reports_unreachable_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, health=OSError("connection refused"))

    snapshot = web_wud_api.get_snapshot(
        _settings(tmp_path, "http://wud.unreachable.test:3000"),
        include_containers=True,
        force=True,
    )

    assert snapshot.status.state == "unavailable"
    assert snapshot.status.available is False
    assert snapshot.status.metadata_available is False
    assert snapshot.containers == ()


def test_wud_api_snapshot_reports_auth_required_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(
        monkeypatch,
        containers=(401, {"error": "authentication required"}),
    )

    snapshot = web_wud_api.get_snapshot(
        _settings(tmp_path, "http://wud.auth.test:3000"),
        include_containers=True,
        force=True,
    )

    assert snapshot.status.state == "auth_required"
    assert snapshot.status.available is True
    assert snapshot.status.metadata_available is False
    assert snapshot.status.detail == "WUD API container metadata requires authentication"


def test_wud_api_snapshot_rejects_invalid_container_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, containers=(200, {"items": []}))

    snapshot = web_wud_api.get_snapshot(
        _settings(tmp_path, "http://wud.invalid.test:3000"),
        include_containers=True,
        force=True,
    )

    assert snapshot.status.state == "error"
    assert snapshot.status.available is True
    assert snapshot.status.metadata_available is False
    assert snapshot.status.detail == "WUD API container metadata payload was not a list"


def test_web_startup_continues_when_wud_api_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, health=OSError("connection refused"))

    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_API_BASE_URL": "http://wud.startup.test:3000",
        },
    )

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    body = response.json()
    assert body["wud_api"]["state"] == "unavailable"
    assert body["wud_api"]["available"] is False


def test_pending_endpoint_enriches_items_from_wud_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, containers=(200, [_container_payload(name="app")]))
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_API_BASE_URL": "http://wud.pending.test:3000",
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    original = "app\n"
    wud_file.write_text(original, encoding="utf-8")

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    body = response.json()
    metadata = body["items"][0]["wud_metadata"]
    assert body["wud_api"]["metadata_available"] is True
    assert metadata["name"] == "app"
    assert metadata["remote_tag"] == "1.1.0"
    assert metadata["remote_digest"] == "sha256:remote"
    assert body["grouping"]["unmatched"][0]["wud_metadata"] == metadata
    assert wud_file.read_text(encoding="utf-8") == original


def test_pending_endpoint_keeps_images_todo_fallback_when_wud_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, health=OSError("connection refused"))
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_API_BASE_URL": "http://wud.fallback.test:3000",
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("registry.example/acme/app:1.0.0\n", encoding="utf-8")

    response = client.get("/api/v1/pending")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["image"] == "registry.example/acme/app:1.0.0"
    assert body["items"][0]["wud_metadata"] is None
    assert body["wud_api"]["metadata_available"] is False


def test_release_notes_refresh_uses_wud_source_and_safe_remote_tag(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_refresh_release_notes(
        _conn,
        targets,
        environ,
        *,
        source_resolver=None,
        target_tag_resolver=None,
        **_kwargs,
    ):
        contexts = release_note_contexts(
            targets,
            environ,
            source_resolver=source_resolver,
            target_tag_resolver=target_tag_resolver,
        )
        captured["contexts"] = contexts
        return [
            ReleaseNoteData(
                line_no=context.line_no,
                status="missing",
                provider=context.provider,
                image_repo=context.image_repo,
                upstream_repo=context.upstream_repo,
            )
            for context in contexts
        ]

    monkeypatch.setattr(
        release_notes_module,
        "refresh_release_notes",
        fake_refresh_release_notes,
    )
    _install_wud_api(
        monkeypatch,
        containers=(
            200,
            [
                _container_payload(
                    image="registry.example/acme/app",
                    tag="1.0.0",
                    remote_tag="1.1.0",
                ),
                _container_payload(
                    name="api",
                    image="registry.example/acme/api",
                    tag="2.0.0",
                    remote_tag="2.1.0",
                    source="https://github.com/acme/api",
                ),
            ],
        ),
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_API_BASE_URL": "http://wud.release-notes.test:3000",
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text(
        "\n".join(
            (
                "registry.example/acme/app:1.0.0",
                "registry.example/acme/api:2.0.0 tag=3.0.0",
                "",
            )
        ),
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/release-notes/refresh",
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    contexts = captured["contexts"]
    assert [context.provider for context in contexts] == ["github", "github"]
    assert [context.upstream_repo for context in contexts] == [
        "acme/app",
        "acme/api",
    ]
    assert [context.target_tag for context in contexts] == ["1.1.0", "3.0.0"]
    assert response.json()["wud_api"]["metadata_available"] is True

from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

import pytest

from wudup import web_release_notes as release_notes_module
from wudup import web_wud_api
from wudup.release_notes import (
    ReleaseNoteInfo as ReleaseNoteData,
    release_note_contexts,
)
from wudup.web import load_web_settings
from wudup.web_auth import WebConfigError

from tests.web_test_helpers import (
    WUD_API_ACCESS_KEY_ID,
    WUD_API_AUTHORIZATION_HEADER,
    WUD_API_SECRET_ACCESS_KEY,
    _client,
    _csrf_headers,
    _install_wud_api,
    _web_env,
)


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


class _ToggleableWudApi:
    def __init__(self, monkeypatch, *, reachable: bool) -> None:
        self.now = 0.0
        self.reachable = reachable
        self.calls: list[str] = []
        monkeypatch.setattr(web_wud_api.time, "monotonic", lambda: self.now)
        monkeypatch.setattr(web_wud_api, "_request_json", self.request_json)

    def request_json(self, url: str) -> object:
        path = urllib.parse.urlsplit(url).path
        self.calls.append(path)
        if not self.reachable:
            raise OSError("connection refused")
        if path == "/health":
            return {"status": "ok"}
        if path == "/api/containers":
            return [_container_payload(name="app")]
        raise AssertionError(f"unexpected WUD API URL: {url}")


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


def test_wud_api_configuration_diagnostics_reads_endpoint_payloads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch)

    diagnostics = web_wud_api.get_configuration_diagnostics(
        _settings(tmp_path, "https://wud.config.test:3000"),
        force=True,
    )

    assert diagnostics.health.state == "ready"
    assert diagnostics.app.status.state == "ready"
    assert diagnostics.app.name == "wud"
    assert diagnostics.app.version == "5.0.0"
    assert diagnostics.log.level == "debug"
    assert diagnostics.store.path == ".store"
    assert diagnostics.store.file == "wud.json"
    assert len(diagnostics.watchers) == 1
    assert diagnostics.watchers[0].id == "docker.local"
    assert diagnostics.watchers[0].cron == "0 * * * *"
    assert diagnostics.watchers[0].watch_by_default is True
    assert len(diagnostics.registries) == 1
    assert diagnostics.registries[0].id == "hub.private"


def test_wud_api_configuration_diagnostics_redacts_sensitive_config(
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
                    "id": "ecr.private",
                    "type": "ecr",
                    "name": "private",
                    "configuration": {
                        "region": "eu-west-1",
                        WUD_API_ACCESS_KEY_ID: "redaction-access-value",
                        WUD_API_SECRET_ACCESS_KEY: redaction_value,
                    },
                }
            ],
        ),
    )

    diagnostics = web_wud_api.get_configuration_diagnostics(
        _settings(tmp_path, "https://wud.config-redaction.test:3000"),
        force=True,
    )
    serialized = diagnostics.model_dump_json()

    assert redaction_value not in serialized
    assert "redaction-access-value" not in serialized
    assert diagnostics.watchers[0].configuration["socket"] == "[REDACTED_PATH]"
    assert diagnostics.watchers[0].configuration["headers"] == "<redacted>"
    assert diagnostics.registries[0].configuration["region"] == "eu-west-1"
    assert diagnostics.registries[0].configuration[WUD_API_ACCESS_KEY_ID] == "<redacted>"
    assert (
        diagnostics.registries[0].configuration[WUD_API_SECRET_ACCESS_KEY]
        == "<redacted>"
    )


def test_wud_api_configuration_diagnostics_reports_unreachable_health(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, health=OSError("connection refused"))

    diagnostics = web_wud_api.get_configuration_diagnostics(
        _settings(tmp_path, "https://wud.config-unreachable.test:3000"),
        force=True,
    )

    assert diagnostics.health.state == "unavailable"
    assert diagnostics.app.status.state == "unavailable"
    assert diagnostics.watchers_status.state == "unavailable"
    assert diagnostics.watchers == []
    assert diagnostics.registries == []


def test_wud_api_configuration_diagnostics_reports_health_auth_required(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, health=(401, {"error": "authentication required"}))

    diagnostics = web_wud_api.get_configuration_diagnostics(
        _settings(tmp_path, "https://wud.config-auth.test:3000"),
        force=True,
    )

    assert diagnostics.health.state == "auth_required"
    assert diagnostics.health.available is True
    assert diagnostics.app.status.state == "auth_required"
    assert diagnostics.registries_status.state == "auth_required"


def test_wud_api_configuration_diagnostics_reports_partial_endpoint_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(
        monkeypatch,
        registries=(401, {"error": "authentication required"}),
    )

    diagnostics = web_wud_api.get_configuration_diagnostics(
        _settings(tmp_path, "https://wud.config-partial.test:3000"),
        force=True,
    )

    assert diagnostics.app.status.state == "ready"
    assert diagnostics.watchers_status.state == "ready"
    assert diagnostics.registries_status.state == "auth_required"
    assert diagnostics.registries == []


def test_wud_api_configuration_diagnostics_rejects_malformed_payloads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(
        monkeypatch,
        app=(200, []),
        log=(200, []),
        store=(200, {"configuration": []}),
        watchers=(200, {"items": []}),
        registries=(200, {"items": []}),
    )

    diagnostics = web_wud_api.get_configuration_diagnostics(
        _settings(tmp_path, "https://wud.config-malformed.test:3000"),
        force=True,
    )

    assert diagnostics.app.status.state == "error"
    assert diagnostics.log.status.state == "error"
    assert diagnostics.store.status.state == "error"
    assert diagnostics.watchers_status.state == "error"
    assert diagnostics.registries_status.state == "error"


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


def test_startup_probe_waits_for_wud_api_readiness(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_request_json(url: str) -> object:
        calls.append(url)
        if len(calls) == 1:
            raise OSError("connection refused")
        return {"status": "ok"}

    monkeypatch.setattr(web_wud_api, "_request_json", fake_request_json)
    monkeypatch.setattr(
        web_wud_api,
        "WUD_API_STARTUP_RETRY_INTERVAL_SECONDS",
        0.0,
    )
    settings = load_web_settings(
        environ=_web_env(
            tmp_path,
            {
                "WUD_API_BASE_URL": "https://wud.startup-wait.test:3000",
                "WUD_API_STARTUP_WAIT_SECONDS": "1",
            },
        ),
    )

    snapshot = web_wud_api.startup_probe(settings)

    assert snapshot.status.state == "ready"
    assert snapshot.status.available is True
    assert len(calls) == 2


@pytest.mark.parametrize("value", ["soon", "-1", "nan", "inf"])
def test_wud_api_startup_wait_rejects_invalid_values(
    tmp_path: Path,
    value: str,
) -> None:
    with pytest.raises(WebConfigError):
        load_web_settings(
            environ=_web_env(
                tmp_path,
                {"WUD_API_STARTUP_WAIT_SECONDS": value},
            ),
        )


def test_pending_source_rejects_invalid_values(tmp_path: Path) -> None:
    with pytest.raises(WebConfigError) as exc_info:
        load_web_settings(
            environ=_web_env(
                tmp_path,
                {"WUD_PENDING_SOURCE": "queue"},
            ),
        )

    assert str(exc_info.value) == "WUD_PENDING_SOURCE must be one of: api, auto, file"


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


def test_wud_api_snapshot_reports_degraded_after_ready_cache_expires(
    tmp_path: Path,
    monkeypatch,
) -> None:
    api = _ToggleableWudApi(monkeypatch, reachable=True)
    settings = _settings(tmp_path, "http://wud.cache-expiry.test:3000")

    ready = web_wud_api.get_snapshot(
        settings,
        include_containers=True,
        force=True,
    )
    assert ready.status.state == "ready"
    assert ready.status.metadata_available is True

    api.reachable = False
    api.now = web_wud_api.WUD_API_CACHE_TTL_SECONDS / 2
    cached = web_wud_api.get_snapshot(settings, include_containers=True)
    assert cached.status.state == "ready"
    assert api.calls == ["/health", "/api/containers"]

    api.now = web_wud_api.WUD_API_CACHE_TTL_SECONDS + 0.1
    degraded = web_wud_api.get_snapshot(settings, include_containers=True)
    assert degraded.status.state == "unavailable"
    assert degraded.status.metadata_available is False
    assert degraded.containers == ()
    assert api.calls == ["/health", "/api/containers", "/health"]


def test_wud_api_degraded_snapshot_retries_after_short_interval_and_recovers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    api = _ToggleableWudApi(monkeypatch, reachable=False)
    settings = _settings(tmp_path, "http://wud.retry.test:3000")

    unavailable = web_wud_api.get_snapshot(
        settings,
        include_containers=True,
        force=True,
    )
    assert unavailable.status.state == "unavailable"
    assert unavailable.status.metadata_available is False
    assert unavailable.containers == ()
    assert api.calls == ["/health"]

    api.reachable = True
    api.now = web_wud_api.WUD_API_DEGRADED_RETRY_INTERVAL_SECONDS / 2
    cached = web_wud_api.get_snapshot(settings, include_containers=True)
    assert cached.status.state == "unavailable"
    assert cached.status.metadata_available is False
    assert cached.containers == ()
    assert api.calls == ["/health"]

    api.now = web_wud_api.WUD_API_DEGRADED_RETRY_INTERVAL_SECONDS + 0.1
    recovered = web_wud_api.get_snapshot(settings, include_containers=True)
    assert recovered.status.state == "ready"
    assert recovered.status.metadata_available is True
    assert recovered.containers[0].name == "app"
    assert api.calls == ["/health", "/health", "/api/containers"]


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


def test_pending_endpoint_falls_back_after_wud_api_connection_loss(
    tmp_path: Path,
    monkeypatch,
) -> None:
    api = _ToggleableWudApi(monkeypatch, reachable=True)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_API_BASE_URL": "http://wud.pending-loss.test:3000",
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    original = "app\n"
    wud_file.write_text(original, encoding="utf-8")

    ready_response = client.get("/api/v1/pending")
    assert ready_response.status_code == 200
    ready_body = ready_response.json()
    assert ready_body["wud_api"]["metadata_available"] is True
    assert ready_body["items"][0]["wud_metadata"]["name"] == "app"

    api.reachable = False
    api.now = web_wud_api.WUD_API_CACHE_TTL_SECONDS + 0.1
    degraded_response = client.get("/api/v1/pending")

    assert degraded_response.status_code == 200
    degraded_body = degraded_response.json()
    assert degraded_body["count"] == 1
    assert degraded_body["items"][0]["image"] == "app"
    assert degraded_body["items"][0]["wud_metadata"] is None
    assert degraded_body["wud_api"]["state"] == "unavailable"
    assert wud_file.read_text(encoding="utf-8") == original


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

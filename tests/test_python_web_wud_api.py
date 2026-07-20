from __future__ import annotations

import base64
import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from threading import Event, local
from types import SimpleNamespace
from typing import Any

import pytest

from wudup import web_release_notes as release_notes_module
from wudup import web_wud_api
from wudup.config import ConfigError
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
    _wud_image_payload,
)


def _settings(
    tmp_path: Path,
    base_url: str,
    env: dict[str, str] | None = None,
):
    values = {"WUD_API_BASE_URL": base_url}
    if env:
        values.update(env)
    return load_web_settings(
        environ=_web_env(tmp_path, values),
    )


def _container_payload(
    *,
    name: str = "app",
    image: str = "registry.example/acme/app",
    tag: str = "1.0.0",
    remote_tag: str = "1.1.0",
    result_digest: str = "sha256:remote",
    update_kind: str = "tag",
    local_value: str | None = None,
    remote_value: str | None = None,
    source: str = "https://github.com/acme/app",
    link: str = "https://github.com/acme/app/releases/tag/v1.1.0",
    update_available: bool = True,
    platform: dict[str, str] | None = None,
    registry_url: str = "",
) -> dict[str, Any]:
    image_payload = _wud_image_payload(
        image=image,
        tag=tag,
        digest="sha256:local",
        registry_url=registry_url,
        platform=platform,
    )
    return {
        "id": f"docker.local.{name}",
        "name": name,
        "displayName": name.title(),
        "status": "running",
        "watcher": "local",
        "image": image_payload,
        "result": {
            "tag": remote_tag,
            "digest": result_digest,
            "link": link,
        },
        "updateKind": {
            "kind": update_kind,
            "localValue": tag if local_value is None else local_value,
            "remoteValue": remote_tag if remote_value is None else remote_value,
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

    def request_json(self, url: str, _client_config=None) -> object:
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
                _container_payload(
                    name="already-current",
                    update_available=False,
                    remote_value="1.0.0",
                ),
            ],
        ),
    )

    snapshot = web_wud_api.get_snapshot(
        _settings(tmp_path, "https://wud.test:3000"),
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
    assert snapshot.hidden_update_candidates == ()


def test_wud_api_older_forced_refresh_cannot_replace_newer_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    clock = local()
    older_waiting = Event()
    newer_finished = Event()
    calls: list[str] = []

    def monotonic() -> float:
        return getattr(clock, "now", 0.0)

    def request_json(url: str, _client_config=None) -> object:
        path = urllib.parse.urlsplit(url).path
        calls.append(path)
        if path == "/health":
            return {"status": "ok"}
        if path == "/api/containers":
            name = clock.name
            if name == "older":
                older_waiting.set()
                assert newer_finished.wait(timeout=5)
            return [_container_payload(name=name)]
        raise AssertionError(f"unexpected WUD API URL: {url}")

    def refresh(name: str, now: float) -> web_wud_api.WudApiSnapshot:
        clock.name = name
        clock.now = now
        return web_wud_api.get_snapshot(
            settings,
            include_containers=True,
            force=True,
        )

    monkeypatch.setattr(web_wud_api.time, "monotonic", monotonic)
    monkeypatch.setattr(web_wud_api, "_request_json", request_json)
    settings = _settings(tmp_path, "https://wud.concurrent-refresh.test:3000")

    with ThreadPoolExecutor(max_workers=2) as executor:
        older_future = executor.submit(refresh, "older", 1.0)
        assert older_waiting.wait(timeout=5)
        newer = executor.submit(refresh, "newer", 2.0).result(timeout=5)
        newer_finished.set()
        older = older_future.result(timeout=5)

    clock.now = 3.0
    cached = web_wud_api.get_snapshot(settings, include_containers=True)

    assert older.containers[0].name == "older"
    assert newer.containers[0].name == "newer"
    assert cached.containers[0].name == "newer"
    assert calls.count("/api/containers") == 2


def test_wud_api_snapshot_reads_hidden_update_candidates_from_update_kind_delta(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(
        monkeypatch,
        containers=(
            200,
            [
                _container_payload(
                    name="snoozed",
                    update_available=False,
                    update_kind="digest",
                    local_value="sha256:local",
                    remote_value="sha256:remote",
                ),
                _container_payload(
                    name="unknown-kind",
                    update_available=False,
                    update_kind="unknown",
                    local_value="1.0.0",
                    remote_value="1.1.0",
                ),
                _container_payload(
                    name="same-tag",
                    update_available=False,
                    local_value="1.0.0",
                    remote_value="1.0.0",
                ),
            ],
        ),
    )

    snapshot = web_wud_api.get_snapshot(
        _settings(tmp_path, "https://wud.hidden-candidates.test:3000"),
        include_containers=True,
        force=True,
    )

    assert snapshot.containers == ()
    assert len(snapshot.hidden_update_candidates) == 1
    candidate = snapshot.hidden_update_candidates[0]
    assert candidate.name == "snoozed"
    assert candidate.image == "registry.example/acme/app:1.0.0"
    assert candidate.remote_tag == "1.1.0"
    assert candidate.remote_digest == "sha256:remote"
    assert candidate.update_kind == "digest"


def test_wud_api_snapshot_preserves_registry_url_for_unqualified_images(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(
        monkeypatch,
        containers=(
            200,
            [
                _container_payload(
                    name="dozzle",
                    image="amir20/dozzle",
                    tag="v10.6.6",
                    remote_tag="v10.6.7",
                    result_digest="",
                    registry_url="https://ghcr.io",
                ),
                _container_payload(
                    name="explicit",
                    image="ghcr.io/acme/app",
                    registry_url="https://ghcr.io",
                ),
                _container_payload(
                    name="hub",
                    image="library/nginx",
                    registry_url="https://index.docker.io/v1/",
                ),
                _container_payload(
                    name="digest",
                    image="amir20/dozzle@sha256:local",
                    tag="",
                    remote_tag="",
                    result_digest="",
                    registry_url="https://ghcr.io",
                ),
            ],
        ),
    )

    snapshot = web_wud_api.get_snapshot(
        _settings(tmp_path, "https://wud.registry-url.test:3000"),
        include_containers=True,
        force=True,
    )

    images = {container.name: container.image for container in snapshot.containers}
    assert images["dozzle"] == "ghcr.io/amir20/dozzle:v10.6.6"
    assert images["explicit"] == "ghcr.io/acme/app:1.0.0"
    assert images["hub"] == "library/nginx:1.0.0"
    assert images["digest"] == "ghcr.io/amir20/dozzle@sha256:local"


def test_wud_api_snapshot_reads_tag_digest_from_remote_value(
    tmp_path: Path,
    monkeypatch,
) -> None:
    digest = f"sha256:{'b' * 64}"
    _install_wud_api(
        monkeypatch,
        containers=(
            200,
            [
                _container_payload(
                    result_digest="",
                    remote_value=f"registry.example/acme/app:1.1.0@{digest}",
                ),
            ],
        ),
    )

    snapshot = web_wud_api.get_snapshot(
        _settings(tmp_path, "https://wud.tag-digest.test:3000"),
        include_containers=True,
        force=True,
    )

    assert len(snapshot.containers) == 1
    assert snapshot.containers[0].remote_tag == "1.1.0"
    assert snapshot.containers[0].remote_digest == digest


def test_wud_api_watch_uses_longer_timeout_than_metadata_reads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, str, float]] = []

    def response(payload: object):
        return nullcontext(
            SimpleNamespace(read=lambda: json.dumps(payload).encode("utf-8"))
        )

    def urlopen(request, *, timeout: float):
        path = urllib.parse.urlsplit(request.get_full_url()).path
        calls.append((request.get_method(), path, timeout))
        if path == "/health":
            return response({"status": "ok"})
        if path == "/api/containers/watch":
            return response({"status": "ok"})
        if path == "/api/containers":
            return response([_container_payload()])
        raise AssertionError(f"unexpected WUD API URL: {request.get_full_url()}")

    monkeypatch.setattr(web_wud_api.urllib.request, "urlopen", urlopen)

    watch = web_wud_api.watch_all(_settings(tmp_path, "https://wud.timeout.test:3000"))

    assert watch.watched is True
    assert (
        "POST",
        "/api/containers/watch",
        web_wud_api.WUD_API_WATCH_TIMEOUT_SECONDS,
    ) in calls
    assert (
        "GET",
        "/api/containers",
        web_wud_api.WUD_API_TIMEOUT_SECONDS,
    ) in calls
    assert {
        timeout
        for _method, path, timeout in calls
        if path == "/health"
    } == {web_wud_api.WUD_API_TIMEOUT_SECONDS}


def test_container_triggers_ignores_non_object_entries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def request_json(_url: str, _client_config=None) -> object:
        return [
            {
                "id": "discord.release",
                "type": "discord",
                "name": "release",
            },
            "not-a-trigger",
            None,
        ]

    monkeypatch.setattr(web_wud_api, "_request_json", request_json)

    triggers, warning = web_wud_api.container_triggers(
        _settings(tmp_path, "https://wud.triggers.test:3000"),
        "docker.local.app",
    )

    assert warning == ""
    assert [trigger.model_dump() for trigger in triggers] == [
        {"id": "discord.release", "type": "discord", "name": "release"}
    ]


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


def test_wud_api_bearer_auth_applies_to_get_and_post_requests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bearer_value = "fixture-bearer-value"
    calls: list[tuple[str, str, dict[str, str]]] = []

    def request_json(url: str, client_config=None) -> object:
        path = urllib.parse.urlsplit(url).path
        calls.append(("GET", path, web_wud_api._request_headers(client_config)))
        if path == "/health":
            return {"status": "ok"}
        if path == "/api/containers":
            return [_container_payload(name="app")]
        raise AssertionError(f"unexpected WUD API URL: {url}")

    def post_json(url: str, client_config=None, **_kwargs) -> object:
        path = urllib.parse.urlsplit(url).path
        calls.append(("POST", path, web_wud_api._request_headers(client_config)))
        return {"status": "ok"}

    monkeypatch.setattr(web_wud_api, "_request_json", request_json)
    monkeypatch.setattr(web_wud_api, "_post_json", post_json)
    settings = _settings(
        tmp_path,
        "https://wud.auth-header.test:3000",
        {web_wud_api.WUD_API_AUTH_BEARER_TOKEN_ENV: bearer_value},
    )

    snapshot = web_wud_api.get_snapshot(settings, include_containers=True, force=True)
    watch = web_wud_api.watch_all(settings)

    assert snapshot.status.state == "ready"
    assert watch.watched is True
    assert calls
    assert {
        (method, path)
        for method, path, _headers in calls
    } >= {
        ("GET", "/health"),
        ("GET", "/api/containers"),
        ("POST", "/api/containers/watch"),
    }
    for _method, _path, headers in calls:
        assert headers["Authorization"] == f"Bearer {bearer_value}"
        assert headers["Accept"] == "application/json"
        assert headers["User-Agent"] == web_wud_api.WUD_API_USER_AGENT


def test_wud_api_basic_auth_password_file_builds_authorization_header(
    tmp_path: Path,
) -> None:
    password_file = tmp_path / "wud-api-basic-password"
    password_file.write_text("basic-password-secret\n", encoding="utf-8")
    settings = _settings(
        tmp_path,
        "https://wud.basic-auth.test:3000",
        {
            web_wud_api.WUD_API_AUTH_BASIC_USER_ENV: "wud-user",
            web_wud_api.WUD_API_AUTH_BASIC_PASSWORD_FILE_ENV: str(password_file),
        },
    )
    expected_token = base64.b64encode(
        b"wud-user:basic-password-secret"
    ).decode("ascii")

    headers = web_wud_api._request_headers(settings.wud_api_client)

    assert headers["Authorization"] == f"Basic {expected_token}"
    assert "basic-password-secret" in settings.wud_api_client.secret_values
    assert headers["Authorization"] in settings.wud_api_client.secret_values


def test_wud_api_static_json_headers_are_added_to_requests(tmp_path: Path) -> None:
    headers_file = tmp_path / "wud-api-headers.json"
    headers_file.write_text(
        json.dumps(
            {
                "X-Api-Key": "static-header-secret",
                "X-WUD-Trace": "enabled",
            }
        ),
        encoding="utf-8",
    )

    settings = _settings(
        tmp_path,
        "https://wud.static-headers.test:3000",
        {web_wud_api.WUD_API_HEADERS_FILE_ENV: str(headers_file)},
    )
    headers = web_wud_api._request_headers(settings.wud_api_client)

    assert headers["X-Api-Key"] == "static-header-secret"
    assert headers["X-WUD-Trace"] == "enabled"
    assert headers["Accept"] == "application/json"
    assert "static-header-secret" in settings.wud_api_client.secret_values


def test_wud_api_static_json_headers_file_read_error(tmp_path: Path) -> None:
    env = {
        web_wud_api.WUD_API_HEADERS_FILE_ENV: str(tmp_path / "missing-headers.json"),
    }

    with pytest.raises(WebConfigError) as excinfo:
        _settings(tmp_path, "https://wud.static-headers.test:3000", env)

    assert str(excinfo.value) == "WUD_API_HEADERS_FILE could not be read"


def test_wud_api_client_config_fingerprint_is_opaque_without_secret_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tokens = iter(("opaque-one", "opaque-two", "opaque-three"))
    monkeypatch.setattr(web_wud_api.secrets, "token_hex", lambda _bytes: next(tokens))
    base_url = "https://wud.fingerprint.test:3000"
    first = _settings(
        tmp_path,
        base_url,
        {web_wud_api.WUD_API_AUTH_BEARER_TOKEN_ENV: "same-token-secret"},
    )
    second = _settings(
        tmp_path,
        base_url,
        {web_wud_api.WUD_API_AUTH_BEARER_TOKEN_ENV: "same-token-secret"},
    )
    third = _settings(
        tmp_path,
        base_url,
        {web_wud_api.WUD_API_AUTH_BEARER_TOKEN_ENV: "other-token-secret"},
    )

    fingerprint = first.wud_api_client.fingerprint

    assert fingerprint == "opaque-one"
    assert second.wud_api_client.fingerprint == "opaque-two"
    assert third.wud_api_client.fingerprint == "opaque-three"
    assert "same-token-secret" not in fingerprint
    assert "Bearer" not in fingerprint


def test_wud_api_auth_rejected_state_mentions_configured_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, health=(401, {"error": "authentication required"}))

    snapshot = web_wud_api.get_snapshot(
        _settings(
            tmp_path,
            "https://wud.rejected-auth.test:3000",
            {
                web_wud_api.WUD_API_AUTH_BEARER_TOKEN_ENV: (
                    "wud-api-rejected-secret"
                )
            },
        ),
        include_containers=True,
        force=True,
    )

    assert snapshot.status.state == "auth_required"
    assert snapshot.status.detail == "configured WUD API credentials were rejected"


def test_wud_api_snapshot_cache_is_separated_by_auth_headers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    def request_json(url: str, client_config=None) -> object:
        path = urllib.parse.urlsplit(url).path
        authorization = web_wud_api._request_headers(client_config)["Authorization"]
        calls.append(f"{authorization} {path}")
        if path == "/health":
            return {"status": "ok"}
        if path == "/api/containers":
            name = "one" if authorization.endswith("one-token") else "two"
            return [_container_payload(name=name)]
        raise AssertionError(f"unexpected WUD API URL: {url}")

    monkeypatch.setattr(web_wud_api, "_request_json", request_json)
    base_url = "https://wud.auth-cache.test:3000"
    first_settings = _settings(
        tmp_path,
        base_url,
        {web_wud_api.WUD_API_AUTH_BEARER_TOKEN_ENV: "one-token"},
    )
    second_settings = _settings(
        tmp_path,
        base_url,
        {web_wud_api.WUD_API_AUTH_BEARER_TOKEN_ENV: "two-token"},
    )

    first = web_wud_api.get_snapshot(
        first_settings,
        include_containers=True,
        force=True,
    )
    second = web_wud_api.get_snapshot(second_settings, include_containers=True)

    assert first.containers[0].name == "one"
    assert second.containers[0].name == "two"
    assert calls == [
        "Bearer one-token /health",
        "Bearer one-token /api/containers",
        "Bearer two-token /health",
        "Bearer two-token /api/containers",
    ]


def test_wud_api_auth_config_values_are_redacted_from_details(tmp_path: Path) -> None:
    token_file = tmp_path / "wud-api-token"
    token_file.write_text("file-token-secret\n", encoding="utf-8")
    headers_file = tmp_path / "wud-api-headers.json"
    headers_file.write_text(
        json.dumps({"X-Api-Key": "static-header-secret"}),
        encoding="utf-8",
    )
    settings = _settings(
        tmp_path,
        "https://wud.redaction.test:3000",
        {
            web_wud_api.WUD_API_AUTH_BEARER_TOKEN_FILE_ENV: str(token_file),
            web_wud_api.WUD_API_HEADERS_FILE_ENV: str(headers_file),
        },
    )

    detail = web_wud_api._sanitize_detail(
        settings,
        "file-token-secret static-header-secret Bearer file-token-secret",
    )

    assert "file-token-secret" not in detail
    assert "static-header-secret" not in detail
    assert detail.count("<redacted>") == 3


def test_wud_api_auth_config_rejects_malformed_inputs(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("file-token-secret\n", encoding="utf-8")
    empty_file = tmp_path / "empty"
    empty_file.write_text("\n", encoding="utf-8")
    bad_json_file = tmp_path / "headers-bad-json"
    bad_json_file.write_text("{not json", encoding="utf-8")
    unreadable_headers = tmp_path / "headers-unreadable"
    unreadable_headers.mkdir()
    empty_headers = tmp_path / "headers-empty"
    empty_headers.write_text("", encoding="utf-8")
    non_object_headers = tmp_path / "headers-list"
    non_object_headers.write_text("[]", encoding="utf-8")
    non_string_headers = tmp_path / "headers-non-string"
    non_string_headers.write_text(json.dumps({"X-Api-Key": 7}), encoding="utf-8")
    invalid_name_headers = tmp_path / "headers-invalid-name"
    invalid_name_headers.write_text(
        json.dumps({"X Invalid Header": "value"}),
        encoding="utf-8",
    )
    duplicate_headers = tmp_path / "headers-duplicate"
    duplicate_headers.write_text(
        json.dumps({"X-Api-Key": "one", "x-api-key": "two"}),
        encoding="utf-8",
    )
    newline_headers = tmp_path / "headers-newline"
    newline_headers.write_text(
        json.dumps({"X-Api-Key": "bad\nvalue"}),
        encoding="utf-8",
    )
    cr_newline_headers = tmp_path / "headers-cr-newline"
    cr_newline_headers.write_text(
        json.dumps({"X-Api-Key": "bad\r\nvalue"}),
        encoding="utf-8",
    )
    auth_headers = tmp_path / "headers-auth"
    auth_headers.write_text(
        json.dumps({"Authorization": "Bearer static-secret"}),
        encoding="utf-8",
    )

    cases = [
        (
            {
                web_wud_api.WUD_API_AUTH_BEARER_TOKEN_ENV: "direct-token",
                web_wud_api.WUD_API_AUTH_BEARER_TOKEN_FILE_ENV: str(token_file),
            },
            "cannot both be set",
        ),
        (
            {
                web_wud_api.WUD_API_AUTH_BEARER_TOKEN_FILE_ENV: str(empty_file),
            },
            "must not be empty",
        ),
        (
            {
                web_wud_api.WUD_API_AUTH_BEARER_TOKEN_FILE_ENV: str(
                    tmp_path / "missing-token"
                ),
            },
            "could not be read",
        ),
        (
            {
                web_wud_api.WUD_API_AUTH_BEARER_TOKEN_ENV: "direct-token",
                web_wud_api.WUD_API_AUTH_BASIC_USER_ENV: "wud-user",
                web_wud_api.WUD_API_AUTH_BASIC_PASSWORD_ENV: "basic-password",
            },
            "bearer and basic auth cannot both be configured",
        ),
        (
            {web_wud_api.WUD_API_AUTH_BASIC_USER_ENV: "wud-user"},
            "must be set together",
        ),
        (
            {web_wud_api.WUD_API_HEADERS_FILE_ENV: str(bad_json_file)},
            "must contain a JSON object",
        ),
        (
            {web_wud_api.WUD_API_HEADERS_FILE_ENV: str(unreadable_headers)},
            "could not be read",
        ),
        (
            {web_wud_api.WUD_API_HEADERS_FILE_ENV: str(empty_headers)},
            "must contain a JSON object",
        ),
        (
            {web_wud_api.WUD_API_HEADERS_FILE_ENV: str(non_object_headers)},
            "must contain a JSON object",
        ),
        (
            {web_wud_api.WUD_API_HEADERS_FILE_ENV: str(invalid_name_headers)},
            "contains an invalid header",
        ),
        (
            {web_wud_api.WUD_API_HEADERS_FILE_ENV: str(duplicate_headers)},
            "must not define duplicate headers",
        ),
        (
            {web_wud_api.WUD_API_HEADERS_FILE_ENV: str(non_string_headers)},
            "values must be strings",
        ),
        (
            {web_wud_api.WUD_API_HEADERS_FILE_ENV: str(newline_headers)},
            "must not contain newlines",
        ),
        (
            {web_wud_api.WUD_API_HEADERS_FILE_ENV: str(cr_newline_headers)},
            "must not contain newlines",
        ),
        (
            {
                web_wud_api.WUD_API_AUTH_BEARER_TOKEN_ENV: "direct-token",
                web_wud_api.WUD_API_HEADERS_FILE_ENV: str(auth_headers),
            },
            "must not define Authorization",
        ),
    ]

    for env, expected in cases:
        with pytest.raises(WebConfigError, match=expected):
            _settings(tmp_path, f"https://wud.invalid-{len(expected)}.test:3000", env)


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
        _settings(tmp_path, "https://wud.unreachable.test:3000"),
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

    def fake_request_json(url: str, _client_config=None) -> object:
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


def test_pending_source_defaults_to_api(tmp_path: Path) -> None:
    settings = load_web_settings(environ=_web_env(tmp_path))

    assert settings.pending_source == "api"


def test_legacy_scripts_rejects_invalid_bool(tmp_path: Path) -> None:
    environ = _web_env(
        tmp_path,
        {"WUDUP_LEGACY_SCRIPTS": "treu"},
    )

    with pytest.raises(ConfigError, match="WUDUP_LEGACY_SCRIPTS"):
        load_web_settings(environ=environ)


def test_wud_api_snapshot_reports_auth_required_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(
        monkeypatch,
        containers=(401, {"error": "authentication required"}),
    )

    snapshot = web_wud_api.get_snapshot(
        _settings(tmp_path, "https://wud.auth.test:3000"),
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
        _settings(tmp_path, "https://wud.invalid.test:3000"),
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
    settings = _settings(tmp_path, "https://wud.cache-expiry.test:3000")

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
    settings = _settings(tmp_path, "https://wud.retry.test:3000")

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
            "WUD_API_BASE_URL": "https://wud.startup.test:3000",
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
    _install_wud_api(
        monkeypatch,
        containers=(
            200,
            [
                _container_payload(
                    name="app",
                    platform={
                        "os": "linux",
                        "architecture": "arm64",
                        "variant": "v8",
                    },
                )
            ],
        ),
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_API_BASE_URL": "https://wud.pending.test:3000",
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
    assert metadata["platform"] == "linux/arm64/v8"
    assert metadata["platform_os"] == "linux"
    assert metadata["platform_architecture"] == "arm64"
    assert metadata["platform_variant"] == "v8"
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
            "WUD_API_BASE_URL": "https://wud.fallback.test:3000",
            "WUD_PENDING_SOURCE": "auto",
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
            "WUD_API_BASE_URL": "https://wud.pending-loss.test:3000",
            "WUD_PENDING_SOURCE": "auto",
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
            "WUD_API_BASE_URL": "https://wud.release-notes.test:3000",
            "WUD_PENDING_SOURCE": "file",
            "WUD_RELEASE_NOTES_ENABLED": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
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

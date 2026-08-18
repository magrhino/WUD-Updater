from __future__ import annotations

import json
import sqlite3
import urllib.parse
from pathlib import Path
from urllib.error import HTTPError

from tests.web_test_helpers import _client, _csrf_headers, _install_wud_api
from tests.web_wud_rescan_helpers import (
    container_payload,
    degraded_container_payload,
    install_recording_wud_api,
    rescan_payload,
    settings,
)

from wudup import web_pending_rescan_audit, web_wud_api
from wudup.db import open_db


def test_pending_rescan_endpoint_enforces_auth_csrf_and_read_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        web_wud_api,
        "_request_json",
        lambda url, _client_config=None: {"status": "ok"},
    )
    monkeypatch.setattr(
        web_wud_api,
        "_post_json",
        lambda url, _client_config=None, **_kwargs: {"status": "ok"},
    )
    payload = rescan_payload()
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
        "/api/v1/pending/rescan",
        json=payload,
        headers=_csrf_headers(unauthenticated),
    )
    missing_csrf = mutating.post("/api/v1/pending/rescan", json=payload)
    read_only_response = read_only.post(
        "/api/v1/pending/rescan",
        json=payload,
        headers=_csrf_headers(read_only),
    )
    get_response = mutating.get("/api/v1/pending/rescan")

    assert auth_response.status_code == 403
    assert auth_response.json()["detail"] == "setup required"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "origin header is required"
    assert read_only_response.status_code == 403
    assert read_only_response.json()["detail"] == "mutations are disabled"
    assert get_response.status_code == 405


def test_pending_all_rescan_targets_pending_container_ids_and_audits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = install_recording_wud_api(
        monkeypatch,
        [container_payload(name="app")],
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_API_BASE_URL": "https://wud.rescan-all.test:3000",
        },
    )
    calls.clear()

    response = client.post(
        "/api/v1/pending/rescan",
        json=rescan_payload(),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["scope"] == "all"
    assert body["requested_count"] == 1
    assert body["watched_count"] == 1
    assert body["wud_api"]["metadata_available"] is True
    assert calls == [
        ("GET", "/health"),
        ("GET", "/api/containers"),
        ("GET", "/health"),
        ("POST", "/api/containers/docker.local.app/watch"),
        ("GET", "/health"),
        ("GET", "/api/containers"),
    ]
    assert ("POST", "/api/containers/watch") not in calls
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        run = conn.execute(
            "SELECT * FROM update_runs WHERE id = ?",
            (body["audit_run_id"],),
        ).fetchone()
    assert run["mode"] == "web-wud-rescan"
    assert run["status"] == "success"
    metadata = json.loads(run["metadata_json"])
    assert metadata["operation"] == "rescan_wud"
    assert metadata["scope"] == "all"
    assert metadata["requested_count"] == 1
    assert metadata["watched_count"] == 1
    assert metadata["wud_api"]["state"] == "ready"


def test_pending_all_rescan_continues_after_missing_container_and_audits_partial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(
        monkeypatch,
        containers=[
            container_payload(name="missing"),
            container_payload(name="app"),
        ],
    )
    posts: list[str] = []

    def post_json(url: str, _client_config=None, **_kwargs) -> object:
        path = urllib.parse.urlsplit(url).path
        posts.append(path)
        if len(posts) == 1:
            raise HTTPError(url=url, code=404, msg="Not Found", hdrs=None, fp=None)
        return {"status": "ok"}

    monkeypatch.setattr(web_wud_api, "_post_json", post_json)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_API_BASE_URL": "https://wud.rescan-missing.test:3000",
        },
    )

    response = client.post(
        "/api/v1/pending/rescan",
        json=rescan_payload(),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["requested_count"] == 2
    assert body["watched_count"] == 1
    assert "WUD skipped 1 container that no longer exists" in body["wud_api"]["detail"]
    assert len(posts) == 2
    assert set(posts) == {
        "/api/containers/docker.local.missing/watch",
        "/api/containers/docker.local.app/watch",
    }
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        run = conn.execute(
            "SELECT * FROM update_runs WHERE id = ?",
            (body["audit_run_id"],),
        ).fetchone()
    metadata = json.loads(run["metadata_json"])
    assert run["status"] == "success"
    assert metadata["status"] == "partial"
    assert metadata["requested_count"] == 2
    assert metadata["watched_count"] == 1


def test_pending_all_rescan_scopes_embedded_429_cooldown_to_container(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pending = container_payload(name="app")
    degraded = degraded_container_payload(
        name="bazarr",
        image="ghcr.io/linuxserver/bazarr",
    )
    unsupported = degraded_container_payload(
        name="socket-proxy",
        image="lscr.io/linuxserver/socket-proxy",
        error="Unsupported Registry unknown",
    )
    containers = [pending, degraded, unsupported]
    calls = install_recording_wud_api(
        monkeypatch,
        containers,
        post_container=lambda path: degraded
        if path == "/api/containers/docker.local.bazarr/watch"
        else pending,
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_PENDING_SOURCE": "api",
            "WUDUP_LEGACY_SCRIPTS": "false",
            "WUD_API_BASE_URL": "https://wud.rescan-429.test:3000",
        },
    )
    calls.clear()

    response = client.post(
        "/api/v1/pending/rescan",
        json=rescan_payload(),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["requested_count"] == 2
    assert body["watched_count"] == 2
    assert [path for method, path in calls if method == "POST"] == [
        "/api/containers/docker.local.bazarr/watch",
        "/api/containers/docker.local.app/watch",
    ]
    assert "Update status is unknown for 1 container" in body["wud_api"]["detail"]

    calls.clear()
    cooldown = client.post(
        "/api/v1/pending/rescan",
        json=rescan_payload(),
        headers=_csrf_headers(client),
    )

    assert cooldown.status_code == 200
    assert cooldown.json()["status"] == "partial"
    assert cooldown.json()["watched_count"] == 1
    assert "WUD temporarily paused registry checks" in (
        cooldown.json()["wud_api"]["detail"]
    )
    assert [path for method, path in calls if method == "POST"] == [
        "/api/containers/docker.local.app/watch"
    ]


def test_pending_all_rescan_succeeds_after_degraded_container_clears(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pending = container_payload(name="app")
    degraded = degraded_container_payload(
        name="bazarr",
        image="ghcr.io/linuxserver/bazarr",
    )
    unsupported = degraded_container_payload(
        name="socket-proxy",
        image="lscr.io/linuxserver/socket-proxy",
        error="Unsupported Registry unknown",
    )
    cleared = container_payload(
        name="bazarr",
        image="ghcr.io/linuxserver/bazarr",
        update_available=False,
    )
    containers = [pending, degraded, unsupported]

    def post_container(path: str) -> object:
        if path == "/api/containers/docker.local.bazarr/watch":
            containers[1] = cleared
            return cleared
        return pending

    calls = install_recording_wud_api(
        monkeypatch,
        containers,
        post_container=post_container,
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_PENDING_SOURCE": "api",
            "WUDUP_LEGACY_SCRIPTS": "false",
            "WUD_API_BASE_URL": "https://wud.rescan-cleared.test:3000",
        },
    )
    calls.clear()

    response = client.post(
        "/api/v1/pending/rescan",
        json=rescan_payload(),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["requested_count"] == 2
    assert body["watched_count"] == 2
    assert [path for method, path in calls if method == "POST"] == [
        "/api/containers/docker.local.bazarr/watch",
        "/api/containers/docker.local.app/watch",
    ]
    assert ("POST", "/api/containers/watch") not in calls


def test_pending_rescan_does_not_watch_when_audit_start_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = install_recording_wud_api(monkeypatch, [container_payload(name="app")])

    def fail_audit(*_args, **_kwargs):
        raise sqlite3.Error("database is locked")

    monkeypatch.setattr(
        web_pending_rescan_audit,
        "insert_pending_rescan_audit_start",
        fail_audit,
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_API_BASE_URL": "https://wud.rescan-audit-fails.test:3000",
        },
    )
    calls.clear()

    response = client.post(
        "/api/v1/pending/rescan",
        json=rescan_payload(),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 500
    assert response.json()["detail"].startswith("could not record WUD rescan audit")
    assert calls == []


def test_pending_rescan_reports_wud_api_unavailable_without_file_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, health=OSError("connection refused"))
    posts: list[str] = []
    monkeypatch.setattr(
        web_wud_api,
        "_post_json",
        lambda url, _client_config=None, **_kwargs: posts.append(
            urllib.parse.urlsplit(url).path
        ),
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_API_BASE_URL": "https://wud.rescan-unavailable.test:3000",
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    original = "repo/app:1.0\n"
    wud_file.write_text(original, encoding="utf-8")

    response = client.post(
        "/api/v1/pending/rescan",
        json=rescan_payload(),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["wud_api"]["state"] == "unavailable"
    assert posts == []
    assert wud_file.read_text(encoding="utf-8") == original
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        run = conn.execute(
            "SELECT * FROM update_runs WHERE id = ?",
            (body["audit_run_id"],),
        ).fetchone()
    assert run["status"] == "failure"


def test_pending_rescan_reports_wud_api_auth_required_without_watch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, health=(401, {"error": "authentication required"}))
    posts: list[str] = []
    monkeypatch.setattr(
        web_wud_api,
        "_post_json",
        lambda url, _client_config=None, **_kwargs: posts.append(
            urllib.parse.urlsplit(url).path
        ),
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_API_BASE_URL": "https://wud.rescan-auth.test:3000",
        },
    )

    response = client.post(
        "/api/v1/pending/rescan",
        json=rescan_payload(),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert response.json()["wud_api"]["state"] == "auth_required"
    assert posts == []


def test_pending_rescan_reports_wud_watch_auth_required_on_http_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    base_url = "https://wud.rescan-watch-auth.test:3000"
    _install_wud_api(monkeypatch, containers=[container_payload(name="app")])
    posts: list[str] = []

    def raise_watch_http_error(url: str, _client_config=None, **_kwargs) -> object:
        posts.append(urllib.parse.urlsplit(url).path)
        raise HTTPError(
            url=url,
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(web_wud_api, "_post_json", raise_watch_http_error)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_API_BASE_URL": base_url,
        },
    )

    response = client.post(
        "/api/v1/pending/rescan",
        json=rescan_payload(),
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["wud_api"]["state"] == "auth_required"
    assert body["wud_api"]["detail"] == "WUD API watch request requires authentication"
    assert posts == ["/api/containers/docker.local.app/watch"]
    snapshot = web_wud_api.get_snapshot(
        settings(tmp_path, base_url),
        include_containers=True,
    )
    assert snapshot.status.state == body["wud_api"]["state"]
    assert snapshot.status.detail == body["wud_api"]["detail"]
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        run = conn.execute(
            "SELECT * FROM update_runs WHERE id = ?",
            (body["audit_run_id"],),
        ).fetchone()
    assert run["status"] == "failure"
    metadata = json.loads(run["metadata_json"])
    assert metadata["status"] == "blocked"
    assert metadata["wud_api"]["state"] == "auth_required"

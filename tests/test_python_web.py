from __future__ import annotations

import json
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient

from wud_updater import web as web_module
from wud_updater.db import (
    connect_db,
    init_db,
    insert_pending_update,
    insert_update_event,
    insert_update_run,
)
from wud_updater.locks import DirectoryLock, WudLockError, lock_dir_for
from wud_updater.web import create_app


def _web_env(
    tmp_path: Path,
    env: dict[str, str] | None = None,
    *,
    create_root: bool = True,
) -> dict[str, str]:
    root = tmp_path / "state"
    if create_root:
        root.mkdir(exist_ok=True)
    wud_file = root / "images.todo"
    db_path = root / "wud.sqlite"
    values = {
        "HOME": str(tmp_path),
        "DOCKER_BASE": str(tmp_path / "docker"),
        "WUD_OUT_FILE": str(wud_file),
        "WUD_LOG_DIR": str(root / "logs"),
        "WUD_DB_PATH": str(db_path),
        "WUD_WEB_ALLOWED_HOSTS": "testserver",
    }
    if env:
        values.update(env)
    return values


def _client(
    tmp_path: Path,
    env: dict[str, str] | None = None,
    *,
    create_root: bool = True,
) -> TestClient:
    values = _web_env(tmp_path, env, create_root=create_root)
    return TestClient(create_app(environ=values))


def _csrf_headers(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return {
        "Origin": "http://testserver",
        "x-wud-csrf-token": response.json()["csrf_token"],
    }


def _setup_admin(
    client: TestClient,
    *,
    username: str = "admin",
    password: str = "correct horse battery staple",
) -> None:
    claim = client.app.state.web_setup_claim
    response = client.post(
        "/api/v1/setup/claim",
        json={"claim": claim, "username": username, "password": password},
        headers=_csrf_headers(client),
    )
    assert response.status_code == 200


def _contains_key(value: object, target: str) -> bool:
    if isinstance(value, dict):
        return target in value or any(
            _contains_key(item, target) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(item, target) for item in value)
    return False


def _insert_run(tmp_path: Path, *, log_file: str = "") -> int:
    db_path = tmp_path / "state" / "wud.sqlite"
    with connect_db(db_path) as conn:
        init_db(conn)
        return insert_update_run(
            conn,
            started_at="2026-05-27T12:00:00+00:00",
            status="success",
            dry_run=True,
            mode="stop",
            wud_file="/out/images.todo",
            log_file=log_file,
            metadata_json='{"source":"test"}',
        )


def _fake_docker_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    fake_root = tmp_path / "fake-docker"
    for path in (
        fake_root / "images",
        fake_root / "manifests",
        fake_root / "stacks",
        fake_root / "containers",
    ):
        path.mkdir(parents=True, exist_ok=True)
    (fake_root / "containers.tsv").write_text("", encoding="utf-8")
    (fake_root / "calls.log").write_text("", encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    return (
        {
            "FAKE_DOCKER_ROOT": str(fake_root),
            "PATH": f"{repo_root / 'tests' / 'fakes'}:{os.environ['PATH']}",
        },
        fake_root,
    )


def _make_fake_stack(
    tmp_path: Path,
    fake_root: Path,
    stack_id: str,
    services: list[tuple[str, str, str | None]],
) -> Path:
    directory = tmp_path / "docker" / stack_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".fake-docker-id").write_text(f"{stack_id}\n", encoding="utf-8")
    stack_state = fake_root / "stacks" / stack_id
    stack_state.mkdir(parents=True, exist_ok=True)

    compose_lines = ["services:\n"]
    service_rows: list[str] = []
    image_rows: list[str] = []
    cids: list[str] = []
    for service, image, cid in services:
        compose_lines.extend([f"  {service}:\n", f"    image: {image}\n"])
        service_rows.append(f"{service}\n")
        image_rows.append(f"{image}\n")
        with (stack_state / "service-images.tsv").open("a", encoding="utf-8") as file:
            file.write(f"{service}\t{image}\n")
        if cid is None:
            continue
        cids.append(cid)
        (stack_state / f"cids-{service}.txt").write_text(
            f"{cid}\n",
            encoding="utf-8",
        )
        (fake_root / "containers" / f"{cid}.summary").write_text(
            f"/{cid}|running|healthy|0|0\n",
            encoding="utf-8",
        )

    (directory / "docker-compose.yml").write_text(
        "".join(compose_lines),
        encoding="utf-8",
    )
    (stack_state / "services.txt").write_text("".join(service_rows), encoding="utf-8")
    (stack_state / "images.txt").write_text("".join(image_rows), encoding="utf-8")
    (stack_state / "cids.txt").write_text(
        "".join(f"{cid}\n" for cid in cids),
        encoding="utf-8",
    )
    return directory


def _fake_docker_calls(fake_root: Path) -> str:
    return (fake_root / "calls.log").read_text(encoding="utf-8")


def _wait_apply_job(client: TestClient, job_id: str) -> dict[str, object]:
    deadline = time.time() + 5
    while time.time() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] not in {"queued", "running"}:
            return body
        time.sleep(0.02)
    raise AssertionError(f"apply job {job_id} did not finish")


def _sse_job_events(content: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in content.split("\n\n"):
        event_name = ""
        data: list[str] = []
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data.append(line.removeprefix("data: "))
        if event_name == "job" and data:
            events.append(json.loads("\n".join(data)))
    return events


def test_api_rejects_unauthenticated_requests_without_dev_bypass(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    response = client.get("/api/v1/status")

    assert response.status_code == 403
    assert response.json()["detail"] == "setup required"


def test_api_accepts_bearer_token(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_TOKEN": "secret"})
    _setup_admin(client)
    api_client = _client(tmp_path, {"WUD_WEB_TOKEN": "secret"})

    response = api_client.get(
        "/api/v1/status",
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200
    assert response.json()["auth_required"] is True


def test_csrf_endpoint_sets_double_submit_cookie(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/v1/auth/csrf")

    assert response.status_code == 200
    assert response.json()["csrf_token"]
    assert client.cookies.get("wud_csrf_token") == response.json()["csrf_token"]


def test_first_run_setup_claim_creates_admin_and_burns_claim(tmp_path: Path) -> None:
    client = _client(tmp_path)
    claim = client.app.state.web_setup_claim

    before = client.get("/api/v1/setup/status")
    setup_response = client.post(
        "/api/v1/setup/claim",
        json={
            "claim": claim,
            "username": "admin",
            "password": "correct horse battery staple",
        },
        headers=_csrf_headers(client),
    )
    status_response = client.get("/api/v1/status")
    replay_response = client.post(
        "/api/v1/setup/claim",
        json={
            "claim": claim,
            "username": "other",
            "password": "correct horse battery staple",
        },
        headers=_csrf_headers(client),
    )
    after = client.get("/api/v1/setup/status")

    assert before.status_code == 200
    assert before.json()["setup_required"] is True
    assert claim not in before.text
    assert setup_response.status_code == 200
    assert setup_response.json()["authenticated"] is True
    assert setup_response.json()["setup_required"] is False
    assert status_response.status_code == 200
    assert replay_response.status_code == 409
    assert after.json()["setup_required"] is False


def test_first_run_setup_claim_serializes_concurrent_claims(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path)
    settings = client.app.state.web_settings
    claim = client.app.state.web_setup_claim
    db_path = tmp_path / "state" / "wud.sqlite"

    class SlowPasswordHasher:
        def __init__(self) -> None:
            self.calls = 0
            self.first_hash_started = Event()
            self.release_first_hash = Event()
            self.lock = Lock()

        def hash(self, password: str) -> str:
            with self.lock:
                self.calls += 1
                call = self.calls
            if call == 1:
                self.first_hash_started.set()
                assert self.release_first_hash.wait(timeout=5)
            return f"hashed-{password}-{call}"

    hasher = SlowPasswordHasher()
    monkeypatch.setattr(web_module, "PASSWORD_HASHER", hasher)

    def claim_admin(username: str) -> tuple[str, int | str]:
        try:
            user_id = web_module._claim_initial_admin(
                settings,
                claim,
                username,
                "correct horse battery staple",
            )
        except HTTPException as exc:
            return ("error", exc.status_code)
        return ("ok", user_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(claim_admin, "admin-a")
        assert hasher.first_hash_started.wait(timeout=5)
        second = executor.submit(claim_admin, "admin-b")
        time.sleep(0.1)
        hasher.release_first_hash.set()
        results = [first.result(timeout=5), second.result(timeout=5)]

    with connect_db(db_path) as conn:
        users = conn.execute("SELECT username FROM web_users").fetchall()

    assert sorted(result[0] for result in results) == ["error", "ok"]
    assert ("error", 409) in results
    assert [row["username"] for row in users] == ["admin-a"]
    assert hasher.calls == 1


def test_setup_claim_rejects_expired_secret(tmp_path: Path) -> None:
    client = _client(tmp_path)
    db_path = tmp_path / "state" / "wud.sqlite"
    with connect_db(db_path) as conn:
        conn.execute(
            """
            UPDATE web_settings
            SET value = '2000-01-01T00:00:00+00:00'
            WHERE key = 'setup_claim_expires_at'
            """
        )

    response = client.post(
        "/api/v1/setup/claim",
        json={
            "claim": client.app.state.web_setup_claim,
            "username": "admin",
            "password": "correct horse battery staple",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "setup claim expired"


def test_setup_claim_validation_redacts_submitted_inputs(tmp_path: Path) -> None:
    client = _client(tmp_path)
    submitted_password = "tinysecret!"

    response = client.post(
        "/api/v1/setup/claim",
        json={
            "claim": client.app.state.web_setup_claim,
            "username": "admin",
            "password": submitted_password,
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 422
    assert submitted_password not in response.text
    assert not _contains_key(response.json(), "input")


def test_invalid_setup_claim_does_not_hash_password(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path)

    class ExplodingPasswordHasher:
        def hash(self, _password: str) -> str:
            raise AssertionError("password hash should not be called")

    monkeypatch.setattr(web_module, "PASSWORD_HASHER", ExplodingPasswordHasher())

    response = client.post(
        "/api/v1/setup/claim",
        json={
            "claim": "not-the-claim",
            "username": "admin",
            "password": "correct horse battery staple",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "setup claim is invalid"


def test_browser_token_login_payload_is_not_accepted(tmp_path: Path) -> None:
    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    client = _client(tmp_path, {"WUD_WEB_TOKEN": "secret"})

    response = client.post(
        "/api/v1/auth/login",
        json={"token": "secret"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 422


def test_login_validation_redacts_submitted_inputs(tmp_path: Path) -> None:
    client = _client(tmp_path)
    submitted_password = "x" * 1025

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": submitted_password},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 422
    assert submitted_password not in response.text
    assert not _contains_key(response.json(), "input")


def test_login_sets_http_only_session_cookie(tmp_path: Path) -> None:
    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    client = _client(tmp_path)

    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=_csrf_headers(client),
    )
    status_response = client.get("/api/v1/status")

    assert login_response.status_code == 200
    assert login_response.json()["authenticated"] is True
    assert "wud_session=" in login_response.headers["set-cookie"]
    assert "HttpOnly" in login_response.headers["set-cookie"]
    assert status_response.status_code == 200


def test_login_rejects_wrong_password(tmp_path: Path) -> None:
    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    client = _client(tmp_path)

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 401
    assert client.cookies.get("wud_session") is None


def test_login_requires_csrf_origin_headers(tmp_path: Path) -> None:
    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    client = _client(tmp_path)

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "origin header is required"


def test_session_endpoint_reports_cookie_auth_state(tmp_path: Path) -> None:
    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    client = _client(tmp_path)
    before = client.get("/api/v1/auth/session")

    client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=_csrf_headers(client),
    )
    after = client.get("/api/v1/auth/session")

    assert before.status_code == 200
    assert before.json()["authenticated"] is False
    assert after.status_code == 200
    assert after.json()["authenticated"] is True


def test_logout_clears_session_and_csrf_cookies(tmp_path: Path) -> None:
    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    client = _client(tmp_path)
    headers = _csrf_headers(client)
    client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=headers,
    )

    response = client.post("/api/v1/auth/logout", headers=headers)
    status_response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert client.cookies.get("wud_session") is None
    assert client.cookies.get("wud_csrf_token") is None
    assert status_response.status_code == 401


def test_api_rejects_unauthenticated_requests_after_setup(
    tmp_path: Path,
) -> None:
    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    client = _client(tmp_path)

    response = client.get("/api/v1/status")

    assert response.status_code == 401
    assert response.json()["detail"] == "authentication required"


def test_api_allows_dev_auth_bypass_only_when_explicitly_enabled(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["auth_required"] is False
    assert response.json()["dev_auth_bypass"] is True


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
    assert wud_file.read_text(encoding="utf-8") == original


def test_state_read_endpoints_return_empty_without_creating_missing_database(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    db_path = root / "wud.sqlite"
    client = _client(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true"},
        create_root=False,
    )

    policies = client.get("/api/v1/service-policies")
    snoozes = client.get("/api/v1/snoozes?state=all")
    exclusions = client.get("/api/v1/tag-exclusions?status=all")

    assert policies.status_code == 200
    assert policies.json() == []
    assert snoozes.status_code == 200
    assert snoozes.json() == []
    assert exclusions.status_code == 200
    assert exclusions.json() == []
    assert not root.exists()
    assert not db_path.exists()


def test_state_read_endpoints_list_existing_sqlite_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "state" / "wud.sqlite"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    past = (now - timedelta(hours=1)).isoformat()
    future = (now + timedelta(hours=1)).isoformat()
    with connect_db(db_path) as conn:
        init_db(conn)
        with conn:
            conn.execute(
                """
                INSERT INTO service_policy (
                    service_key,
                    update_mode,
                    auto_update,
                    snooze_default_seconds,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES (
                    'stack/app',
                    'stop',
                    0,
                    3600,
                    '2026-05-28T12:00:00+00:00',
                    '2026-05-28T12:01:00+00:00',
                    '{"source":"test"}'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO snoozes (
                    service_key,
                    snoozed_until,
                    reason,
                    created_at,
                    metadata_json
                )
                VALUES ('stack/app', ?, 'maintenance', ?, '{}')
                """,
                (future, now.isoformat()),
            )
            conn.execute(
                """
                INSERT INTO snoozes (
                    service_key,
                    snoozed_until,
                    reason,
                    created_at,
                    metadata_json
                )
                VALUES ('stack/old', ?, 'expired', ?, '{}')
                """,
                (past, past),
            )
            conn.execute(
                """
                INSERT INTO tag_exclusion_rules (
                    scope,
                    image_repo,
                    service_key,
                    match_type,
                    tag,
                    regex_fragment,
                    status,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES
                    (
                        'image_repo',
                        'repo/app',
                        '',
                        'exact',
                        '2.0',
                        '2\\.0',
                        'active',
                        ?,
                        ?,
                        '{}'
                    ),
                    (
                        'service',
                        'repo/app',
                        'stack/app',
                        'exact',
                        '3.0',
                        '3\\.0',
                        'disabled',
                        ?,
                        ?,
                        '{}'
                    )
                """,
                (now.isoformat(), now.isoformat(), now.isoformat(), now.isoformat()),
            )
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    policies = client.get("/api/v1/service-policies")
    active_snoozes = client.get("/api/v1/snoozes")
    expired_snoozes = client.get("/api/v1/snoozes?state=expired")
    all_exclusions = client.get("/api/v1/tag-exclusions?status=all")
    disabled_exclusions = client.get("/api/v1/tag-exclusions?status=disabled")

    assert policies.status_code == 200
    assert policies.json()[0]["service_key"] == "stack/app"
    assert policies.json()[0]["auto_update"] is False
    assert policies.json()[0]["metadata"] == {"source": "test"}
    assert active_snoozes.status_code == 200
    assert [row["service_key"] for row in active_snoozes.json()] == ["stack/app"]
    assert active_snoozes.json()[0]["active"] is True
    assert expired_snoozes.status_code == 200
    assert [row["service_key"] for row in expired_snoozes.json()] == ["stack/old"]
    assert expired_snoozes.json()[0]["active"] is False
    assert all_exclusions.status_code == 200
    assert [row["status"] for row in all_exclusions.json()] == [
        "active",
        "disabled",
    ]
    assert disabled_exclusions.status_code == 200
    assert disabled_exclusions.json()[0]["service_key"] == "stack/app"


def test_state_operation_endpoint_enforces_auth_csrf_and_read_only(
    tmp_path: Path,
) -> None:
    payload = {
        "kind": "upsert_service_policy",
        "service_key": "stack/app",
        "update_mode": "stop",
    }
    unauthenticated = _client(tmp_path, {"WUD_WEB_MUTATIONS_ENABLED": "true"})
    read_only = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    mutating = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )

    unauthenticated_response = unauthenticated.post(
        "/api/v1/state/operations",
        json=payload,
        headers=_csrf_headers(unauthenticated),
    )
    missing_csrf = mutating.post("/api/v1/state/operations", json=payload)
    read_only_response = read_only.post(
        "/api/v1/state/operations",
        json=payload,
        headers=_csrf_headers(read_only),
    )

    assert unauthenticated_response.status_code == 403
    assert unauthenticated_response.json()["detail"] == "setup required"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "origin header is required"
    assert read_only_response.status_code == 403
    assert read_only_response.json()["detail"] == "mutations are disabled"


def test_state_operations_write_rows_and_audit_entries(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)
    future = (
        datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=1)
    ).isoformat()

    policy = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "pause",
            "auto_update": False,
            "snooze_default_seconds": 600,
        },
        headers=headers,
    )
    deleted_policy = client.post(
        "/api/v1/state/operations",
        json={"kind": "delete_service_policy", "service_key": "stack/app"},
        headers=headers,
    )
    snooze = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "create_snooze",
            "service_key": "stack/app",
            "snoozed_until": future,
            "reason": "maintenance",
        },
        headers=headers,
    )
    snooze_id = snooze.json()["resource"]["id"]
    deleted_snooze = client.post(
        "/api/v1/state/operations",
        json={"kind": "delete_snooze", "snooze_id": snooze_id},
        headers=headers,
    )
    exclusion = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_tag_exclusion",
            "scope": "service",
            "image_repo": "repo/app",
            "service_key": "stack/app",
            "tag": "2.0",
        },
        headers=headers,
    )
    rule_id = exclusion.json()["resource"]["id"]
    disabled_exclusion = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "set_tag_exclusion_status",
            "rule_id": rule_id,
            "status": "disabled",
        },
        headers=headers,
    )

    assert policy.status_code == 200
    assert policy.json()["resource"]["auto_update"] is False
    assert policy.json()["resource"]["snooze_default_seconds"] == 600
    assert deleted_policy.status_code == 200
    assert deleted_policy.json()["resource"] is None
    assert snooze.status_code == 200
    assert snooze.json()["resource"]["reason"] == "maintenance"
    assert deleted_snooze.status_code == 200
    assert deleted_snooze.json()["resource"] is None
    assert exclusion.status_code == 200
    assert exclusion.json()["resource"]["regex_fragment"] == "2\\.0"
    assert disabled_exclusion.status_code == 200
    assert disabled_exclusion.json()["resource"]["status"] == "disabled"

    db_path = tmp_path / "state" / "wud.sqlite"
    with connect_db(db_path) as conn:
        service_policies = conn.execute("SELECT * FROM service_policy").fetchall()
        snoozes = conn.execute("SELECT * FROM snoozes").fetchall()
        tag_exclusion = conn.execute(
            "SELECT * FROM tag_exclusion_rules WHERE id = ?",
            (rule_id,),
        ).fetchone()
        runs = conn.execute(
            "SELECT * FROM update_runs ORDER BY id"
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM update_events ORDER BY id"
        ).fetchall()

    operation_kinds = [
        "upsert_service_policy",
        "delete_service_policy",
        "create_snooze",
        "delete_snooze",
        "upsert_tag_exclusion",
        "set_tag_exclusion_status",
    ]
    run_metadata = [json.loads(row["metadata_json"]) for row in runs]
    event_metadata = [json.loads(row["metadata_json"]) for row in events]
    assert service_policies == []
    assert snoozes == []
    assert tag_exclusion["status"] == "disabled"
    assert [row["mode"] for row in runs] == ["web-state"] * 6
    assert [item["operation"] for item in run_metadata] == operation_kinds
    assert [item["operation"] for item in event_metadata] == operation_kinds
    assert event_metadata[0]["before"] is None
    assert event_metadata[1]["before"]["service_key"] == "stack/app"
    assert event_metadata[-1]["after"]["status"] == "disabled"


def test_service_policy_upsert_preserves_omitted_existing_fields(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)

    created = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "stop",
            "auto_update": False,
            "snooze_default_seconds": 600,
        },
        headers=headers,
    )
    mode_only_update = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "live",
        },
        headers=headers,
    )
    auto_only_update = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "auto_update": True,
        },
        headers=headers,
    )
    explicit_clear = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "snooze_default_seconds": None,
        },
        headers=headers,
    )

    assert created.status_code == 200
    assert mode_only_update.status_code == 200
    mode_resource = mode_only_update.json()["resource"]
    assert mode_resource["update_mode"] == "live"
    assert mode_resource["auto_update"] is False
    assert mode_resource["snooze_default_seconds"] == 600
    assert auto_only_update.status_code == 200
    auto_resource = auto_only_update.json()["resource"]
    assert auto_resource["update_mode"] == "live"
    assert auto_resource["auto_update"] is True
    assert auto_resource["snooze_default_seconds"] == 600
    assert explicit_clear.status_code == 200
    clear_resource = explicit_clear.json()["resource"]
    assert clear_resource["update_mode"] == "live"
    assert clear_resource["auto_update"] is True
    assert clear_resource["snooze_default_seconds"] is None


def test_state_operation_rolls_back_when_audit_insert_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)

    def fail_audit(*_args: object, **_kwargs: object) -> int:
        raise sqlite3.OperationalError("audit failed")

    monkeypatch.setattr(web_module, "_insert_state_audit", fail_audit)

    response = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "stop",
        },
        headers=headers,
    )

    with connect_db(tmp_path / "state" / "wud.sqlite") as conn:
        rows = conn.execute("SELECT * FROM service_policy").fetchall()
        runs = conn.execute("SELECT * FROM update_runs").fetchall()

    assert response.status_code == 500
    assert response.json()["detail"] == "could not update database: audit failed"
    assert rows == []
    assert runs == []


def test_state_operations_validate_inputs(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)
    past = "2000-01-01T00:00:00+00:00"
    invalid_payloads = [
        {
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "restart",
        },
        {
            "kind": "create_snooze",
            "service_key": "stack/app",
            "snoozed_until": past,
        },
        {
            "kind": "upsert_tag_exclusion",
            "scope": "global",
            "image_repo": "repo/app",
            "tag": "2.0",
        },
        {
            "kind": "upsert_tag_exclusion",
            "scope": "service",
            "image_repo": "repo/app",
            "tag": "2.0",
        },
        {
            "kind": "upsert_tag_exclusion",
            "scope": "image_repo",
            "image_repo": "repo/app",
            "tag": "bad:value",
        },
    ]

    responses = [
        client.post("/api/v1/state/operations", json=payload, headers=headers)
        for payload in invalid_payloads
    ]

    assert [response.status_code for response in responses] == [422] * 5


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

    monkeypatch.setattr(web_module.UpdateFromWudRunner, "run", lambda _runner: 0)
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


def test_job_stream_returns_404_for_missing_job(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get("/api/v1/jobs/missing/stream")

    assert response.status_code == 404
    assert response.json()["detail"] == "apply job not found"


def test_job_stream_emits_initial_and_terminal_status(tmp_path: Path) -> None:
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
    hook.write_text("#!/usr/bin/env bash\nsleep 0.1\n", encoding="utf-8")
    hook.chmod(0o755)
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

    with client.stream(
        "GET",
        f"/api/v1/jobs/{apply_response.json()['job_id']}/stream",
    ) as response:
        content = response.read().decode("utf-8")

    events = _sse_job_events(content)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert len(events) >= 2
    assert events[0]["job_id"] == apply_response.json()["job_id"]
    assert events[0]["status"] in {"queued", "running"}
    assert events[-1]["status"] == "success"
    assert events[-1]["selected_line_numbers"] == [1]


def test_job_status_get_and_stream_do_not_mutate(tmp_path: Path) -> None:
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
    (fake_root / "calls.log").write_text("", encoding="utf-8")

    status_response = client.get(f"/api/v1/jobs/{job['job_id']}")
    stream_response = client.get(f"/api/v1/jobs/{job['job_id']}/stream")

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "success"
    assert stream_response.status_code == 200
    assert _sse_job_events(stream_response.text)[-1]["status"] == "success"
    assert _fake_docker_calls(fake_root) == ""


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

    monkeypatch.setattr(web_module.UpdateFromWudRunner, "run", fake_run)
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

    monkeypatch.setattr(web_module.UpdateFromWudRunner, "run", fake_run)
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


def test_runs_list_returns_empty_without_creating_missing_database(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    db_path = root / "wud.sqlite"
    client = _client(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true"},
        create_root=False,
    )

    response = client.get("/api/v1/runs")

    assert response.status_code == 200
    assert response.json() == []
    assert not root.exists()
    assert not db_path.exists()


def test_run_detail_returns_not_found_without_creating_missing_database(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    db_path = root / "wud.sqlite"
    client = _client(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true"},
        create_root=False,
    )

    response = client.get("/api/v1/runs/1")

    assert response.status_code == 404
    assert response.json()["detail"] == "run not found"
    assert not root.exists()
    assert not db_path.exists()


def test_runs_endpoints_read_existing_sqlite_state(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    db_path = tmp_path / "state" / "wud.sqlite"
    with connect_db(db_path) as conn:
        init_db(conn)
        run_id = insert_update_run(
            conn,
            started_at="2026-05-27T12:00:00+00:00",
            status="success",
            dry_run=True,
            mode="stop",
            wud_file="/out/images.todo",
            log_file="/logs/run.log",
            metadata_json='{"source":"test"}',
        )
        insert_pending_update(
            conn,
            run_id=run_id,
            line_no=1,
            raw="nginx:1.25",
            image="nginx:1.25",
            status="success",
        )
        insert_update_event(
            conn,
            run_id=run_id,
            service_name="web",
            image="nginx:1.25",
            status="success",
        )

    runs_response = client.get("/api/v1/runs")
    detail_response = client.get(f"/api/v1/runs/{run_id}")

    assert runs_response.status_code == 200
    assert runs_response.json()[0]["id"] == run_id
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["metadata"] == {"source": "test"}
    assert detail["pending_updates"][0]["image"] == "nginx:1.25"
    assert detail["events"][0]["service_name"] == "web"


def test_run_log_endpoint_tails_configured_log_file(tmp_path: Path) -> None:
    log_dir = tmp_path / "state" / "logs"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "run.log"
    log_file.write_text("0123456789", encoding="utf-8")
    run_id = _insert_run(tmp_path, log_file=str(log_file))
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get(f"/api/v1/runs/{run_id}/log?tail_bytes=4")

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["content"] == "6789"
    assert body["truncated"] is True
    assert body["max_bytes"] == 4


def test_run_log_endpoint_caps_tail_size(tmp_path: Path) -> None:
    log_dir = tmp_path / "state" / "logs"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "run.log"
    log_file.write_text("log", encoding="utf-8")
    run_id = _insert_run(tmp_path, log_file=str(log_file))
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get(f"/api/v1/runs/{run_id}/log?tail_bytes=9999999")

    assert response.status_code == 200
    assert response.json()["max_bytes"] == 1_048_576


def test_run_log_endpoint_reports_missing_log_file(tmp_path: Path) -> None:
    log_file = tmp_path / "state" / "logs" / "missing.log"
    run_id = _insert_run(tmp_path, log_file=str(log_file))
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get(f"/api/v1/runs/{run_id}/log")

    assert response.status_code == 200
    assert response.json()["exists"] is False
    assert response.json()["content"] == ""


def test_run_log_endpoint_rejects_logs_outside_configured_dir(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.log"
    outside.write_text("secret", encoding="utf-8")
    run_id = _insert_run(tmp_path, log_file=str(outside))
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get(f"/api/v1/runs/{run_id}/log")

    assert response.status_code == 403
    assert response.json()["detail"] == "log file is outside WUD_LOG_DIR"


def test_run_log_endpoint_returns_not_found_for_unknown_run(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get("/api/v1/runs/404/log")

    assert response.status_code == 404
    assert response.json()["detail"] == "run not found"


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


def test_csrf_origin_scaffold_rejects_unsafe_api_requests(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.post("/api/v1/runs")

    assert response.status_code == 403
    assert response.json()["detail"] == "origin header is required"


def test_host_allowlist_rejects_unknown_hosts(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/v1/setup/status", headers={"Host": "evil.test"})

    assert response.status_code == 400
    assert response.json()["detail"] == "host is not allowed"


def test_web_startup_rejects_bind_host_missing_from_allowed_hosts(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    for key, value in _web_env(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true"},
    ).items():
        monkeypatch.setenv(key, value)

    status = web_module.run_web_from_namespace(
        SimpleNamespace(
            base=None,
            file=None,
            log_dir=None,
            db_path=None,
            host="192.0.2.10",
            port=None,
            static_dir=None,
        )
    )
    stderr = capsys.readouterr().err

    assert status == 1
    assert "WUD_WEB_ALLOWED_HOSTS must include 192.0.2.10" in stderr


def test_forwarded_headers_require_trusted_proxy(tmp_path: Path) -> None:
    env = {
        "WUD_WEB_ALLOWED_HOSTS": "internal.test,wud.example.test",
        "WUD_WEB_TRUSTED_PROXIES": "10.0.0.1/32",
        "WUD_WEB_SECURE_COOKIES": "false",
    }
    app = create_app(environ=_web_env(tmp_path, env))
    headers = {
        "Host": "internal.test",
        "Origin": "https://wud.example.test",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "wud.example.test",
    }
    untrusted = TestClient(
        app,
        base_url="http://internal.test",
        client=("192.0.2.1", 50000),
    )
    trusted = TestClient(
        app,
        base_url="http://internal.test",
        client=("10.0.0.1", 50000),
    )
    csrf_response = untrusted.get("/api/v1/auth/csrf", headers=headers)
    untrusted_headers = {
        **headers,
        "x-wud-csrf-token": csrf_response.json()["csrf_token"],
    }

    untrusted_response = untrusted.post(
        "/api/v1/setup/claim",
        json={
            "claim": app.state.web_setup_claim,
            "username": "admin",
            "password": "correct horse battery staple",
        },
        headers=untrusted_headers,
    )
    csrf_response = trusted.get("/api/v1/auth/csrf", headers=headers)
    trusted_headers = {
        **headers,
        "x-wud-csrf-token": csrf_response.json()["csrf_token"],
    }
    trusted_response = trusted.post(
        "/api/v1/setup/claim",
        json={
            "claim": app.state.web_setup_claim,
            "username": "admin",
            "password": "correct horse battery staple",
        },
        headers=trusted_headers,
    )

    assert untrusted_response.status_code == 403
    assert untrusted_response.json()["detail"] == "origin is not allowed"
    assert trusted_response.status_code == 200


def test_secure_cookie_auto_follows_effective_origin(tmp_path: Path) -> None:
    http_client = _client(tmp_path)
    https_client = _client(
        tmp_path,
        {
            "WUD_WEB_PUBLIC_ORIGIN": "https://wud.example.test",
            "WUD_WEB_ALLOWED_HOSTS": "wud.example.test",
        },
    )

    http_response = http_client.get("/api/v1/auth/csrf")
    https_response = https_client.get(
        "/api/v1/auth/csrf",
        headers={"Host": "wud.example.test"},
    )

    assert "Secure" not in http_response.headers["set-cookie"]
    assert "Secure" in https_response.headers["set-cookie"]

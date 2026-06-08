from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient

from wud_updater import web as web_module
from wud_updater.db import (
    open_db,
    init_db,
)
from wud_updater.web import create_app


from tests.web_test_helpers import (
    _web_env,
    _client,
    _csrf_headers,
    _setup_admin,
    _contains_key,
    _assert_generic_auth_failed,
)


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

    with open_db(db_path) as conn:
        users = conn.execute("SELECT username FROM web_users").fetchall()

    assert sorted(result[0] for result in results) == ["error", "ok"]
    assert ("error", 409) in results
    assert [row["username"] for row in users] == ["admin-a"]
    assert hasher.calls == 1


def test_setup_claim_rejects_expired_secret(tmp_path: Path) -> None:
    client = _client(tmp_path)
    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        with conn:
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


def test_login_throttle_locks_after_repeated_failures_and_expires(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = 1_000.0
    monkeypatch.setattr(web_module.time, "monotonic", lambda: now)
    app = create_app(environ=_web_env(tmp_path))
    setup_client = TestClient(app)
    _setup_admin(setup_client)
    client = TestClient(app)
    headers = _csrf_headers(client)

    for _index in range(web_module.LOGIN_THROTTLE_MAX_FAILURES):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong"},
            headers=headers,
        )
        _assert_generic_auth_failed(response)

    locked_response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=headers,
    )
    now += web_module.LOGIN_THROTTLE_COOLDOWN_SECONDS + 0.1
    unlocked_response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=headers,
    )

    _assert_generic_auth_failed(locked_response)
    assert client.cookies.get("wud_session") is not None
    assert unlocked_response.status_code == 200
    assert unlocked_response.json()["authenticated"] is True


def test_login_throttle_entry_cap_does_not_evict_locked_user(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = 1_000.0
    monkeypatch.setattr(web_module.time, "monotonic", lambda: now)
    app = create_app(environ=_web_env(tmp_path))
    setup_client = TestClient(app)
    _setup_admin(setup_client)
    client = TestClient(app, client=("203.0.113.10", 50000))
    headers = _csrf_headers(client)

    for _index in range(web_module.LOGIN_THROTTLE_MAX_FAILURES):
        _assert_generic_auth_failed(
            client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "wrong"},
                headers=headers,
            )
        )

    for index in range(web_module.LOGIN_THROTTLE_MAX_ENTRIES + 1):
        _assert_generic_auth_failed(
            client.post(
                "/api/v1/auth/login",
                json={"username": f"filler-{index}", "password": "wrong"},
                headers=headers,
            )
        )

    locked_after_fill = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=headers,
    )
    now += web_module.LOGIN_THROTTLE_COOLDOWN_SECONDS + 0.1
    unlocked_response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=headers,
    )

    _assert_generic_auth_failed(locked_after_fill)
    assert unlocked_response.status_code == 200
    assert unlocked_response.json()["authenticated"] is True


def test_login_throttle_entry_cap_evicts_unlocked_entries_without_global_lockout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = 1_000.0
    monkeypatch.setattr(web_module.time, "monotonic", lambda: now)
    app = create_app(environ=_web_env(tmp_path))
    setup_client = TestClient(app)
    _setup_admin(setup_client)
    request = SimpleNamespace(
        app=app,
        client=SimpleNamespace(host="203.0.113.10"),
        headers={},
    )
    settings = app.state.web_settings

    for index in range(web_module.LOGIN_THROTTLE_MAX_ENTRIES):
        web_module._record_login_failure(request, settings, f"filler-{index}")
    web_module._record_login_failure(request, settings, "overflow")

    throttle = app.state.web_login_throttle
    assert len(throttle) == web_module.LOGIN_THROTTLE_MAX_ENTRIES
    assert ("filler-0", "203.0.113.10") not in throttle
    assert ("overflow", "203.0.113.10") in throttle

    client = TestClient(app, client=("203.0.113.10", 50000))
    headers = _csrf_headers(client)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["authenticated"] is True


def test_login_throttle_entry_cap_records_client_overflow_when_all_entries_locked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = 1_000.0
    monkeypatch.setattr(web_module.time, "monotonic", lambda: now)
    monkeypatch.setattr(web_module, "LOGIN_THROTTLE_MAX_ENTRIES", 2)
    monkeypatch.setattr(web_module, "LOGIN_THROTTLE_MAX_FAILURES", 1)
    app = create_app(environ=_web_env(tmp_path))
    setup_client = TestClient(app)
    _setup_admin(setup_client)
    client = TestClient(app, client=("203.0.113.99", 50000))
    headers = _csrf_headers(client)

    for index in range(web_module.LOGIN_THROTTLE_MAX_ENTRIES):
        _assert_generic_auth_failed(
            client.post(
                "/api/v1/auth/login",
                json={"username": f"filler-{index}", "password": "wrong"},
                headers=headers,
            )
        )
    _assert_generic_auth_failed(
        client.post(
            "/api/v1/auth/login",
            json={"username": "overflow", "password": "wrong"},
            headers=headers,
        )
    )
    locked_response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=headers,
    )

    throttle = app.state.web_login_throttle
    client_throttle = app.state.web_login_client_throttle
    assert len(throttle) == web_module.LOGIN_THROTTLE_MAX_ENTRIES
    assert ("overflow", "203.0.113.99") not in throttle
    assert client_throttle["203.0.113.99"].locked_until > now
    _assert_generic_auth_failed(locked_response)

    now += web_module.LOGIN_THROTTLE_COOLDOWN_SECONDS + 0.1
    unlocked_response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=headers,
    )

    assert unlocked_response.status_code == 200
    assert unlocked_response.json()["authenticated"] is True


def test_login_throttle_client_overflow_does_not_lock_out_other_clients(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(web_module.time, "monotonic", lambda: 1_000.0)
    monkeypatch.setattr(web_module, "LOGIN_THROTTLE_MAX_ENTRIES", 2)
    monkeypatch.setattr(web_module, "LOGIN_THROTTLE_MAX_FAILURES", 1)
    app = create_app(environ=_web_env(tmp_path))
    setup_client = TestClient(app)
    _setup_admin(setup_client)
    abusive_client = TestClient(app, client=("203.0.113.99", 50000))
    other_client = TestClient(app, client=("203.0.113.100", 50000))
    abusive_headers = _csrf_headers(abusive_client)
    other_headers = _csrf_headers(other_client)

    for username in ("filler-0", "filler-1", "overflow"):
        _assert_generic_auth_failed(
            abusive_client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": "wrong"},
                headers=abusive_headers,
            )
        )
    abusive_login = abusive_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=abusive_headers,
    )
    other_login = other_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=other_headers,
    )

    _assert_generic_auth_failed(abusive_login)
    assert other_login.status_code == 200
    assert other_login.json()["authenticated"] is True


def test_login_throttle_client_overflow_cap_evicts_oldest_client(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(web_module.time, "monotonic", lambda: 1_000.0)
    monkeypatch.setattr(web_module, "LOGIN_THROTTLE_MAX_ENTRIES", 1)
    monkeypatch.setattr(web_module, "LOGIN_THROTTLE_MAX_FAILURES", 1)
    monkeypatch.setattr(web_module, "LOGIN_THROTTLE_MAX_CLIENT_ENTRIES", 2)
    app = create_app(environ=_web_env(tmp_path))
    setup_client = TestClient(app)
    _setup_admin(setup_client)
    settings = app.state.web_settings
    seed_request = SimpleNamespace(
        app=app,
        client=SimpleNamespace(host="203.0.113.9"),
        headers={},
    )
    web_module._record_login_failure(seed_request, settings, "seed")

    for index in range(3):
        request = SimpleNamespace(
            app=app,
            client=SimpleNamespace(host=f"203.0.113.{index + 10}"),
            headers={},
        )
        web_module._record_login_failure(request, settings, f"overflow-{index}")

    client_throttle = app.state.web_login_client_throttle
    assert len(client_throttle) == web_module.LOGIN_THROTTLE_MAX_CLIENT_ENTRIES
    assert "203.0.113.10" not in client_throttle
    assert "203.0.113.11" in client_throttle
    assert "203.0.113.12" in client_throttle


def test_login_throttle_is_scoped_by_username_and_client_address(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(web_module.time, "monotonic", lambda: 1_000.0)
    app = create_app(environ=_web_env(tmp_path))
    setup_client = TestClient(app)
    _setup_admin(setup_client)
    client_a = TestClient(app, client=("203.0.113.10", 50000))
    client_b = TestClient(app, client=("203.0.113.11", 50000))
    headers_a = _csrf_headers(client_a)
    headers_b = _csrf_headers(client_b)

    for _index in range(web_module.LOGIN_THROTTLE_MAX_FAILURES):
        _assert_generic_auth_failed(
            client_a.post(
                "/api/v1/auth/login",
                json={"username": "missing", "password": "wrong"},
                headers=headers_a,
            )
        )
    same_address_different_user = client_a.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=headers_a,
    )

    for _index in range(web_module.LOGIN_THROTTLE_MAX_FAILURES):
        _assert_generic_auth_failed(
            client_a.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "wrong"},
                headers=headers_a,
            )
        )
    different_address_same_user = client_b.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=headers_b,
    )

    assert same_address_different_user.status_code == 200
    assert different_address_same_user.status_code == 200


def test_login_throttle_uses_trusted_forwarded_client_address(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(web_module.time, "monotonic", lambda: 1_000.0)
    app = create_app(
        environ=_web_env(
            tmp_path,
            {"WUD_WEB_TRUSTED_PROXIES": "10.0.0.1/32"},
        )
    )
    setup_client = TestClient(app, client=("10.0.0.1", 50000))
    _setup_admin(setup_client)
    proxy_client = TestClient(app, client=("10.0.0.1", 50000))
    headers = _csrf_headers(proxy_client)
    forwarded_a = {**headers, "X-Forwarded-For": "198.51.100.10"}
    forwarded_b = {**headers, "X-Forwarded-For": "198.51.100.11"}

    for _index in range(web_module.LOGIN_THROTTLE_MAX_FAILURES):
        _assert_generic_auth_failed(
            proxy_client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "wrong"},
                headers=forwarded_a,
            )
        )
    different_forwarded_address = proxy_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=forwarded_b,
    )

    assert different_forwarded_address.status_code == 200


def test_login_throttle_ignores_untrusted_forwarded_client_address(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(web_module.time, "monotonic", lambda: 1_000.0)
    app = create_app(environ=_web_env(tmp_path))
    setup_client = TestClient(app, client=("203.0.113.10", 50000))
    _setup_admin(setup_client)
    client = TestClient(app, client=("203.0.113.10", 50000))
    headers = _csrf_headers(client)

    for index in range(web_module.LOGIN_THROTTLE_MAX_FAILURES):
        _assert_generic_auth_failed(
            client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "wrong"},
                headers={
                    **headers,
                    "X-Forwarded-For": f"198.51.100.{index + 10}",
                },
            )
        )
    locked_response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers={**headers, "X-Forwarded-For": "198.51.100.99"},
    )

    _assert_generic_auth_failed(locked_response)


def test_successful_login_clears_failed_login_throttle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(web_module.time, "monotonic", lambda: 1_000.0)
    app = create_app(environ=_web_env(tmp_path))
    setup_client = TestClient(app)
    _setup_admin(setup_client)
    client = TestClient(app)
    headers = _csrf_headers(client)

    for _index in range(web_module.LOGIN_THROTTLE_MAX_FAILURES - 1):
        _assert_generic_auth_failed(
            client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "wrong"},
                headers=headers,
            )
        )
    first_success = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=headers,
    )
    one_failure_after_success = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
        headers=headers,
    )
    second_success = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=headers,
    )

    assert first_success.status_code == 200
    _assert_generic_auth_failed(one_failure_after_success)
    assert second_success.status_code == 200


def test_login_failures_use_same_generic_response(tmp_path: Path) -> None:
    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    client = _client(tmp_path)
    headers = _csrf_headers(client)

    unknown_user = client.post(
        "/api/v1/auth/login",
        json={"username": "missing", "password": "wrong"},
        headers=headers,
    )
    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
        headers=headers,
    )
    for _index in range(web_module.LOGIN_THROTTLE_MAX_FAILURES - 1):
        _assert_generic_auth_failed(
            client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "wrong"},
                headers=headers,
            )
        )
    throttled = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=headers,
    )

    _assert_generic_auth_failed(unknown_user)
    _assert_generic_auth_failed(wrong_password)
    _assert_generic_auth_failed(throttled)


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


def test_auth_error_responses_do_not_leak_submitted_secrets_or_tokens(
    tmp_path: Path,
    caplog,
) -> None:
    web_token = "web-token-secret-value"
    setup_claim = "submitted-setup-claim-secret"
    setup_password = "submitted-setup-password"
    login_password = "submitted-login-password"
    reset_claim = "submitted-reset-claim-secret"
    reset_password = "submitted-reset-password"
    client = _client(tmp_path, {"WUD_WEB_TOKEN": web_token})

    with caplog.at_level(logging.DEBUG):
        invalid_setup = client.post(
            "/api/v1/setup/claim",
            json={
                "claim": setup_claim,
                "username": "admin",
                "password": setup_password,
            },
            headers=_csrf_headers(client),
        )
        _setup_admin(client)
        csrf_headers = _csrf_headers(client)
        csrf_token = csrf_headers["x-wud-csrf-token"]
        invalid_token_login = client.post(
            "/api/v1/auth/login",
            json={"token": web_token},
            headers=csrf_headers,
        )
        bad_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": login_password},
            headers=csrf_headers,
        )
        good_login = client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": "correct horse battery staple",
            },
            headers=csrf_headers,
        )
        session_cookie = client.cookies.get("wud_session")
        invalid_reset = client.post(
            "/api/v1/auth/reset-admin/claim",
            json={
                "claim": reset_claim,
                "username": "admin",
                "password": reset_password,
            },
            headers=_csrf_headers(client),
        )

    assert invalid_setup.status_code == 403
    assert invalid_token_login.status_code == 422
    _assert_generic_auth_failed(bad_login)
    assert good_login.status_code == 200
    assert session_cookie
    assert invalid_reset.status_code == 403

    response_text = "\n".join(
        response.text
        for response in (
            invalid_setup,
            invalid_token_login,
            bad_login,
            good_login,
            invalid_reset,
        )
    )
    for secret in (
        setup_claim,
        setup_password,
        web_token,
        login_password,
        session_cookie,
        csrf_token,
        reset_claim,
        reset_password,
    ):
        assert secret not in response_text
        assert secret not in caplog.text


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


def test_authenticated_get_does_not_touch_session_last_seen(tmp_path: Path) -> None:
    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    client = _client(tmp_path)
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=_csrf_headers(client),
    )
    assert login_response.status_code == 200

    db_path = tmp_path / "state" / "wud.sqlite"
    sentinel = "2000-01-01T00:00:00+00:00"
    with open_db(db_path) as conn:
        init_db(conn)
        with conn:
            conn.execute("UPDATE web_sessions SET last_seen_at = ?", (sentinel,))

    status_response = client.get("/api/v1/status")

    with open_db(db_path) as conn:
        last_seen = conn.execute(
            "SELECT last_seen_at FROM web_sessions LIMIT 1"
        ).fetchone()["last_seen_at"]

    assert status_response.status_code == 200
    assert last_seen == sentinel


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


def test_admin_reset_claim_revokes_sessions_invalidates_password_and_audits(
    tmp_path: Path,
) -> None:
    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    logged_in_client = _client(tmp_path)
    login_response = logged_in_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=_csrf_headers(logged_in_client),
    )
    assert login_response.status_code == 200

    recovery = web_module.issue_admin_recovery_claim(
        setup_client.app.state.web_settings,
        "admin",
    )
    status_response = logged_in_client.get("/api/v1/status")
    old_login_client = _client(tmp_path)
    old_login_response = old_login_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=_csrf_headers(old_login_client),
    )

    assert recovery.claim
    assert recovery.username == "admin"
    assert recovery.revoked_sessions >= 2
    assert status_response.status_code == 401
    assert old_login_response.status_code == 401
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        init_db(conn)
        reset_hash = web_module._web_setting(
            conn,
            web_module.RESET_ADMIN_CLAIM_HASH_KEY,
        )
        sessions = conn.execute("SELECT revoked_at FROM web_sessions").fetchall()
        audit_rows = conn.execute(
            """
            SELECT metadata_json
            FROM update_runs
            WHERE mode = 'web-auth'
            ORDER BY id
            """
        ).fetchall()

    assert reset_hash
    assert reset_hash != recovery.claim
    assert all(row["revoked_at"] for row in sessions)
    audit = [json.loads(row["metadata_json"]) for row in audit_rows]
    assert audit[-1]["operation"] == "admin_reset_claim_issued"
    assert audit[-1]["source"] == "cli"
    assert audit[-1]["target"]["username"] == "admin"
    assert recovery.claim not in json.dumps(audit)


def test_admin_reset_claim_redeems_once_and_allows_new_password(
    tmp_path: Path,
) -> None:
    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    recovery = web_module.issue_admin_recovery_claim(
        setup_client.app.state.web_settings,
        "admin",
    )
    client = _client(tmp_path)

    response = client.post(
        "/api/v1/auth/reset-admin/claim",
        json={
            "claim": recovery.claim,
            "username": "admin",
            "password": "new correct horse battery",
        },
        headers=_csrf_headers(client),
    )
    replay_response = client.post(
        "/api/v1/auth/reset-admin/claim",
        json={
            "claim": recovery.claim,
            "username": "admin",
            "password": "new correct horse battery",
        },
        headers=_csrf_headers(client),
    )
    old_login_client = _client(tmp_path)
    old_login_response = old_login_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=_csrf_headers(old_login_client),
    )
    new_login_client = _client(tmp_path)
    new_login_response = new_login_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "new correct horse battery"},
        headers=_csrf_headers(new_login_client),
    )

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert "wud_session=" in response.headers["set-cookie"]
    assert replay_response.status_code == 403
    assert replay_response.json()["detail"] == "admin recovery claim is invalid"
    assert old_login_response.status_code == 401
    assert new_login_response.status_code == 200
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        init_db(conn)
        assert (
            web_module._web_setting(
                conn,
                web_module.RESET_ADMIN_CLAIM_HASH_KEY,
            )
            == ""
        )
        audit_rows = conn.execute(
            """
            SELECT metadata_json
            FROM update_runs
            WHERE mode = 'web-auth'
            ORDER BY id
            """
        ).fetchall()
    audit = [json.loads(row["metadata_json"]) for row in audit_rows]
    assert [row["operation"] for row in audit] == [
        "admin_reset_claim_issued",
        "admin_reset_password_changed",
    ]


def test_admin_reset_rejects_invalid_claim_without_burning_valid_claim(
    tmp_path: Path,
) -> None:
    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    recovery = web_module.issue_admin_recovery_claim(
        setup_client.app.state.web_settings,
        "admin",
    )
    client = _client(tmp_path)

    invalid = client.post(
        "/api/v1/auth/reset-admin/claim",
        json={
            "claim": "not-the-claim",
            "username": "admin",
            "password": "new correct horse battery",
        },
        headers=_csrf_headers(client),
    )
    valid = client.post(
        "/api/v1/auth/reset-admin/claim",
        json={
            "claim": recovery.claim,
            "username": "admin",
            "password": "new correct horse battery",
        },
        headers=_csrf_headers(client),
    )

    assert invalid.status_code == 403
    assert invalid.json()["detail"] == "admin recovery claim is invalid"
    assert valid.status_code == 200


def test_admin_reset_rejects_expired_claim_without_creating_session(
    tmp_path: Path,
) -> None:
    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    recovery = web_module.issue_admin_recovery_claim(
        setup_client.app.state.web_settings,
        "admin",
    )
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        init_db(conn)
        with conn:
            conn.execute(
                """
                UPDATE web_settings
                SET value = '2000-01-01T00:00:00+00:00'
                WHERE key = ?
                """,
                (web_module.RESET_ADMIN_CLAIM_EXPIRES_KEY,),
            )
    client = _client(tmp_path)

    response = client.post(
        "/api/v1/auth/reset-admin/claim",
        json={
            "claim": recovery.claim,
            "username": "admin",
            "password": "new correct horse battery",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "admin recovery claim expired"
    assert client.cookies.get("wud_session") is None


def test_admin_reset_claim_requires_csrf_origin_headers(tmp_path: Path) -> None:
    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    recovery = web_module.issue_admin_recovery_claim(
        setup_client.app.state.web_settings,
        "admin",
    )
    client = _client(tmp_path)

    response = client.post(
        "/api/v1/auth/reset-admin/claim",
        json={
            "claim": recovery.claim,
            "username": "admin",
            "password": "new correct horse battery",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "origin header is required"


def test_admin_reset_command_errors_for_missing_setup_and_unknown_user(
    tmp_path: Path,
) -> None:
    missing_settings = web_module.load_web_settings(_web_env(tmp_path))
    try:
        web_module.issue_admin_recovery_claim(missing_settings, "admin")
        raise AssertionError("missing database should fail")
    except web_module.WebAdminResetError as exc:
        assert "database file does not exist" in str(exc)
    assert not (tmp_path / "state" / "wud.sqlite").exists()

    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        init_db(conn)
    try:
        web_module.issue_admin_recovery_claim(missing_settings, "admin")
        raise AssertionError("incomplete setup should fail")
    except web_module.WebAdminResetError as exc:
        assert "setup is not complete" in str(exc)

    setup_client = _client(tmp_path)
    _setup_admin(setup_client)
    try:
        web_module.issue_admin_recovery_claim(
            setup_client.app.state.web_settings,
            "other",
        )
        raise AssertionError("unknown user should fail")
    except web_module.WebAdminResetError as exc:
        assert "active admin user not found" in str(exc)


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

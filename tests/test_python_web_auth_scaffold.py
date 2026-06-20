from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from wudup import web_auth as web_auth_module
from wudup.web import create_app


from tests.web_test_helpers import (
    _web_env,
    _client,
    _csrf_headers,
    _setup_admin,
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


def test_request_actor_type_falls_back_to_unknown_without_auth(tmp_path: Path) -> None:
    settings = _client(tmp_path, {"WUD_WEB_TOKEN": "secret"}).app.state.web_settings
    request = SimpleNamespace(headers={}, cookies={})

    assert web_auth_module._request_actor_type(settings, request) == "unknown"


def test_csrf_endpoint_sets_double_submit_cookie(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/v1/auth/csrf")

    assert response.status_code == 200
    assert response.json()["csrf_token"]
    assert client.cookies.get("wud_csrf_token") == response.json()["csrf_token"]


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


def test_trusted_forwarded_headers_use_last_proxy_hop(tmp_path: Path) -> None:
    app = create_app(
        environ=_web_env(
            tmp_path,
            {
                "WUD_WEB_ALLOWED_HOSTS": "internal.test,wud.example.test",
                "WUD_WEB_TRUSTED_PROXIES": "10.0.0.1/32",
            },
        )
    )
    settings = app.state.web_settings
    forwarded_request = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.1"),
        headers={
            "forwarded": (
                "for=198.51.100.10;proto=http;host=evil.test, "
                "for=203.0.113.20;proto=https;host=wud.example.test"
            ),
        },
    )
    x_forwarded_request = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.1"),
        headers={
            "x-forwarded-for": "198.51.100.10, 203.0.113.20",
            "x-forwarded-proto": "http, https",
            "x-forwarded-host": "evil.test, wud.example.test",
        },
    )

    assert (
        web_auth_module._trusted_forwarded_origin(forwarded_request, settings)
        == "https://wud.example.test"
    )
    assert (
        web_auth_module._request_client_address(forwarded_request, settings)
        == "203.0.113.20"
    )
    assert (
        web_auth_module._trusted_forwarded_origin(x_forwarded_request, settings)
        == "https://wud.example.test"
    )
    assert (
        web_auth_module._request_client_address(x_forwarded_request, settings)
        == "203.0.113.20"
    )


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

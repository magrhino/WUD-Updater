from __future__ import annotations
from pathlib import Path
from wudup import web_self_update as self_update_module
from wudup.web_models import WebApplyJob
from tests.web_test_helpers import (
    _client,
    _csrf_headers,
    _fake_docker_env,
    _make_fake_stack,
    _fake_docker_calls,
)


def test_self_update_plan_endpoint_returns_pinned_tag_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    monkeypatch.setattr(
        self_update_module,
        "current_container_image",
        lambda _env: "ghcr.io/magrhino/wudup:v0.24.2",
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
            "WUD_WEB_RESTART_CONTAINER": "wudup",
            **fake_env,
        },
    )
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "wud",
        [
            (
                "wudup",
                "ghcr.io/magrhino/wudup:v0.24.2",
                "wudup",
            ),
        ],
    )
    compose_before = (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")

    response = client.post(
        "/api/v1/self-update/plan",
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "prepare_tag_update"
    assert body["external_recreate_required"] is True
    assert body["target_image"] == "ghcr.io/magrhino/wudup:v0.25.0"
    assert body["plan"]["status"] == "ready"
    assert body["plan"]["can_apply"] is True
    stack = body["plan"]["stacks"][0]
    assert stack["services"] == ["wudup"]
    assert stack["tag_updates"] == [
        {
            "old_image": "ghcr.io/magrhino/wudup:v0.24.2",
            "desired_tag": "v0.25.0",
            "new_image": "ghcr.io/magrhino/wudup:v0.25.0",
            "services": ["wudup"],
        }
    ]
    assert (compose_dir / "docker-compose.yml").read_text(encoding="utf-8") == compose_before
    calls = _fake_docker_calls(fake_root)
    assert "manifest inspect ghcr.io/magrhino/wudup:v0.25.0" in calls
    assert " pull " not in calls
    assert " up -d " not in calls
    assert "restart " not in calls


def test_self_update_prepare_endpoint_rejects_stale_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    monkeypatch.setattr(
        self_update_module,
        "current_container_image",
        lambda _env: "ghcr.io/magrhino/wudup:v0.24.2",
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
            "WUD_WEB_RESTART_CONTAINER": "wudup",
            **fake_env,
        },
    )

    response = client.post(
        "/api/v1/self-update/prepare",
        json={
            "confirmation": "prepare_tag_update",
            "plan_id": "missing-plan",
            "current_tag": "v0.24.2",
            "latest_tag": "v0.25.0",
            "target_image": "ghcr.io/magrhino/wudup:v0.25.0",
            "restart_container": "wudup",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "self-update plan is stale"
    assert client.app.state.web_self_update_running is False
    assert _fake_docker_calls(fake_root) == ""


def test_self_update_plan_and_prepare_enforce_auth_csrf_read_only_and_active_job(
    tmp_path: Path,
) -> None:
    prepare_payload = {
        "confirmation": "prepare_tag_update",
        "plan_id": "plan",
        "current_tag": "v0.24.2",
        "latest_tag": "v0.25.0",
        "target_image": "ghcr.io/magrhino/wudup:v0.25.0",
        "restart_container": "wudup",
    }
    unauthenticated = _client(tmp_path, {"WUD_WEB_MUTATIONS_ENABLED": "true"})
    read_only = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_RESTART_CONTAINER": "wudup",
        },
    )
    mutating = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wudup",
        },
    )
    mutating.app.state.web_apply_jobs["job-active"] = WebApplyJob(
        id="job-active",
        status="running",
        selected_line_numbers=(1,),
    )

    unauthenticated_plan = unauthenticated.post(
        "/api/v1/self-update/plan",
        headers=_csrf_headers(unauthenticated),
    )
    missing_csrf_plan = mutating.post("/api/v1/self-update/plan")
    read_only_plan = read_only.post(
        "/api/v1/self-update/plan",
        headers=_csrf_headers(read_only),
    )
    active_job_plan = mutating.post(
        "/api/v1/self-update/plan",
        headers=_csrf_headers(mutating),
    )
    unauthenticated_prepare = unauthenticated.post(
        "/api/v1/self-update/prepare",
        json=prepare_payload,
        headers=_csrf_headers(unauthenticated),
    )
    missing_csrf_prepare = mutating.post(
        "/api/v1/self-update/prepare",
        json=prepare_payload,
    )
    read_only_prepare = read_only.post(
        "/api/v1/self-update/prepare",
        json=prepare_payload,
        headers=_csrf_headers(read_only),
    )
    active_job_prepare = mutating.post(
        "/api/v1/self-update/prepare",
        json=prepare_payload,
        headers=_csrf_headers(mutating),
    )

    assert unauthenticated_plan.status_code == 403
    assert unauthenticated_plan.json()["detail"] == "setup required"
    assert missing_csrf_plan.status_code == 403
    assert missing_csrf_plan.json()["detail"] == "origin header is required"
    assert read_only_plan.status_code == 403
    assert read_only_plan.json()["detail"] == "mutations are disabled"
    assert active_job_plan.status_code == 409
    assert active_job_plan.json()["detail"] == "an apply job is already running"
    assert unauthenticated_prepare.status_code == 403
    assert unauthenticated_prepare.json()["detail"] == "setup required"
    assert missing_csrf_prepare.status_code == 403
    assert missing_csrf_prepare.json()["detail"] == "origin header is required"
    assert read_only_prepare.status_code == 403
    assert read_only_prepare.json()["detail"] == "mutations are disabled"
    assert active_job_prepare.status_code == 409
    assert active_job_prepare.json()["detail"] == "an apply job is already running"

from __future__ import annotations
from pathlib import Path
from wud_updater import web as web_module
from wud_updater import web_jobs
from wud_updater import web_self_update as self_update_module
from wud_updater.config import UpdaterConfig
from wud_updater.web_models import WebSettings
from tests.web_test_helpers import (
    _client,
    _csrf_headers,
    _self_update_payload,
    _fake_docker_env,
    _make_fake_stack,
    _fake_docker_calls,
    _wait_apply_job,
    _sse_event_names,
    _sse_job_events,
    _sse_log_events,
    _sse_progress_events,
)


def _settings_for_lock_timeout(
    tmp_path: Path,
    command_env: dict[str, str] | None,
) -> WebSettings:
    root = tmp_path / "state"
    return WebSettings(
        config=UpdaterConfig(
            docker_base=tmp_path / "docker",
            wud_out_file=root / "images.todo",
            log_dir=root / "logs",
            db_path=root / "wud.sqlite",
            update_mode="stop",
            max_wait=180,
            lock_timeout=30,
            timezone_name="UTC",
            compose_ignore_paths=(),
            digest_pin_updates=False,
            out_uid=None,
            out_gid=None,
        ),
        auth_token="",
        command_env=command_env,
    )


def test_acquire_apply_wud_lock_coerces_env_timeout_to_int(
    tmp_path: Path,
    monkeypatch,
) -> None:
    observed: list[int] = []

    class FakeDirectoryLock:
        def __init__(self, _path: object, *, timeout_seconds: int) -> None:
            self.timeout_seconds = timeout_seconds
            observed.append(timeout_seconds)

        def acquire(self) -> None:
            pass

    monkeypatch.setattr(web_jobs, "DirectoryLock", FakeDirectoryLock)

    cases = [
        ({"WUD_LOCK_TIMEOUT": "5"}, 5),
        ({}, 30),
        ({"WUD_LOCK_TIMEOUT": "slow"}, 30),
        ({"WUD_LOCK_TIMEOUT": "-1"}, 30),
    ]

    for command_env, expected in cases:
        lock = web_jobs._acquire_apply_wud_lock(
            _settings_for_lock_timeout(tmp_path, command_env)
        )
        assert lock.timeout_seconds == expected

    assert observed == [5, 30, 30, 30]
    assert all(isinstance(timeout_seconds, int) for timeout_seconds in observed)


def test_self_update_endpoint_enforces_auth_csrf_read_only_and_active_job(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(self_update_module, "current_tag", lambda: "v0.24.2")
    monkeypatch.setattr(self_update_module, "fetch_latest_release_tag", lambda: "v0.25.0")
    monkeypatch.setattr(
        self_update_module,
        "_fetch_self_update_release_notes",
        lambda *_args, **_kwargs: ([], False, []),
    )
    payload = _self_update_payload()
    unauthenticated = _client(tmp_path, {"WUD_WEB_MUTATIONS_ENABLED": "true"})
    read_only = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
        },
    )
    mutating = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_WEB_RESTART_CONTAINER": "wud-updater",
        },
    )
    mutating.app.state.web_apply_jobs["job-active"] = web_module.WebApplyJob(
        id="job-active",
        status="running",
        selected_line_numbers=(1,),
    )

    unauthenticated_response = unauthenticated.post(
        "/api/v1/self-update",
        json=payload,
        headers=_csrf_headers(unauthenticated),
    )
    missing_csrf = mutating.post("/api/v1/self-update", json=payload)
    read_only_response = read_only.post(
        "/api/v1/self-update",
        json=payload,
        headers=_csrf_headers(read_only),
    )
    active_job = mutating.post(
        "/api/v1/self-update",
        json=payload,
        headers=_csrf_headers(mutating),
    )

    assert unauthenticated_response.status_code == 403
    assert unauthenticated_response.json()["detail"] == "setup required"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "origin header is required"
    assert read_only_response.status_code == 403
    assert read_only_response.json()["detail"] == "mutations are disabled"
    assert active_job.status_code == 409
    assert active_job.json()["detail"] == "an apply job is already running"


def test_job_stream_returns_404_for_missing_job(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get("/api/v1/jobs/missing/stream")

    assert response.status_code == 404
    assert response.json()["detail"] == "apply job not found"


def test_job_status_snapshots_while_locked(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    job_id = "job-active"
    client.app.state.web_apply_jobs[job_id] = web_module.WebApplyJob(
        id=job_id,
        status="running",
        selected_line_numbers=(1,),
    )
    original_response = web_jobs._apply_job_response
    observed: dict[str, bool] = {}

    def assert_locked(job):
        observed["locked"] = client.app.state.web_apply_lock.locked()
        return original_response(job)

    monkeypatch.setattr(web_jobs, "_apply_job_response", assert_locked)

    response = client.get(f"/api/v1/jobs/{job_id}")

    assert response.status_code == 200
    assert observed["locked"] is True


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
    log_events = _sse_log_events(content)
    progress_events = _sse_progress_events(content)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert len(events) >= 2
    assert events[0]["job_id"] == apply_response.json()["job_id"]
    assert events[0]["status"] in {"queued", "running"}
    assert events[-1]["status"] == "success"
    assert events[-1]["selected_line_numbers"] == [1]
    assert events[-1]["progress"]
    assert progress_events
    assert progress_events[0]["job_id"] == apply_response.json()["job_id"]
    assert {event["phase"] for event in progress_events} >= {
        "preflight",
        "pull",
        "recreate",
        "health",
        "cleanup",
        "completion",
    }
    assert progress_events[-1]["phase"] == "completion"
    assert progress_events[-1]["status"] == "success"
    assert log_events
    assert log_events[0]["job_id"] == apply_response.json()["job_id"]
    assert log_events[0]["max_bytes"] == 65_536
    assert "docker-update-from-wud-v2" in str(log_events[0]["content"])
    assert _sse_event_names(content)[-2:] == ["log", "job"]


def test_job_stream_caps_live_log_tail_size(tmp_path: Path) -> None:
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

    with client.stream(
        "GET",
        f"/api/v1/jobs/{apply_response.json()['job_id']}/stream?log_tail_bytes=9999999",
    ) as response:
        content = response.read().decode("utf-8")

    log_events = _sse_log_events(content)
    assert response.status_code == 200
    assert log_events
    assert log_events[0]["max_bytes"] == 1_048_576


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

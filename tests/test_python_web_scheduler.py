from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

from wud_updater import web as web_module
from wud_updater import web_jobs, web_scheduler, web_settings
from wud_updater.db import init_db, open_db, upsert_known_image
from wud_updater.digest_provenance import DigestTagProvenance
from wud_updater.locks import DirectoryLock

from tests.web_test_helpers import (
    _client,
    _csrf_headers,
    _fake_docker_calls,
    _fake_docker_env,
    _make_fake_stack,
    _web_env,
    _wait_apply_job,
)


def _auto_update_tick(client, now: datetime):
    return web_scheduler._auto_update_tick(
        client.app,
        client.app.state.web_settings,
        effective_config_loader=web_settings._effective_config,
        now=now,
    )


def test_auto_update_scheduler_loop_runs_initial_tick_before_wait(
    monkeypatch,
    caplog,
) -> None:
    calls: list[str] = []

    class StopAfterInitialTick:
        timeout: float | None = None

        def wait(self, timeout: float) -> bool:
            self.timeout = timeout
            return True

    def fail_tick(*_args, **_kwargs):
        calls.append("tick")
        raise RuntimeError("tick failed")

    stop_event = StopAfterInitialTick()
    monkeypatch.setattr(web_scheduler, "_auto_update_tick", fail_tick)

    with caplog.at_level(logging.ERROR, logger=web_scheduler.LOGGER.name):
        web_scheduler._auto_update_scheduler_loop(
            SimpleNamespace(),
            SimpleNamespace(),
            stop_event,
            lambda _settings: None,
        )

    assert calls == ["tick"]
    assert stop_event.timeout == web_scheduler.AUTO_UPDATE_POLL_SECONDS
    assert "auto update scheduler tick failed" in caplog.text


def test_auto_update_scheduler_does_not_start_without_mutations(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = _auto_update_tick(client, datetime(2026, 5, 30, 14, 30, tzinfo=timezone.utc))

    assert client.app.state.web_auto_update_thread is None
    assert response is None


def test_auto_update_scheduler_start_initializes_database(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    try:
        with open_db(tmp_path / "state" / "wud.sqlite") as conn:
            row = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'web_settings'
                """
            ).fetchone()
    finally:
        web_scheduler.shutdown_auto_update_scheduler_state(client.app.state)

    assert row is not None


def test_auto_update_scheduler_start_refuses_duplicate_thread(tmp_path: Path) -> None:
    release_existing = Event()
    existing = Thread(target=release_existing.wait, daemon=True)
    existing.start()
    app = SimpleNamespace(
        state=SimpleNamespace(
            web_auto_update_thread=existing,
            web_auto_update_stop=Event(),
        )
    )
    settings = SimpleNamespace(
        mutations_enabled=True,
        config=SimpleNamespace(db_path=tmp_path / "state" / "wud.sqlite"),
    )
    try:
        thread = web_scheduler.start_auto_update_scheduler(
            app,
            settings,
            effective_config_loader=lambda _settings: None,
        )
    finally:
        release_existing.set()
        existing.join(timeout=1.0)

    assert thread is existing
    assert app.state.web_auto_update_thread is existing


def test_auto_update_scheduler_start_replaces_stopped_event(
    tmp_path: Path,
    monkeypatch,
) -> None:
    old_stop = Event()
    old_stop.set()
    app = SimpleNamespace(
        state=SimpleNamespace(
            web_auto_update_thread=None,
            web_auto_update_stop=old_stop,
        )
    )
    settings = SimpleNamespace(
        mutations_enabled=True,
        config=SimpleNamespace(db_path=tmp_path / "state" / "wud.sqlite"),
    )
    observed_stop_states: list[bool] = []

    def fake_loop(_app, _settings, stop_event, _effective_config_loader):
        observed_stop_states.append(stop_event.is_set())

    monkeypatch.setattr(web_scheduler, "_auto_update_scheduler_loop", fake_loop)

    thread = web_scheduler.start_auto_update_scheduler(
        app,
        settings,
        effective_config_loader=lambda _settings: None,
    )

    assert thread is not None
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert observed_stop_states == [False]
    assert app.state.web_auto_update_stop is not old_stop
    assert app.state.web_auto_update_thread is thread


def test_auto_update_scheduler_applies_due_policy_at_configured_local_time(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_TIMEZONE": "America/Chicago",
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
    (fake_root / "images" / "repo_app_latest.id").write_text(
        "old\n",
        encoding="utf-8",
    )
    (fake_root / "images" / "repo_app_latest.after_id").write_text(
        "new\n",
        encoding="utf-8",
    )
    policy = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "live",
            "auto_update": True,
            "auto_update_time": "09:30",
            "auto_update_days": ["sat"],
        },
        headers=_csrf_headers(client),
    )

    now = datetime(2026, 5, 30, 14, 30, tzinfo=timezone.utc)
    client.app.state.web_auto_update_started_at = now - timedelta(minutes=30)
    response = _auto_update_tick(client, now)
    assert response is not None
    job = _wait_apply_job(client, response.job_id)
    second_response = _auto_update_tick(client, now + timedelta(minutes=1))

    assert policy.status_code == 200
    assert job["status"] == "success"
    assert job["selected_line_numbers"] == [1]
    assert second_response is None
    assert wud_file.read_text(encoding="utf-8") == ""
    calls = _fake_docker_calls(fake_root)
    assert "compose -f docker-compose.yml pull app" in calls
    assert "compose -f docker-compose.yml up -d --remove-orphans --no-deps app" in calls

    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        schedule_rows = conn.execute(
            """
            SELECT *
            FROM auto_update_schedule_runs
            ORDER BY schedule_key
            """
        ).fetchall()
        detail = client.get(f"/api/v1/runs/{job['run_id']}").json()

    assert len(schedule_rows) == 1
    assert schedule_rows[0]["schedule_key"] == (
        "stack/app|2026-05-30|09:30|America/Chicago"
    )
    assert schedule_rows[0]["status"] == "success"
    assert schedule_rows[0]["run_id"] == job["run_id"]
    assert datetime.fromisoformat(schedule_rows[0]["updated_at"]) >= datetime.fromisoformat(
        schedule_rows[0]["created_at"]
    )
    schedule_metadata = json.loads(schedule_rows[0]["metadata_json"])
    assert schedule_metadata["job_id"] == response.job_id
    assert schedule_metadata["line_numbers"] == [1]
    assert schedule_metadata["service_keys"] == ["stack/app"]
    assert schedule_metadata["scheduled_for"] == "2026-05-30T14:30:00+00:00"
    assert schedule_metadata["status"] == "success"
    assert schedule_metadata["timezone"] == "America/Chicago"
    assert schedule_metadata["run_id"] == job["run_id"]
    assert detail["metadata"]["source"] == "webui-auto"
    assert detail["metadata"]["actor_type"] == "scheduler"
    assert detail["metadata"]["auto_update_service_keys"] == ["stack/app"]
    assert detail["metadata"]["auto_update_scheduled_for"] == (
        "2026-05-30T14:30:00+00:00"
    )


def test_auto_update_scheduler_submits_after_reservation_commit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_TIMEZONE": "America/Chicago",
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
    policy = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "live",
            "auto_update": True,
            "auto_update_time": "09:30",
            "auto_update_days": ["sat"],
        },
        headers=_csrf_headers(client),
    )
    observed: dict[str, object] = {}

    def submit_after_commit(*_args, **kwargs):
        with open_db(tmp_path / "state" / "wud.sqlite") as conn:
            row = conn.execute(
                """
                SELECT status
                FROM auto_update_schedule_runs
                WHERE schedule_key = ?
                """,
                ("stack/app|2026-05-30|09:30|America/Chicago",),
            ).fetchone()
        assert row is not None
        assert row["status"] == "reserved"
        kwargs["wud_lock"].close()
        observed["start_event"] = kwargs["start_event"]
        return web_scheduler.ApplyJobResponse(
            job_id="job-after-commit",
            status="queued",
            selected_line_numbers=[1],
        )

    monkeypatch.setattr(web_jobs, "_submit_apply_job_state", submit_after_commit)
    now = datetime(2026, 5, 30, 14, 30, tzinfo=timezone.utc)
    client.app.state.web_auto_update_started_at = now - timedelta(minutes=30)
    response = _auto_update_tick(client, now)

    assert policy.status_code == 200
    assert response is not None
    assert response.job_id == "job-after-commit"
    assert observed["start_event"].is_set()
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        row = conn.execute(
            """
            SELECT status, metadata_json
            FROM auto_update_schedule_runs
            WHERE schedule_key = ?
            """,
            ("stack/app|2026-05-30|09:30|America/Chicago",),
        ).fetchone()

    assert row is not None
    assert row["status"] == "queued"
    metadata = json.loads(row["metadata_json"])
    assert metadata["job_id"] == "job-after-commit"
    assert metadata["status"] == "queued"


def test_auto_update_scheduler_records_failed_policy_run(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_TIMEZONE": "America/Chicago",
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
    policy = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "live",
            "auto_update": True,
            "auto_update_time": "09:30",
            "auto_update_days": ["sat"],
        },
        headers=_csrf_headers(client),
    )

    now = datetime(2026, 5, 30, 14, 30, tzinfo=timezone.utc)
    client.app.state.web_auto_update_started_at = now - timedelta(minutes=30)
    response = _auto_update_tick(client, now)
    assert response is not None
    job = _wait_apply_job(client, response.job_id)

    assert policy.status_code == 200
    assert job["status"] == "failure"
    assert job["run_id"]
    assert wud_file.read_text(encoding="utf-8") == original
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        schedule_rows = conn.execute(
            """
            SELECT *
            FROM auto_update_schedule_runs
            ORDER BY schedule_key
            """
        ).fetchall()
        detail = client.get(f"/api/v1/runs/{job['run_id']}").json()

    assert len(schedule_rows) == 1
    assert schedule_rows[0]["schedule_key"] == (
        "stack/app|2026-05-30|09:30|America/Chicago"
    )
    assert schedule_rows[0]["status"] == "failure"
    assert schedule_rows[0]["run_id"] == job["run_id"]
    assert datetime.fromisoformat(schedule_rows[0]["updated_at"]) >= datetime.fromisoformat(
        schedule_rows[0]["created_at"]
    )
    schedule_metadata = json.loads(schedule_rows[0]["metadata_json"])
    assert schedule_metadata["status"] == "failure"
    assert schedule_metadata["run_id"] == job["run_id"]
    assert "updater exited with status 1" in schedule_metadata["error"]
    assert detail["status"] == "failure"


def test_auto_update_scheduler_applies_due_policy_within_grace_window(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_TIMEZONE": "America/Chicago",
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
    (fake_root / "images" / "repo_app_latest.id").write_text("old\n", encoding="utf-8")
    (fake_root / "images" / "repo_app_latest.after_id").write_text(
        "new\n",
        encoding="utf-8",
    )
    policy = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "live",
            "auto_update": True,
            "auto_update_time": "09:30",
            "auto_update_days": ["sat"],
        },
        headers=_csrf_headers(client),
    )

    now = datetime(2026, 5, 30, 14, 34, 59, tzinfo=timezone.utc)
    client.app.state.web_auto_update_started_at = now - timedelta(minutes=30)
    response = _auto_update_tick(client, now)
    assert response is not None
    job = _wait_apply_job(client, response.job_id)

    assert policy.status_code == 200
    assert job["status"] == "success"
    assert wud_file.read_text(encoding="utf-8") == ""


def test_auto_update_scheduler_applies_due_policy_after_local_midnight(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_TIMEZONE": "America/Chicago",
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
    (fake_root / "images" / "repo_app_latest.id").write_text("old\n", encoding="utf-8")
    (fake_root / "images" / "repo_app_latest.after_id").write_text(
        "new\n",
        encoding="utf-8",
    )
    policy = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "live",
            "auto_update": True,
            "auto_update_time": "23:58",
            "auto_update_days": ["sat"],
        },
        headers=_csrf_headers(client),
    )

    now = datetime(2026, 5, 31, 5, 1, tzinfo=timezone.utc)
    client.app.state.web_auto_update_started_at = now - timedelta(minutes=30)
    response = _auto_update_tick(client, now)
    assert response is not None
    job = _wait_apply_job(client, response.job_id)

    assert policy.status_code == 200
    assert job["status"] == "success"
    assert wud_file.read_text(encoding="utf-8") == ""
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        schedule_row = conn.execute(
            """
            SELECT *
            FROM auto_update_schedule_runs
            """
        ).fetchone()

    assert schedule_row is not None
    assert schedule_row["schedule_key"] == (
        "stack/app|2026-05-30|23:58|America/Chicago"
    )
    assert schedule_row["scheduled_for"] == "2026-05-31T04:58:00+00:00"


def test_auto_update_scheduler_does_not_apply_late_pending_after_grace_window(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_TIMEZONE": "America/Chicago",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    wud_file.write_text("", encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )
    policy = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "live",
            "auto_update": True,
            "auto_update_time": "09:30",
            "auto_update_days": ["sat"],
        },
        headers=_csrf_headers(client),
    )

    scheduled = datetime(2026, 5, 30, 14, 30, tzinfo=timezone.utc)
    client.app.state.web_auto_update_started_at = scheduled - timedelta(minutes=30)
    empty_response = _auto_update_tick(client, scheduled)
    original = "repo/app:latest\n"
    wud_file.write_text(original, encoding="utf-8")
    late_response = _auto_update_tick(client, scheduled + timedelta(minutes=5))

    assert policy.status_code == 200
    assert empty_response is None
    assert late_response is None
    assert wud_file.read_text(encoding="utf-8") == original
    assert " up -d " not in _fake_docker_calls(fake_root)
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        rows = conn.execute("SELECT * FROM auto_update_schedule_runs").fetchall()
    assert rows == []


def test_auto_update_scheduler_skips_when_started_after_grace_window(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_TIMEZONE": "America/Chicago",
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
    policy = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "live",
            "auto_update": True,
            "auto_update_time": "09:30",
            "auto_update_days": ["sat"],
        },
        headers=_csrf_headers(client),
    )

    scheduled = datetime(2026, 5, 30, 14, 30, tzinfo=timezone.utc)
    client.app.state.web_auto_update_started_at = scheduled + timedelta(minutes=5)
    response = _auto_update_tick(client, scheduled + timedelta(minutes=6))

    assert policy.status_code == 200
    assert response is None
    assert wud_file.read_text(encoding="utf-8") == original
    assert " up -d " not in _fake_docker_calls(fake_root)


def test_auto_update_scheduler_skips_previously_reserved_schedule(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_TIMEZONE": "America/Chicago",
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
    policy = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "live",
            "auto_update": True,
            "auto_update_time": "09:30",
            "auto_update_days": ["sat"],
        },
        headers=_csrf_headers(client),
    )
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        init_db(conn)
        with conn:
            conn.execute(
                """
                INSERT INTO auto_update_schedule_runs (
                    schedule_key,
                    service_key,
                    scheduled_for,
                    run_id,
                    status,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES (
                    'stack/app|2026-05-30|09:30|America/Chicago',
                    'stack/app',
                    '2026-05-30T14:30:00+00:00',
                    NULL,
                    'success',
                    '2026-05-30T14:30:00+00:00',
                    '2026-05-30T14:30:00+00:00',
                    '{}'
                )
                """
            )

    now = datetime(2026, 5, 30, 14, 30, tzinfo=timezone.utc)
    client.app.state.web_auto_update_started_at = now - timedelta(minutes=30)
    response = _auto_update_tick(client, now)

    assert policy.status_code == 200
    assert response is None
    assert wud_file.read_text(encoding="utf-8") == original
    assert " up -d " not in _fake_docker_calls(fake_root)


def test_auto_update_scheduler_rolls_back_partial_schedule_reservations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_TIMEZONE": "America/Chicago",
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
        [
            ("app", "repo/app:latest", "cid-app"),
            ("worker", "repo/app:latest", "cid-worker"),
        ],
    )
    headers = _csrf_headers(client)
    for service_key in ("stack/app", "stack/worker"):
        policy = client.post(
            "/api/v1/state/operations",
            json={
                "kind": "upsert_service_policy",
                "service_key": service_key,
                "update_mode": "live",
                "auto_update": True,
                "auto_update_time": "09:30",
                "auto_update_days": ["sat"],
            },
            headers=headers,
        )
        assert policy.status_code == 200
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        init_db(conn)
        with conn:
            conn.execute(
                """
                INSERT INTO auto_update_schedule_runs (
                    schedule_key,
                    service_key,
                    scheduled_for,
                    run_id,
                    status,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES (
                    'stack/worker|2026-05-30|09:30|America/Chicago',
                    'stack/worker',
                    '2026-05-30T14:30:00+00:00',
                    NULL,
                    'success',
                    '2026-05-30T14:30:00+00:00',
                    '2026-05-30T14:30:00+00:00',
                    '{}'
                )
                """
            )
    monkeypatch.setattr(
        web_scheduler,
        "_auto_update_schedule_recorded",
        lambda _conn, _schedule_key: False,
    )

    now = datetime(2026, 5, 30, 14, 30, tzinfo=timezone.utc)
    client.app.state.web_auto_update_started_at = now - timedelta(minutes=30)
    response = _auto_update_tick(client, now)

    assert response is None
    assert wud_file.read_text(encoding="utf-8") == original
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        rows = conn.execute(
            """
            SELECT schedule_key
            FROM auto_update_schedule_runs
            ORDER BY schedule_key
            """
        ).fetchall()
    assert [row["schedule_key"] for row in rows] == [
        "stack/worker|2026-05-30|09:30|America/Chicago"
    ]


def test_auto_update_scheduler_rolls_back_reservation_when_queue_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_TIMEZONE": "America/Chicago",
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
    policy = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "live",
            "auto_update": True,
            "auto_update_time": "09:30",
            "auto_update_days": ["sat"],
        },
        headers=_csrf_headers(client),
    )

    def fail_submit(*_args, **_kwargs):
        raise RuntimeError("queue failed")

    monkeypatch.setattr(web_jobs, "_submit_apply_job_state", fail_submit)
    now = datetime(2026, 5, 30, 14, 30, tzinfo=timezone.utc)
    client.app.state.web_auto_update_started_at = now - timedelta(minutes=30)
    try:
        _auto_update_tick(client, now)
    except RuntimeError as exc:
        assert str(exc) == "queue failed"
    else:
        raise AssertionError("queue failure was not raised")

    assert policy.status_code == 200
    assert wud_file.read_text(encoding="utf-8") == original
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        rows = conn.execute("SELECT * FROM auto_update_schedule_runs").fetchall()
    assert rows == []
    contender = DirectoryLock(wud_file, timeout_seconds=0)
    try:
        contender.acquire()
    finally:
        contender.close()


def test_auto_update_scheduler_skips_tag_updates_without_mutation(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_TIMEZONE": "America/Chicago",
            **fake_env,
        },
    )
    wud_file = tmp_path / "state" / "images.todo"
    original = "repo/app:1.0 tag=2.0\n"
    wud_file.write_text(original, encoding="utf-8")
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:1.0", "cid-app")],
    )
    policy = client.post(
        "/api/v1/state/operations",
        json={
            "kind": "upsert_service_policy",
            "service_key": "stack/app",
            "update_mode": "live",
            "auto_update": True,
            "auto_update_time": "09:30",
            "auto_update_days": ["sat"],
        },
        headers=_csrf_headers(client),
    )

    now = datetime(2026, 5, 30, 14, 30, tzinfo=timezone.utc)
    client.app.state.web_auto_update_started_at = now - timedelta(minutes=30)
    response = _auto_update_tick(client, now)

    assert policy.status_code == 200
    assert response is None
    assert wud_file.read_text(encoding="utf-8") == original
    assert " up -d " not in _fake_docker_calls(fake_root)
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        rows = conn.execute("SELECT * FROM auto_update_schedule_runs").fetchall()
    assert rows == []


def test_auto_update_candidate_reuses_effective_config_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env = _web_env(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    settings = web_module.load_web_settings(env)
    settings.config.wud_out_file.write_text("repo/app:latest\n", encoding="utf-8")
    now = datetime(2026, 5, 30, 14, 30, tzinfo=timezone.utc)
    first_config = replace(settings.config, docker_base=tmp_path / "first")
    second_config = replace(settings.config, docker_base=tmp_path / "second")
    loaded_settings: list[object] = []
    observed: dict[str, object] = {}

    def effective_config_loader(loaded_settings_arg):
        loaded_settings.append(loaded_settings_arg)
        return first_config if len(loaded_settings) == 1 else second_config

    def fake_resolve_pending_groups(
        config,
        _parsed,
        *,
        host_docker_base,
        environ,
        known_digest_provenance_by_service,
    ):
        observed["resolve_config"] = config
        observed["host_docker_base"] = host_docker_base
        observed["environ"] = environ
        observed["grouping_provenance"] = known_digest_provenance_by_service
        return SimpleNamespace(
            status="ready",
            groups=(
                SimpleNamespace(
                    name="stack",
                    items=(
                        SimpleNamespace(
                            desired_tag="",
                            line_no=1,
                            services=("app",),
                        ),
                    ),
                ),
            ),
        )

    def fake_build_dry_run_plan(config, **kwargs):
        observed["plan_config"] = config
        observed["plan_kwargs"] = kwargs
        return SimpleNamespace(status="ready", skipped=(), issues=())

    monkeypatch.setattr(
        web_scheduler,
        "resolve_pending_groups",
        fake_resolve_pending_groups,
    )
    monkeypatch.setattr(web_scheduler, "build_dry_run_plan", fake_build_dry_run_plan)
    with open_db(settings.config.db_path) as conn:
        init_db(conn)
        upsert_known_image(
            conn,
            service_key="stack/app",
            image="repo/app@sha256:old",
            image_id="sha256:old-id",
            digest="repo/app@sha256:old",
            digest_provenance=DigestTagProvenance(
                source_image="repo/app:latest",
                resolved_tag="latest",
                watch_tag="latest",
                target_digest="sha256:old",
                final_image="repo/app@sha256:old",
                provenance_source="apply",
                provenance_confidence="verified",
            ),
        )
        with conn:
            conn.execute(
                """
                INSERT INTO service_policy (
                    service_key,
                    update_mode,
                    auto_update,
                    created_at,
                    updated_at,
                    metadata_json,
                    auto_update_time,
                    auto_update_days_json
                )
                VALUES (?, '', 1, ?, ?, '{}', ?, ?)
                """,
                (
                    "stack/app",
                    now.isoformat(),
                    now.isoformat(),
                    "14:30",
                    json.dumps(["sat"]),
                ),
            )
        candidate = web_scheduler._auto_update_candidate(
            conn,
            settings,
            effective_config_loader=effective_config_loader,
            now_utc=now,
            started_at=now - timedelta(minutes=30),
        )

    assert candidate is not None
    selection, plan = candidate
    assert plan.status == "ready"
    assert selection.line_numbers == (1,)
    assert len(loaded_settings) == 1
    assert observed["resolve_config"] is first_config
    assert observed["host_docker_base"] == settings.host_docker_base
    assert observed["environ"] == settings.command_env
    grouping_provenance = observed["grouping_provenance"]
    assert grouping_provenance["stack/app"].resolved_tag == "latest"
    assert observed["plan_config"].docker_base == first_config.docker_base
    assert observed["plan_config"].docker_base != second_config.docker_base
    assert observed["plan_kwargs"]["line_numbers"] == (1,)
    plan_provenance = observed["plan_kwargs"]["known_digest_provenance_by_service"]
    assert plan_provenance is grouping_provenance


def test_auto_update_selection_prefers_earliest_scheduled_mode() -> None:
    earlier = datetime(2026, 5, 30, 14, 0, tzinfo=timezone.utc)
    later = datetime(2026, 5, 30, 15, 0, tzinfo=timezone.utc)
    settings = SimpleNamespace(config=SimpleNamespace(update_mode="live"))
    grouping = SimpleNamespace(
        groups=(
            SimpleNamespace(
                name="stack",
                items=(
                    SimpleNamespace(
                        desired_tag="",
                        line_no=1,
                        services=("app",),
                    ),
                    SimpleNamespace(
                        desired_tag="",
                        line_no=2,
                        services=("worker",),
                    ),
                ),
            ),
        ),
    )
    policies = {
        "stack/app": web_scheduler.AutoUpdatePolicy(
            service_key="stack/app",
            update_mode="a-later",
            auto_update_time="10:00",
            auto_update_days=("sat",),
            schedule_key="stack/app|2026-05-30|10:00|America/Chicago",
            scheduled_for=later,
        ),
        "stack/worker": web_scheduler.AutoUpdatePolicy(
            service_key="stack/worker",
            update_mode="z-earlier",
            auto_update_time="09:00",
            auto_update_days=("sat",),
            schedule_key="stack/worker|2026-05-30|09:00|America/Chicago",
            scheduled_for=earlier,
        ),
    }

    selection = web_scheduler._auto_update_selection(settings, grouping, policies)

    assert selection is not None
    assert selection.update_mode == "z-earlier"
    assert selection.line_numbers == (2,)
    assert selection.service_keys == ("stack/worker",)
    assert selection.schedule_keys == (
        "stack/worker|2026-05-30|09:00|America/Chicago",
    )
    assert selection.scheduled_for == earlier

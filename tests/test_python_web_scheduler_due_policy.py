from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from wudup import web as web_module
from wudup import web_scheduler
from wudup.db import init_db, open_db, upsert_known_image
from wudup.digest_provenance import DigestTagProvenance

from tests.web_test_helpers import (
    _client,
    _csrf_headers,
    _fake_docker_calls,
    _fake_docker_env,
    _make_fake_stack,
    _web_env,
    _wait_apply_job,
)

from tests.web_scheduler_test_helpers import _auto_update_tick

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

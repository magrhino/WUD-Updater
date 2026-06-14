from __future__ import annotations

from pathlib import Path

from tests.web_test_helpers import (
    _assert_pending_grouping_did_not_mutate,
    _client,
    _csrf_headers,
    _fake_docker_calls,
    _fake_docker_env,
    _make_fake_stack,
    _wait_apply_job,
)
from wud_updater.db import init_db, open_db, upsert_known_image
from wud_updater.digest_provenance import DigestTagProvenance
from wud_updater.web_models import WebApplyJob


def test_retag_targets_endpoint_returns_eligible_digest_pinned_service(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app@sha256:old", "cid-app")],
    )
    _write_compose(
        compose_dir,
        "app",
        "repo/app@sha256:old",
        label_value="^latest$$",
    )
    _seed_known_image(
        tmp_path,
        service_key="stack/app",
        image="repo/app@sha256:old",
        source_image="repo/app:latest",
        resolved_tag="2.0",
        watch_tag="latest",
        target_digest="sha256:old",
        final_image="repo/app@sha256:old",
    )
    before = (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")

    response = client.get("/api/v1/retag-targets")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["count"] == 1
    assert body["warnings"] == []
    item = body["items"][0]
    assert item["service_key"] == "stack/app"
    assert item["image"] == "repo/app@sha256:old"
    assert item["current_tag"] == ""
    assert item["tracking_tag"] == "latest"
    assert item["tracking_tag_source"] == "label"
    assert item["label_key"] == "wud.tag.include"
    assert item["label_value"] == "^latest$$"
    assert item["proposed_tag"] == "2.0"
    assert item["final_image"] == "repo/app@sha256:old"
    assert item["retag_available"] is True
    assert item["retag_reason"] == "eligible"
    assert item["choices"] == ["keep-current", "switch-to-concrete"]
    assert item["digest_provenance"]["resolved_tag"] == "2.0"
    assert (compose_dir / "docker-compose.yml").read_text(encoding="utf-8") == before
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_retag_targets_endpoint_marks_ineligible_review_states(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [
            ("latest", "repo/latest:latest", "cid-latest"),
            ("concrete", "repo/concrete:1.0", "cid-concrete"),
            ("custom", "repo/custom:latest", "cid-custom"),
            ("escaped", "repo/escaped:latest", "cid-escaped"),
        ],
    )
    (compose_dir / "docker-compose.yml").write_text(
        "\n".join(
            [
                "services:",
                "  latest:",
                "    image: repo/latest:latest",
                "  concrete:",
                "    image: repo/concrete:1.0",
                "  custom:",
                "    image: repo/custom:latest",
                "    labels:",
                "      - wud.tag.include=^latest|stable$",
                "  escaped:",
                "    image: repo/escaped:latest",
                "    labels:",
                "      - wud.tag.include=^2\\.0$$",
                "",
            ]
        ),
        encoding="utf-8",
    )

    response = client.get("/api/v1/retag-targets")

    assert response.status_code == 200
    items = {item["service"]: item for item in response.json()["items"]}
    assert items["latest"]["tracking_tag"] == "latest"
    assert items["latest"]["retag_available"] is False
    assert items["latest"]["retag_reason"] == "missing-provenance"
    assert items["latest"]["choices"] == ["keep-current"]
    assert items["concrete"]["tracking_tag"] == "1.0"
    assert items["concrete"]["retag_reason"] == "not-latest-tracking"
    assert items["custom"]["tracking_tag"] == ""
    assert items["custom"]["tracking_tag_source"] == "unsupported-label"
    assert items["custom"]["retag_reason"] == "unsupported-tracking-label"
    assert items["escaped"]["tracking_tag"] == "2.0"
    assert items["escaped"]["tracking_tag_source"] == "label"
    assert items["escaped"]["retag_reason"] == "not-latest-tracking"
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_retag_targets_endpoint_marks_stale_known_provenance(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app@sha256:current", "cid-app")],
    )
    _write_compose(
        compose_dir,
        "app",
        "repo/app@sha256:current",
        label_value="^latest$$",
    )
    _seed_known_image(
        tmp_path,
        service_key="stack/app",
        image="repo/app@sha256:old",
        source_image="repo/app:latest",
        resolved_tag="2.0",
        watch_tag="latest",
        target_digest="sha256:old",
        final_image="repo/app@sha256:old",
    )

    response = client.get("/api/v1/retag-targets")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["tracking_tag"] == "latest"
    assert item["retag_available"] is False
    assert item["retag_reason"] == "stale-provenance"
    assert item["proposed_tag"] == "2.0"
    assert item["final_image"] == "repo/app@sha256:old"
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_retag_targets_endpoint_includes_service_without_pending_line(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )

    response = client.get("/api/v1/retag-targets")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["service_key"] == "stack/app"
    assert body["items"][0]["tracking_tag"] == "latest"
    assert body["items"][0]["retag_reason"] == "missing-provenance"
    assert not (tmp_path / "state" / "images.todo").exists()
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_retag_targets_endpoint_returns_unavailable_when_discovery_fails(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get("/api/v1/retag-targets")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["count"] == 0
    assert body["items"] == []
    assert body["warnings"]


def test_retag_plan_and_apply_rewrites_pulls_recreates_and_audits(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_UPDATE_MODE": "live",
            "WUD_MAX_WAIT": "0",
            **fake_env,
        },
    )
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app@sha256:old", "cid-app")],
    )
    _write_compose(
        compose_dir,
        "app",
        "repo/app@sha256:old",
        label_value="^latest$$",
    )
    _seed_known_image(
        tmp_path,
        service_key="stack/app",
        image="repo/app@sha256:old",
        source_image="repo/app:latest",
        resolved_tag="2.0",
        watch_tag="latest",
        target_digest="sha256:old",
        final_image="repo/app@sha256:old",
    )
    headers = _csrf_headers(client)

    plan_response = client.post(
        "/api/v1/retag-plans",
        json={"choices": [{"service_key": "stack/app", "choice": "switch-to-concrete"}]},
        headers=headers,
    )

    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["status"] == "ready"
    assert plan["can_apply"] is True
    assert plan["selected_count"] == 1
    assert plan["external_recreate_required"] is False
    assert plan["stacks"][0]["services"] == ["app"]
    assert plan["stacks"][0]["digest_pin_updates"][0]["resolved_tag"] == "2.0"

    apply_response = client.post(
        "/api/v1/retag-plans/apply",
        json={
            "plan_id": plan["plan_id"],
            "choices": [{"service_key": "stack/app", "choice": "switch-to-concrete"}],
            "confirmation": "apply-retags",
        },
        headers=headers,
    )

    assert apply_response.status_code == 202
    job = _wait_apply_job(client, apply_response.json()["job_id"])
    assert job["status"] == "success"
    content = (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")
    assert "# wud-updater.resolved-tag=2.0" in content
    assert "image: repo/app@sha256:old" in content
    assert "wud.tag.include=^2\\.0$$" in content
    calls = _fake_docker_calls(fake_root)
    assert "compose -f docker-compose.yml pull app" in calls
    assert "compose -f docker-compose.yml up -d --remove-orphans --force-recreate --no-deps app" in calls

    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        run = conn.execute(
            "SELECT mode, status FROM update_runs WHERE id = ?",
            (job["run_id"],),
        ).fetchone()
        event = conn.execute(
            "SELECT stack_name, service_name, status, target_image, digest_provenance_source "
            "FROM update_events WHERE run_id = ?",
            (job["run_id"],),
        ).fetchone()
        known = conn.execute(
            "SELECT image, digest_provenance_source, digest_watch_tag "
            "FROM known_images WHERE service_key = 'stack/app'",
        ).fetchone()
    assert run["mode"] == "web-retag"
    assert run["status"] == "success"
    assert event["stack_name"] == "stack"
    assert event["service_name"] == "app"
    assert event["status"] == "success"
    assert event["target_image"] == "repo/app@sha256:old"
    assert event["digest_provenance_source"] == "retag"
    assert known["image"] == "repo/app@sha256:old"
    assert known["digest_provenance_source"] == "retag"
    assert known["digest_watch_tag"] == "2.0"


def test_retag_plan_keep_current_is_empty_noop(tmp_path: Path) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            **fake_env,
        },
    )
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app@sha256:old", "cid-app")],
    )
    _write_compose(
        compose_dir,
        "app",
        "repo/app@sha256:old",
        label_value="^latest$$",
    )
    _seed_known_image(
        tmp_path,
        service_key="stack/app",
        image="repo/app@sha256:old",
        source_image="repo/app:latest",
        resolved_tag="2.0",
        watch_tag="latest",
        target_digest="sha256:old",
        final_image="repo/app@sha256:old",
    )
    headers = _csrf_headers(client)

    response = client.post(
        "/api/v1/retag-plans",
        json={"choices": [{"service_key": "stack/app", "choice": "keep-current"}]},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "empty"
    assert body["can_apply"] is False
    assert body["selected_count"] == 0
    assert body["keep_current_count"] == 1
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_retag_apply_rejects_stale_plan(tmp_path: Path) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            **fake_env,
        },
    )
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app@sha256:old", "cid-app")],
    )
    _write_compose(
        compose_dir,
        "app",
        "repo/app@sha256:old",
        label_value="^latest$$",
    )
    _seed_known_image(
        tmp_path,
        service_key="stack/app",
        image="repo/app@sha256:old",
        source_image="repo/app:latest",
        resolved_tag="2.0",
        watch_tag="latest",
        target_digest="sha256:old",
        final_image="repo/app@sha256:old",
    )
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/retag-plans",
        json={"choices": [{"service_key": "stack/app", "choice": "switch-to-concrete"}]},
        headers=headers,
    ).json()
    _write_compose(
        compose_dir,
        "app",
        "repo/app@sha256:old",
        label_value="^2\\.0$$",
    )

    response = client.post(
        "/api/v1/retag-plans/apply",
        json={
            "plan_id": plan["plan_id"],
            "choices": [{"service_key": "stack/app", "choice": "switch-to-concrete"}],
            "confirmation": "apply-retags",
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "retag plan is stale"


def test_retag_plan_rejects_duplicate_and_unknown_choices(tmp_path: Path) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env},
    )
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )
    headers = _csrf_headers(client)

    duplicate = client.post(
        "/api/v1/retag-plans",
        json={
            "choices": [
                {"service_key": "stack/app", "choice": "keep-current"},
                {"service_key": "stack/app", "choice": "keep-current"},
            ]
        },
        headers=headers,
    )
    unknown = client.post(
        "/api/v1/retag-plans",
        json={"choices": [{"service_key": "stack/missing", "choice": "keep-current"}]},
        headers=headers,
    )

    assert duplicate.status_code == 422
    assert "duplicate" in duplicate.json()["detail"]
    assert unknown.status_code == 422
    assert "unknown service" in unknown.json()["detail"]


def test_retag_apply_enforces_csrf_read_only_and_active_job(tmp_path: Path) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    read_only = _client(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env},
    )
    mutating = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            **fake_env,
        },
    )
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app:latest", "cid-app")],
    )
    payload = {
        "plan_id": "plan",
        "choices": [{"service_key": "stack/app", "choice": "keep-current"}],
        "confirmation": "apply-retags",
    }
    read_only_response = read_only.post(
        "/api/v1/retag-plans/apply",
        json=payload,
        headers=_csrf_headers(read_only),
    )
    missing_csrf = mutating.post("/api/v1/retag-plans/apply", json=payload)
    mutating.app.state.web_apply_jobs["active"] = WebApplyJob(
        id="active",
        status="running",
        selected_line_numbers=(),
    )
    active_job = mutating.post(
        "/api/v1/retag-plans/apply",
        json=payload,
        headers=_csrf_headers(mutating),
    )

    assert read_only_response.status_code == 403
    assert read_only_response.json()["detail"] == "mutations are disabled"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "origin header is required"
    assert active_job.status_code == 409
    assert active_job.json()["detail"] == "an apply job is already running"


def test_retag_apply_restores_compose_when_pull_fails(tmp_path: Path) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_UPDATE_MODE": "live",
            "WUD_MAX_WAIT": "0",
            **fake_env,
        },
    )
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "repo/app@sha256:old", "cid-app")],
    )
    _write_compose(
        compose_dir,
        "app",
        "repo/app@sha256:old",
        label_value="^latest$$",
    )
    _seed_known_image(
        tmp_path,
        service_key="stack/app",
        image="repo/app@sha256:old",
        source_image="repo/app:latest",
        resolved_tag="2.0",
        watch_tag="latest",
        target_digest="sha256:old",
        final_image="repo/app@sha256:old",
    )
    (fake_root / "stacks" / "stack" / "pull_fail").write_text(
        "pull failed\n",
        encoding="utf-8",
    )
    before = (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")
    headers = _csrf_headers(client)
    plan = client.post(
        "/api/v1/retag-plans",
        json={"choices": [{"service_key": "stack/app", "choice": "switch-to-concrete"}]},
        headers=headers,
    ).json()

    response = client.post(
        "/api/v1/retag-plans/apply",
        json={
            "plan_id": plan["plan_id"],
            "choices": [{"service_key": "stack/app", "choice": "switch-to-concrete"}],
            "confirmation": "apply-retags",
        },
        headers=headers,
    )

    assert response.status_code == 202
    job = _wait_apply_job(client, response.json()["job_id"])
    assert job["status"] == "failure"
    assert (compose_dir / "docker-compose.yml").read_text(encoding="utf-8") == before
    calls = _fake_docker_calls(fake_root)
    assert "compose -f docker-compose.yml pull app" in calls
    assert "compose -f docker-compose.yml up -d --remove-orphans --force-recreate --no-deps app" in calls
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        run = conn.execute(
            "SELECT status FROM update_runs WHERE id = ?",
            (job["run_id"],),
        ).fetchone()
    assert run["status"] == "failure"


def _seed_known_image(
    tmp_path: Path,
    *,
    service_key: str,
    image: str,
    source_image: str,
    resolved_tag: str,
    watch_tag: str,
    target_digest: str,
    final_image: str,
) -> None:
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        init_db(conn)
        upsert_known_image(
            conn,
            service_key=service_key,
            image=image,
            digest_provenance=DigestTagProvenance(
                source_image=source_image,
                resolved_tag=resolved_tag,
                watch_tag=watch_tag,
                target_digest=target_digest,
                final_image=final_image,
                provenance_source="apply",
                provenance_confidence="verified",
            ),
        )


def _write_compose(
    compose_dir: Path,
    service: str,
    image: str,
    *,
    label_value: str,
) -> None:
    (compose_dir / "docker-compose.yml").write_text(
        "\n".join(
            [
                "services:",
                f"  {service}:",
                f"    image: {image}",
                "    labels:",
                f"      - wud.tag.include={label_value}",
                "",
            ]
        ),
        encoding="utf-8",
    )

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, fields
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient
from httpx import Response
import pytest

from tests.web_test_helpers import (
    _assert_pending_grouping_did_not_mutate,
    _client,
    _csrf_headers,
    _fake_docker_calls,
    _fake_docker_env,
    _make_fake_stack,
    _wait_apply_job,
)
from wudup.db import init_db, open_db, upsert_known_image
from wudup.digest_verifier import DigestResolveResult
from wudup.digest_provenance import DigestTagProvenance
from wudup import web_database
from wudup import web_retags as web_retags_module
from wudup.web_models import WebApplyJob


@dataclass(frozen=True)
class _RetagFixture:
    client: TestClient
    compose_dir: Path
    fake_root: Path


def test_retag_targets_endpoint_returns_eligible_digest_pinned_service(
    tmp_path: Path,
) -> None:
    fixture = _make_retag_fixture(tmp_path)
    client = fixture.client
    compose_dir = fixture.compose_dir
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
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fixture.fake_root))


@pytest.mark.parametrize(
    "provenance_field",
    [field.name for field in fields(DigestTagProvenance)],
)
def test_known_digest_state_reads_any_non_empty_provenance_column(
    tmp_path: Path,
    provenance_field: str,
) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    provenance_value = f"value-for-{provenance_field}"
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        init_db(conn)
        upsert_known_image(
            conn,
            service_key="stack/app",
            image="repo/app:latest",
            digest_provenance=DigestTagProvenance(
                **{provenance_field: provenance_value},
            ),
        )

    state = web_database.known_digest_state_by_service(
        client.app.state.web_settings,
    )
    provenance = web_database.known_digest_provenance_by_service(
        client.app.state.web_settings,
    )

    assert state["stack/app"].image == "repo/app:latest"
    assert (
        getattr(state["stack/app"].digest_provenance, provenance_field)
        == provenance_value
    )
    assert getattr(provenance["stack/app"], provenance_field) == provenance_value
    for field in fields(DigestTagProvenance):
        if field.name == provenance_field:
            continue
        assert getattr(state["stack/app"].digest_provenance, field.name) == ""
        assert getattr(provenance["stack/app"], field.name) == ""


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


def test_retag_github_latest_fallback_refresh_enables_cached_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "ghcr.io/acme/app:latest", "cid-app")],
    )
    digest = "sha256:" + "b" * 64
    _patch_github_latest(
        monkeypatch,
        tag="v1.2.3",
        url="https://github.com/acme/app/releases/tag/v1.2.3",
    )
    _patch_digest_resolution(
        monkeypatch,
        expected_image="ghcr.io/acme/app:v1.2.3",
        digest=digest,
    )

    missing_csrf = client.post("/api/v1/retag-targets/github-latest/refresh")
    refresh = client.post(
        "/api/v1/retag-targets/github-latest/refresh",
        headers=_csrf_headers(client),
    )
    cached = client.get(
        "/api/v1/retag-targets",
        params={"github_latest_fallback": "true"},
    )
    plain = client.get("/api/v1/retag-targets")

    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "origin header is required"
    assert refresh.status_code == 200
    item = refresh.json()["items"][0]
    assert item["retag_available"] is True
    assert item["retag_reason"] == "eligible"
    assert item["proposed_tag"] == "v1.2.3"
    assert item["final_image"] == f"ghcr.io/acme/app@{digest}"
    assert item["candidate_source"] == "github-latest"
    assert "will update latest tracking to v1.2.3" in item["candidate_warning"]
    assert item["candidate_link_label"] == "GitHub release"
    assert item["candidate_link_url"].endswith("/v1.2.3")
    assert item["digest_provenance"]["provenance_source"] == "github-latest"
    assert cached.json()["items"][0]["retag_available"] is True
    assert plain.json()["items"][0]["retag_reason"] == "missing-provenance"
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_retag_preview_refreshes_github_latest_before_building_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "ghcr.io/acme/app:latest", "cid-app")],
    )
    digest = "sha256:" + "d" * 64
    _patch_github_latest(
        monkeypatch,
        tag="v1.2.3",
        url="https://github.com/acme/app/releases/tag/v1.2.3",
    )
    _patch_digest_resolution(
        monkeypatch,
        expected_image="ghcr.io/acme/app:v1.2.3",
        digest=digest,
    )

    missing_csrf = client.post(
        "/api/v1/retag-plans/preview",
        json={
            "choices": [_switch_choice()],
            "github_latest_fallback": True,
        },
    )
    started = client.post(
        "/api/v1/retag-plans/preview",
        json={
            "choices": [_switch_choice()],
            "github_latest_fallback": True,
        },
        headers=_csrf_headers(client),
    )
    assert started.status_code == 202
    job = _wait_retag_preview_job(client, started.json()["preview_job_id"])

    assert missing_csrf.status_code == 403
    assert job["status"] == "success"
    assert [event["phase"] for event in job["progress"]] == ["refresh", "refresh", "preview"]
    plan = job["plan"]
    assert plan["status"] == "ready"
    assert plan["can_apply"] is True
    update = plan["stacks"][0]["digest_pin_updates"][0]
    assert update["resolved_tag"] == "v1.2.3"
    assert update["planned_digest"] == digest
    assert update["final_image"] == f"ghcr.io/acme/app@{digest}"
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_retag_preview_rejects_second_active_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)
    started = Event()
    release = Event()

    def slow_preview_job(
        state: object,
        _settings: object,
        _payload: object,
        job_id: str,
    ) -> None:
        web_retags_module._update_retag_preview_job(
            state,
            job_id,
            status="running",
        )
        started.set()
        release.wait(timeout=2)
        web_retags_module._update_retag_preview_job(
            state,
            job_id,
            status="failure",
            error="test preview released",
        )

    monkeypatch.setattr(
        web_retags_module,
        "_run_retag_plan_preview_job",
        slow_preview_job,
    )

    first = client.post(
        "/api/v1/retag-plans/preview",
        json={"choices": [_switch_choice()]},
        headers=headers,
    )
    assert first.status_code == 202
    assert started.wait(timeout=1)

    second = client.post(
        "/api/v1/retag-plans/preview",
        json={"choices": [_switch_choice()]},
        headers=headers,
    )

    assert second.status_code == 409
    assert second.json()["detail"] == "retag preview is already running"
    release.set()
    job = _wait_retag_preview_job(client, first.json()["preview_job_id"])
    assert job["status"] == "failure"


def test_retag_preview_warns_when_github_latest_candidate_changes_after_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "ghcr.io/acme/app:latest", "cid-app")],
    )
    old_digest = "sha256:" + "e" * 64
    new_digest = "sha256:" + "f" * 64
    headers = _csrf_headers(client)
    _patch_github_latest(
        monkeypatch,
        tag="v1.0.0",
        url="https://github.com/acme/app/releases/tag/v1.0.0",
    )
    _patch_digest_resolution(
        monkeypatch,
        expected_image="ghcr.io/acme/app:v1.0.0",
        digest=old_digest,
    )
    cached = client.post(
        "/api/v1/retag-targets/github-latest/refresh",
        headers=headers,
    )
    assert cached.status_code == 200

    _patch_github_latest(
        monkeypatch,
        tag="v1.1.0",
        url="https://github.com/acme/app/releases/tag/v1.1.0",
    )
    _patch_digest_resolution_map(
        monkeypatch,
        {
            "ghcr.io/acme/app:v1.0.0": old_digest,
            "ghcr.io/acme/app:v1.1.0": new_digest,
        },
    )

    started = client.post(
        "/api/v1/retag-plans/preview",
        json={
            "choices": [_switch_choice()],
            "github_latest_fallback": True,
        },
        headers=headers,
    )
    assert started.status_code == 202
    job = _wait_retag_preview_job(client, started.json()["preview_job_id"])

    assert job["status"] == "success"
    plan = job["plan"]
    assert plan["status"] == "ready"
    assert plan["can_apply"] is True
    assert any(
        "tag v1.0.0 -> v1.1.0" in warning
        for warning in plan["warnings"]
    )
    update = plan["stacks"][0]["digest_pin_updates"][0]
    assert update["planned_digest"] == new_digest


def test_retag_apply_rejects_plan_when_fallback_flag_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "ghcr.io/acme/app:latest", "cid-app")],
    )
    _patch_github_latest(
        monkeypatch,
        tag="v1.2.3",
        url="https://github.com/acme/app/releases/tag/v1.2.3",
    )
    _patch_digest_resolution(
        monkeypatch,
        expected_image="ghcr.io/acme/app:v1.2.3",
        digest="sha256:" + "c" * 64,
    )
    headers = _csrf_headers(client)
    refresh = client.post(
        "/api/v1/retag-targets/github-latest/refresh",
        headers=headers,
    )
    assert refresh.status_code == 200
    choices = [_switch_choice()]
    plan_response = client.post(
        "/api/v1/retag-plans",
        json={"choices": choices, "github_latest_fallback": True},
        headers=headers,
    )
    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["status"] == "ready"

    stale = client.post(
        "/api/v1/retag-plans/apply",
        json={
            "plan_id": plan["plan_id"],
            "choices": choices,
            "confirmation": "apply-retags",
        },
        headers=headers,
    )

    assert stale.status_code == 409
    assert stale.json()["detail"] == "retag plan is stale"


def test_retag_github_latest_fallback_uses_v_stripped_docker_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", "ghcr.io/acme/app:latest", "cid-app")],
    )
    digest = "sha256:" + "9" * 64
    _patch_github_latest(
        monkeypatch,
        tag="v1.2.3",
        url="https://github.com/acme/app/releases/tag/v1.2.3",
    )
    _patch_digest_resolution_results(
        monkeypatch,
        {
            "ghcr.io/acme/app:v1.2.3": DigestResolveResult(
                ok=False,
                status="unavailable",
                reason="manifest-unavailable",
            ),
            "ghcr.io/acme/app:1.2.3": DigestResolveResult(
                ok=True,
                status="resolved",
                reason="tag-digest-resolved",
                digest=digest,
                source="test",
            ),
        },
    )

    response = client.post(
        "/api/v1/retag-targets/github-latest/refresh",
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["retag_available"] is True
    assert item["retag_reason"] == "eligible"
    assert item["proposed_tag"] == "1.2.3"
    assert item["final_image"] == f"ghcr.io/acme/app@{digest}"
    assert "release tag v1.2.3 resolved as Docker tag 1.2.3" in item[
        "candidate_warning"
    ]
    assert item["candidate_link_url"].endswith("/v1.2.3")
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_retag_github_latest_fallback_uses_lsio_release_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream_map = tmp_path / "upstreams.txt"
    upstream_map.write_text(
        "linuxserver/docker-radarr: Radarr/Radarr\n",
        encoding="utf-8",
    )
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "UPSTREAM_MAP": str(upstream_map),
            **fake_env,
        },
    )
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("radarr", "ghcr.io/linuxserver/radarr:latest", "cid-radarr")],
    )
    digest = "sha256:" + "a" * 64
    _patch_digest_resolution(
        monkeypatch,
        expected_image="ghcr.io/linuxserver/radarr:5.1.0-ls1",
        digest=digest,
    )
    _patch_github_latest(
        monkeypatch,
        tag="5.1.0-ls1",
        url="https://github.com/linuxserver/docker-radarr/releases/tag/5.1.0-ls1",
        extra={
            "https://api.github.com/repos/Radarr/Radarr/releases/tags/v5.1.0": {
                "tag_name": "v5.1.0",
                "name": "v5.1.0",
                "html_url": "https://github.com/Radarr/Radarr/releases/tag/v5.1.0",
                "body": "Routine update",
                "published_at": "2026-01-02T00:00:00Z",
            }
        },
    )

    response = client.post(
        "/api/v1/retag-targets/github-latest/refresh",
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["retag_available"] is True
    assert item["retag_reason"] == "eligible"
    assert item["proposed_tag"] == "5.1.0-ls1"
    assert item["final_image"] == f"ghcr.io/linuxserver/radarr@{digest}"
    assert "will update latest tracking to 5.1.0-ls1" in item["candidate_warning"]
    assert item["candidate_link_label"] == "LSIO release"
    assert item["candidate_link_url"].endswith("/5.1.0-ls1")
    assert item["digest_provenance"]["provenance_source"] == "github-latest"
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))


def test_retag_github_latest_fallback_does_not_guess_lsio_upstream_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream_map = tmp_path / "upstreams.txt"
    upstream_map.write_text(
        "linuxserver/docker-radarr: Radarr/Radarr\n",
        encoding="utf-8",
    )
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "UPSTREAM_MAP": str(upstream_map),
            **fake_env,
        },
    )
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("radarr", "ghcr.io/linuxserver/radarr:latest", "cid-radarr")],
    )

    class FailDigestVerifier:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            # Test double accepts production constructor arguments but needs no setup.
            pass

        def resolve_tag_digest(self, image: str) -> DigestResolveResult:
            if image == "ghcr.io/linuxserver/radarr:v5.1.0":
                raise AssertionError("LSIO fallback should not use upstream tag")
            return DigestResolveResult(
                ok=False,
                status="unavailable",
                reason="manifest-unavailable",
            )

    monkeypatch.setattr(web_retags_module, "DigestVerifier", FailDigestVerifier)
    _patch_github_latest(
        monkeypatch,
        tag="5.1.0-ls1",
        url="https://github.com/linuxserver/docker-radarr/releases/tag/5.1.0-ls1",
        extra={
            "https://api.github.com/repos/Radarr/Radarr/releases/tags/v5.1.0": {
                "tag_name": "v5.1.0",
                "name": "v5.1.0",
                "html_url": "https://github.com/Radarr/Radarr/releases/tag/v5.1.0",
                "body": "Routine update",
                "published_at": "2026-01-02T00:00:00Z",
            }
        },
    )

    response = client.post(
        "/api/v1/retag-targets/github-latest/refresh",
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["retag_available"] is False
    assert item["retag_reason"] == "missing-provenance"
    assert "5.1.0-ls1: manifest-unavailable" in item["candidate_warning"]
    assert item["choices"] == ["keep-current"]


def test_retag_refresh_and_preview_require_mutations_enabled(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    headers = _csrf_headers(client)

    refresh = client.post(
        "/api/v1/retag-targets/github-latest/refresh",
        headers=headers,
    )
    preview = client.post(
        "/api/v1/retag-plans/preview",
        json={"choices": [_switch_choice()]},
        headers=headers,
    )

    assert refresh.status_code == 403
    assert refresh.json()["detail"] == "mutations are disabled"
    assert preview.status_code == 403
    assert preview.json()["detail"] == "mutations are disabled"


def test_retag_targets_do_not_treat_persisted_source_image_as_current(
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
    _seed_known_image(
        tmp_path,
        service_key="stack/app",
        image="repo/app@sha256:old",
        source_image="repo/app:latest",
        resolved_tag="1.0.0",
        watch_tag="latest",
        target_digest="sha256:old",
        final_image="repo/app@sha256:old",
    )

    response = client.get("/api/v1/retag-targets")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["image"] == "repo/app:latest"
    assert item["retag_available"] is False
    assert item["retag_reason"] == "stale-provenance"
    assert item["choices"] == ["keep-current"]


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
    assert "[REDACTED_PATH]" in body["warnings"][0]
    assert str(tmp_path) not in body["warnings"][0]


def test_retag_plan_and_apply_rewrites_pulls_recreates_and_audits(
    tmp_path: Path,
) -> None:
    fixture = _make_retag_fixture(
        tmp_path,
        env={
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_UPDATE_MODE": "live",
            "WUD_MAX_WAIT": "0",
        },
    )
    client = fixture.client
    compose_dir = fixture.compose_dir
    headers = _csrf_headers(client)

    plan = _create_retag_plan(client, headers)

    assert plan["status"] == "ready"
    assert plan["can_apply"] is True
    assert plan["selected_count"] == 1
    assert plan["external_recreate_required"] is False
    assert plan["stacks"][0]["services"] == ["app"]
    assert plan["stacks"][0]["digest_pin_updates"][0]["resolved_tag"] == "2.0"

    apply_response = _apply_retag_plan(client, headers, plan)

    assert apply_response.status_code == 202
    job = _wait_apply_job(client, apply_response.json()["job_id"])
    assert job["status"] == "success"
    content = (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")
    assert "# wudup.resolved-tag=2.0" in content
    assert "image: repo/app@sha256:old" in content
    assert "wud.tag.include=^2\\.0$$" in content
    calls = _fake_docker_calls(fixture.fake_root)
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
    fixture = _make_retag_fixture(
        tmp_path,
        env={
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    client = fixture.client
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
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fixture.fake_root))


def test_retag_plan_sanitizes_compose_preview_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _make_retag_fixture(tmp_path)
    headers = _csrf_headers(fixture.client)

    def fail_preview(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(f"invalid compose at {tmp_path}/secret/docker-compose.yml")

    monkeypatch.setattr(
        web_retags_module,
        "render_compose_digest_pins",
        fail_preview,
    )

    response = fixture.client.post(
        "/api/v1/retag-plans",
        json={"choices": [_switch_choice()]},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    message = body["issues"][0]["message"]
    assert "Could not safely preview retag for stack/app" in message
    assert "[REDACTED_PATH]" in message
    assert str(tmp_path) not in message


def test_retag_apply_rejects_stale_plan(tmp_path: Path) -> None:
    fixture = _make_retag_fixture(
        tmp_path,
        env={
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    client = fixture.client
    compose_dir = fixture.compose_dir
    headers = _csrf_headers(client)
    plan = _create_retag_plan(client, headers)
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
            "choices": [_switch_choice()],
            "confirmation": "apply-retags",
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "retag plan is stale"


def test_retag_apply_cleans_up_job_when_executor_submit_fails(
    tmp_path: Path,
) -> None:
    fixture = _make_retag_fixture(
        tmp_path,
        env={
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    client = fixture.client
    headers = _csrf_headers(client)
    plan = _create_retag_plan(client, headers)

    class FailingExecutor:
        def submit(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("queue failed")

    client.app.state.web_apply_executor = FailingExecutor()

    with pytest.raises(RuntimeError, match="queue failed"):
        client.post(
            "/api/v1/retag-plans/apply",
            json={
                "plan_id": plan["plan_id"],
                "choices": [_switch_choice()],
                "confirmation": "apply-retags",
            },
            headers=headers,
        )

    assert client.app.state.web_apply_jobs == {}


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
    fixture = _make_retag_fixture(
        tmp_path,
        env={
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_UPDATE_MODE": "live",
            "WUD_MAX_WAIT": "0",
        },
    )
    client = fixture.client
    compose_dir = fixture.compose_dir
    (fixture.fake_root / "stacks" / "stack" / "pull_fail").write_text(
        "pull failed\n",
        encoding="utf-8",
    )
    before = (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")
    headers = _csrf_headers(client)
    plan = _create_retag_plan(client, headers)

    response = _apply_retag_plan(client, headers, plan)

    assert response.status_code == 202
    job = _wait_apply_job(client, response.json()["job_id"])
    assert job["status"] == "failure"
    assert (compose_dir / "docker-compose.yml").read_text(encoding="utf-8") == before
    calls = _fake_docker_calls(fixture.fake_root)
    assert "compose -f docker-compose.yml pull app" in calls
    assert "compose -f docker-compose.yml up -d --remove-orphans --force-recreate --no-deps app" in calls
    run = _wait_run_status(
        tmp_path / "state" / "wud.sqlite",
        job["run_id"],
        "failure",
    )
    assert run["status"] == "failure"


def test_retag_apply_marks_job_failed_before_failure_audit_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _make_retag_fixture(
        tmp_path,
        env={
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_UPDATE_MODE": "live",
            "WUD_MAX_WAIT": "0",
        },
    )
    (fixture.fake_root / "stacks" / "stack" / "pull_fail").write_text(
        "pull failed\n",
        encoding="utf-8",
    )
    headers = _csrf_headers(fixture.client)
    plan = _create_retag_plan(fixture.client, headers)
    original_finish = web_retags_module._finish_retag_audit_run

    def fail_failure_finish(*args: object, **kwargs: object) -> None:
        if kwargs.get("status") == "failure":
            raise RuntimeError("audit finalization failed")
        original_finish(*args, **kwargs)

    monkeypatch.setattr(
        web_retags_module,
        "_finish_retag_audit_run",
        fail_failure_finish,
    )

    response = _apply_retag_plan(fixture.client, headers, plan)

    assert response.status_code == 202
    job = _wait_apply_job(fixture.client, response.json()["job_id"])
    assert job["status"] == "failure"
    assert job["error"]


def test_retag_apply_records_partial_stack_success_when_later_stack_fails(
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
    alpha_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "alpha",
        [("app", "repo/alpha@sha256:old", "cid-alpha")],
    )
    bravo_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "bravo",
        [("app", "repo/bravo@sha256:old", "cid-bravo")],
    )
    _write_compose(
        alpha_dir,
        "app",
        "repo/alpha@sha256:old",
        label_value="^latest$$",
    )
    _write_compose(
        bravo_dir,
        "app",
        "repo/bravo@sha256:old",
        label_value="^latest$$",
    )
    _seed_known_image(
        tmp_path,
        service_key="alpha/app",
        image="repo/alpha@sha256:old",
        source_image="repo/alpha:latest",
        resolved_tag="2.0",
        watch_tag="latest",
        target_digest="sha256:old",
        final_image="repo/alpha@sha256:old",
    )
    _seed_known_image(
        tmp_path,
        service_key="bravo/app",
        image="repo/bravo@sha256:old",
        source_image="repo/bravo:latest",
        resolved_tag="3.0",
        watch_tag="latest",
        target_digest="sha256:old",
        final_image="repo/bravo@sha256:old",
    )
    (fake_root / "stacks" / "bravo" / "pull_fail").write_text(
        "pull failed\n",
        encoding="utf-8",
    )
    bravo_before = (bravo_dir / "docker-compose.yml").read_text(encoding="utf-8")
    headers = _csrf_headers(client)
    choices = [
        {"service_key": "alpha/app", "choice": "switch-to-concrete"},
        {"service_key": "bravo/app", "choice": "switch-to-concrete"},
    ]
    plan = client.post(
        "/api/v1/retag-plans",
        json={"choices": choices},
        headers=headers,
    ).json()

    response = client.post(
        "/api/v1/retag-plans/apply",
        json={
            "plan_id": plan["plan_id"],
            "choices": choices,
            "confirmation": "apply-retags",
        },
        headers=headers,
    )

    assert response.status_code == 202
    job = _wait_apply_job(client, response.json()["job_id"])
    assert job["status"] == "failure"
    assert "wud.tag.include=^2\\.0$$" in (
        alpha_dir / "docker-compose.yml"
    ).read_text(encoding="utf-8")
    assert (bravo_dir / "docker-compose.yml").read_text(
        encoding="utf-8"
    ) == bravo_before
    db_path = tmp_path / "state" / "wud.sqlite"
    run = _wait_run_status(db_path, job["run_id"], "failure")
    with open_db(db_path) as conn:
        events = conn.execute(
            """
            SELECT stack_name, service_name, status, digest_provenance_confidence
            FROM update_events
            WHERE run_id = ?
            ORDER BY stack_name, service_name
            """,
            (job["run_id"],),
        ).fetchall()
        known = conn.execute(
            """
            SELECT service_key, digest_provenance_source, digest_watch_tag
            FROM known_images
            WHERE service_key IN ('alpha/app', 'bravo/app')
            ORDER BY service_key
            """
        ).fetchall()
    assert run["status"] == "failure"
    assert [
        (
            row["stack_name"],
            row["service_name"],
            row["status"],
            row["digest_provenance_confidence"],
        )
        for row in events
    ] == [
        ("alpha", "app", "success", "verified"),
        ("bravo", "app", "failure", "planned"),
    ]
    assert [
        (
            row["service_key"],
            row["digest_provenance_source"],
            row["digest_watch_tag"],
        )
        for row in known
    ] == [
        ("alpha/app", "retag", "2.0"),
        ("bravo/app", "apply", "latest"),
    ]


def test_retag_apply_redacts_rollback_failure_paths(tmp_path: Path) -> None:
    fixture = _make_retag_fixture(
        tmp_path,
        env={
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_UPDATE_MODE": "live",
            "WUD_MAX_WAIT": "0",
        },
    )
    client = fixture.client
    (fixture.fake_root / "stacks" / "stack" / "up_fail").write_text(
        "up failed\n",
        encoding="utf-8",
    )
    headers = _csrf_headers(client)
    plan = _create_retag_plan(client, headers)

    response = _apply_retag_plan(client, headers, plan)

    assert response.status_code == 202
    job = _wait_apply_job(client, response.json()["job_id"])
    assert job["status"] == "failure"
    visible_error = " ".join(
        [
            job["error"],
            *[item["message"] for item in job["progress"]],
        ]
    )
    assert "backup retained at" in visible_error
    assert "[REDACTED_PATH]" in visible_error
    assert str(tmp_path) not in visible_error


def test_retag_apply_unpauses_before_rollback_when_pause_mode_up_fails(
    tmp_path: Path,
) -> None:
    fixture = _make_retag_fixture(
        tmp_path,
        env={
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_UPDATE_MODE": "pause",
            "WUD_MAX_WAIT": "0",
        },
    )
    client = fixture.client
    compose_dir = fixture.compose_dir
    (fixture.fake_root / "stacks" / "stack" / "up_fail").write_text(
        "up failed\n",
        encoding="utf-8",
    )
    before = (compose_dir / "docker-compose.yml").read_text(encoding="utf-8")
    headers = _csrf_headers(client)
    plan = _create_retag_plan(client, headers)

    response = _apply_retag_plan(client, headers, plan)

    assert response.status_code == 202
    job = _wait_apply_job(client, response.json()["job_id"])
    assert job["status"] == "failure"
    assert (compose_dir / "docker-compose.yml").read_text(encoding="utf-8") == before
    calls = _fake_docker_calls(fixture.fake_root).splitlines()
    up_call = "compose -f docker-compose.yml up -d --remove-orphans --force-recreate --no-deps app"

    def call_index(needle: str, *, start: int = 0) -> int:
        return next(
            index for index, call in enumerate(calls[start:], start) if needle in call
        )

    pause = call_index("compose -f docker-compose.yml pause app")
    first_up = call_index(up_call)
    unpause = call_index("compose -f docker-compose.yml unpause app")
    rollback_up = call_index(up_call, start=first_up + 1)
    assert pause < first_up < unpause < rollback_up


def _patch_github_latest(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tag: str,
    url: str,
    extra: dict[str, object] | None = None,
) -> None:
    responses = {
        "https://api.github.com/repos/acme/app/releases/latest": {
            "tag_name": tag,
            "name": tag,
            "html_url": url,
            "body": "Routine update",
            "published_at": "2026-01-02T00:00:00Z",
        },
        "https://api.github.com/repos/linuxserver/docker-radarr/releases/latest": {
            "tag_name": tag,
            "name": tag,
            "html_url": url,
            "body": "Remote Changes:\n- Updating to v5.1.0",
            "published_at": "2026-01-02T00:00:00Z",
        },
        **(extra or {}),
    }

    class FakeGitHubClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            # Test double accepts production constructor arguments but needs no setup.
            pass

        def get_json(self, request_url: str) -> object:
            return responses[request_url]

    monkeypatch.setattr(web_retags_module, "GitHubClient", FakeGitHubClient)


def _patch_digest_resolution(
    monkeypatch: pytest.MonkeyPatch,
    *,
    expected_image: str,
    digest: str,
) -> None:
    class FakeDigestVerifier:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            # Test double accepts production constructor arguments but needs no setup.
            pass

        def resolve_tag_digest(self, image: str) -> DigestResolveResult:
            assert image == expected_image
            return DigestResolveResult(
                ok=True,
                status="resolved",
                reason="tag-digest-resolved",
                digest=digest,
                source="test",
            )

    monkeypatch.setattr(web_retags_module, "DigestVerifier", FakeDigestVerifier)


def _patch_digest_resolution_map(
    monkeypatch: pytest.MonkeyPatch,
    digests_by_image: dict[str, str],
) -> None:
    class FakeDigestVerifier:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            # Test double accepts production constructor arguments but needs no setup.
            pass

        def resolve_tag_digest(self, image: str) -> DigestResolveResult:
            return DigestResolveResult(
                ok=True,
                status="resolved",
                reason="tag-digest-resolved",
                digest=digests_by_image[image],
                source="test",
            )

    monkeypatch.setattr(web_retags_module, "DigestVerifier", FakeDigestVerifier)


def _patch_digest_resolution_results(
    monkeypatch: pytest.MonkeyPatch,
    results_by_image: dict[str, DigestResolveResult],
) -> None:
    class FakeDigestVerifier:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            # Test double accepts production constructor arguments but needs no setup.
            pass

        def resolve_tag_digest(self, image: str) -> DigestResolveResult:
            return results_by_image[image]

    monkeypatch.setattr(web_retags_module, "DigestVerifier", FakeDigestVerifier)


def _wait_retag_preview_job(
    client: TestClient,
    preview_job_id: str,
) -> dict[str, object]:
    deadline = time.time() + 5
    last_status = None
    while time.time() < deadline:
        response = client.get(f"/api/v1/retag-plans/preview/{preview_job_id}")
        assert response.status_code == 200
        body = response.json()
        last_status = body["status"]
        if last_status in {"success", "failure"}:
            return body
        time.sleep(0.02)
    raise AssertionError(
        f"retag preview job {preview_job_id} did not finish; "
        f"last status was {last_status}"
    )


def _make_retag_fixture(
    tmp_path: Path,
    *,
    env: dict[str, str] | None = None,
    image: str = "repo/app@sha256:old",
    label_value: str = "^latest$$",
) -> _RetagFixture:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            **(env or {}),
            **fake_env,
        },
    )
    compose_dir = _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [("app", image, "cid-app")],
    )
    _write_compose(
        compose_dir,
        "app",
        image,
        label_value=label_value,
    )
    _seed_known_image(
        tmp_path,
        service_key="stack/app",
        image=image,
        source_image="repo/app:latest",
        resolved_tag="2.0",
        watch_tag="latest",
        target_digest="sha256:old",
        final_image="repo/app@sha256:old",
    )
    return _RetagFixture(client=client, compose_dir=compose_dir, fake_root=fake_root)


def _switch_choice(service_key: str = "stack/app") -> dict[str, str]:
    return {"service_key": service_key, "choice": "switch-to-concrete"}


def _create_retag_plan(
    client: TestClient,
    headers: dict[str, str],
    choices: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/retag-plans",
        json={"choices": choices if choices is not None else [_switch_choice()]},
        headers=headers,
    )
    assert response.status_code == 200
    return response.json()


def _apply_retag_plan(
    client: TestClient,
    headers: dict[str, str],
    plan: dict[str, object],
    choices: list[dict[str, str]] | None = None,
) -> Response:
    return client.post(
        "/api/v1/retag-plans/apply",
        json={
            "plan_id": plan["plan_id"],
            "choices": choices if choices is not None else [_switch_choice()],
            "confirmation": "apply-retags",
        },
        headers=headers,
    )


def _wait_run_status(
    db_path: Path,
    run_id: object,
    status: str,
) -> sqlite3.Row:
    deadline = time.time() + 5
    last_status = None
    while time.time() < deadline:
        with open_db(db_path) as conn:
            row = conn.execute(
                "SELECT status FROM update_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is not None:
            last_status = row["status"]
            if last_status == status:
                return row
        time.sleep(0.02)
    raise AssertionError(
        f"run {run_id} did not reach status {status}; last status was {last_status}"
    )


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

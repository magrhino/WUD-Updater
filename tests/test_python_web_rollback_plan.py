from __future__ import annotations

from pathlib import Path

import pytest

from wudup import web_rollback
from wudup.compose import ComposeDiscoveryError
from wudup.db import init_db, insert_update_event, insert_update_run, open_db
from tests.web_test_helpers import (
    _client,
    _fake_docker_calls,
    _fake_docker_env,
    _fake_image_state_file,
    _make_fake_stack,
)


OLD_DIGEST = f"sha256:{'a' * 64}"
OLD_IMAGE_ID = "sha256:old-image"
NEW_IMAGE_ID = "sha256:new-image"


def _insert_update(
    tmp_path: Path,
    *,
    dry_run: bool = False,
    mode: str = "stop",
    event_status: str = "success",
    image: str = "repo/app:1.0",
    target_image: str = "repo/app:2.0",
    old_image_id: str = OLD_IMAGE_ID,
    new_image_id: str = NEW_IMAGE_ID,
    old_digest: str = OLD_DIGEST,
    stack_name: str = "stack",
    service_name: str = "app",
) -> int:
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        init_db(conn)
        run_id = insert_update_run(
            conn,
            status="success",
            dry_run=dry_run,
            mode=mode,
        )
        insert_update_event(
            conn,
            run_id=run_id,
            service_name=service_name,
            stack_name=stack_name,
            image=image,
            target_image=target_image,
            old_image_id=old_image_id,
            new_image_id=new_image_id,
            old_digest=old_digest,
            new_digest=f"sha256:{'b' * 64}",
            status=event_status,
        )
    return run_id


def _live_client(tmp_path: Path):
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    return client, fake_root


def _write_live_service(
    tmp_path: Path,
    fake_root: Path,
    *,
    service: str = "app",
    image: str = "repo/app:2.0",
    container_ids: tuple[str, ...] = ("cid-app",),
    current_image_ids: tuple[str, ...] = (NEW_IMAGE_ID,),
) -> None:
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [(service, image, container_ids[0])],
    )
    stack_state = fake_root / "stacks" / "stack"
    if len(container_ids) > 1:
        (stack_state / f"cids-{service}.txt").write_text(
            "".join(f"{container_id}\n" for container_id in container_ids),
            encoding="utf-8",
        )
        (stack_state / "cids.txt").write_text(
            "".join(f"{container_id}\n" for container_id in container_ids),
            encoding="utf-8",
        )
    for container_id, image_id in zip(container_ids, current_image_ids, strict=True):
        (fake_root / "containers" / f"{container_id}.summary").write_text(
            f"/{container_id}|running|healthy|0|0\n",
            encoding="utf-8",
        )
        (fake_root / "containers" / f"{container_id}.image-id").write_text(
            f"{image_id}\n",
            encoding="utf-8",
        )


def _write_local_rollback_image(fake_root: Path) -> None:
    rollback_image = f"repo/app@{OLD_DIGEST}"
    _fake_image_state_file(fake_root, rollback_image, "id").write_text(
        f"{OLD_IMAGE_ID}\n",
        encoding="utf-8",
    )


def _assert_read_only_calls(calls: str) -> None:
    for mutation in (
        " pull ",
        " tag ",
        " up ",
        " down ",
        " stop ",
        " restart ",
        " pause ",
        " unpause ",
    ):
        assert mutation not in f" {calls} "


def test_rollback_plan_returns_verified_local_target_without_mutation(
    tmp_path: Path,
) -> None:
    client, fake_root = _live_client(tmp_path)
    run_id = _insert_update(tmp_path)
    _write_live_service(tmp_path, fake_root)
    _write_local_rollback_image(fake_root)

    response = client.get(f"/api/v1/runs/{run_id}/rollback-plan")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["ready_count"] == 1
    assert body["blocked_count"] == 0
    item = body["items"][0]
    assert item == {
        "event_id": item["event_id"],
        "service_key": "stack/app",
        "stack_name": "stack",
        "service_name": "app",
        "status": "ready",
        "reason": "Current and previous image state was verified from Docker and Compose.",
        "recorded_previous_image": "repo/app:1.0",
        "recorded_target_image": "repo/app:2.0",
        "rollback_image": f"repo/app@{OLD_DIGEST}",
        "previous_image_id": OLD_IMAGE_ID,
        "previous_digest": OLD_DIGEST,
        "current_compose_image": "repo/app:2.0",
        "current_container_image_ids": [NEW_IMAGE_ID],
    }
    calls = _fake_docker_calls(fake_root)
    assert "compose -f docker-compose.yml ps -q app" in calls
    assert "inspect cid-app" in calls
    assert f"image inspect repo/app@{OLD_DIGEST}" in calls
    _assert_read_only_calls(calls)


def test_rollback_plan_requires_authentication(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/v1/runs/1/rollback-plan")

    assert response.status_code == 403
    assert response.json()["detail"] == "setup required"


def test_rollback_plan_returns_not_found_for_missing_run(tmp_path: Path) -> None:
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get("/api/v1/runs/99/rollback-plan")

    assert response.status_code == 404
    assert response.json() == {"detail": "run not found"}


@pytest.mark.parametrize(
    ("dry_run", "mode", "expected_detail"),
    [
        (True, "stop", "Dry runs do not change services"),
        (False, "web-state", "not an updater apply run"),
    ],
)
def test_rollback_plan_skips_non_applicable_runs_without_docker(
    tmp_path: Path,
    dry_run: bool,
    mode: str,
    expected_detail: str,
) -> None:
    client, fake_root = _live_client(tmp_path)
    run_id = _insert_update(tmp_path, dry_run=dry_run, mode=mode)

    response = client.get(f"/api/v1/runs/{run_id}/rollback-plan")

    assert response.status_code == 200
    assert response.json()["status"] == "not_applicable"
    assert expected_detail in response.json()["detail"]
    assert _fake_docker_calls(fake_root) == ""


def test_rollback_plan_marks_no_change_without_live_service_lookup(
    tmp_path: Path,
) -> None:
    client, fake_root = _live_client(tmp_path)
    run_id = _insert_update(
        tmp_path,
        image="repo/app:1.0",
        target_image="repo/app:1.0",
        old_image_id=OLD_IMAGE_ID,
        new_image_id=OLD_IMAGE_ID,
    )

    response = client.get(f"/api/v1/runs/{run_id}/rollback-plan")

    assert response.status_code == 200
    assert response.json()["status"] == "not_needed"
    assert response.json()["not_needed_count"] == 1
    assert " ps -q " not in _fake_docker_calls(fake_root)


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"event_status": "failure"}, "did not complete successfully"),
        ({"old_image_id": ""}, "missing stack, service, image, or image ID"),
        ({"old_digest": "sha256:short"}, "valid exact previous sha256 digest"),
    ],
)
def test_rollback_plan_blocks_failed_or_incomplete_events(
    tmp_path: Path,
    overrides: dict[str, str],
    expected_reason: str,
) -> None:
    client, fake_root = _live_client(tmp_path)
    run_id = _insert_update(tmp_path, **overrides)
    _write_live_service(tmp_path, fake_root)

    response = client.get(f"/api/v1/runs/{run_id}/rollback-plan")

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert expected_reason in response.json()["items"][0]["reason"]
    _assert_read_only_calls(_fake_docker_calls(fake_root))


def test_rollback_plan_blocks_superseded_service(tmp_path: Path) -> None:
    client, fake_root = _live_client(tmp_path)
    run_id = _insert_update(tmp_path)
    later_run_id = _insert_update(tmp_path)
    _write_live_service(tmp_path, fake_root)

    response = client.get(f"/api/v1/runs/{run_id}/rollback-plan")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["status"] == "blocked"
    assert f"run #{later_run_id}" in item["reason"]
    assert " ps -q " not in _fake_docker_calls(fake_root)


@pytest.mark.parametrize(
    ("compose_image", "current_ids", "expected_reason"),
    [
        (
            "repo/app:3.0",
            (NEW_IMAGE_ID,),
            "Compose image no longer matches",
        ),
        (
            "repo/app:2.0",
            (NEW_IMAGE_ID, "sha256:other-image"),
            "running container no longer uses",
        ),
    ],
)
def test_rollback_plan_blocks_live_state_drift(
    tmp_path: Path,
    compose_image: str,
    current_ids: tuple[str, ...],
    expected_reason: str,
) -> None:
    client, fake_root = _live_client(tmp_path)
    run_id = _insert_update(tmp_path)
    container_ids = tuple(f"cid-{index}" for index in range(len(current_ids)))
    _write_live_service(
        tmp_path,
        fake_root,
        image=compose_image,
        container_ids=container_ids,
        current_image_ids=current_ids,
    )
    _write_local_rollback_image(fake_root)

    response = client.get(f"/api/v1/runs/{run_id}/rollback-plan")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["status"] == "blocked"
    assert expected_reason in item["reason"]
    _assert_read_only_calls(_fake_docker_calls(fake_root))


def test_rollback_plan_blocks_previous_image_missing_locally(tmp_path: Path) -> None:
    client, fake_root = _live_client(tmp_path)
    run_id = _insert_update(tmp_path)
    _write_live_service(tmp_path, fake_root)

    response = client.get(f"/api/v1/runs/{run_id}/rollback-plan")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["rollback_image"] == f"repo/app@{OLD_DIGEST}"
    assert item["status"] == "blocked"
    assert "no longer available locally" in item["reason"]


def test_rollback_plan_aggregates_ready_and_blocked_events(tmp_path: Path) -> None:
    client, fake_root = _live_client(tmp_path)
    run_id = _insert_update(tmp_path)
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        insert_update_event(
            conn,
            run_id=run_id,
            service_name="worker",
            stack_name="stack",
            image="repo/worker:1.0",
            target_image="repo/worker:2.0",
            old_image_id="sha256:worker-old",
            new_image_id="sha256:worker-new",
            old_digest=f"sha256:{'c' * 64}",
            status="failure",
        )
    _write_live_service(tmp_path, fake_root)
    _write_local_rollback_image(fake_root)

    response = client.get(f"/api/v1/runs/{run_id}/rollback-plan")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["ready_count"] == 1
    assert body["blocked_count"] == 1


def test_rollback_plan_sanitizes_compose_discovery_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = "rollback-secret"
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_TOKEN": secret,
        },
    )
    run_id = _insert_update(tmp_path)

    def fail_discovery(*_args, **_kwargs):
        raise ComposeDiscoveryError(
            f"could not read {tmp_path / 'docker' / 'compose.yml'} with {secret}"
        )

    monkeypatch.setattr(web_rollback.ComposeCli, "discover_stacks", fail_discovery)

    response = client.get(f"/api/v1/runs/{run_id}/rollback-plan")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert secret not in body["detail"]
    assert str(tmp_path) not in body["detail"]
    assert "<redacted>" in body["detail"]
    assert "[REDACTED_PATH]" in body["detail"]

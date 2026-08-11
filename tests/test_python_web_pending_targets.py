from __future__ import annotations

from pathlib import Path

from tests.web_test_helpers import (
    _assert_pending_grouping_did_not_mutate,
    _client,
    _fake_docker_calls,
    _fake_docker_env,
    _make_fake_stack,
)


def test_update_targets_endpoint_lists_compose_service_images_without_mutation(
    tmp_path: Path,
) -> None:
    fake_env, fake_root = _fake_docker_env(tmp_path)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true", **fake_env})
    _make_fake_stack(
        tmp_path,
        fake_root,
        "stack",
        [
            ("app", "ghcr.io/acme/app:1.0", "cid-app"),
            ("db", "postgres:16@sha256:abc", "cid-db"),
        ],
    )

    response = client.get("/api/v1/update-targets")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["count"] == 2
    assert body["warnings"] == []
    assert [
        (item["service_key"], item["image"], item["image_repo"], item["current_tag"])
        for item in body["items"]
    ] == [
        ("stack/app", "ghcr.io/acme/app:1.0", "acme/app", "1.0"),
        ("stack/db", "postgres:16@sha256:abc", "postgres", "16"),
    ]
    assert all(item["compose_file"] == "docker-compose.yml" for item in body["items"])
    _assert_pending_grouping_did_not_mutate(_fake_docker_calls(fake_root))

from __future__ import annotations

from pathlib import Path

from tests.web_test_helpers import (
    _assert_pending_grouping_did_not_mutate,
    _client,
    _fake_docker_calls,
    _fake_docker_env,
    _make_fake_stack,
)
from wud_updater.db import init_db, open_db, upsert_known_image
from wud_updater.digest_provenance import DigestTagProvenance


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

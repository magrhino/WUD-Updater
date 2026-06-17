from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Optional

from fastapi.testclient import TestClient

from wud_updater.db import (
    open_db,
    init_db,
    insert_update_run,
)
from wud_updater.web import create_app

DEFAULT_CLAIM_PHRASE = " ".join(("correct", "horse", "battery", "staple"))
SSE_EVENT_PREFIX = "event: "
WEB_DB_NAME = "wud.sqlite"


def _web_env(
    tmp_path: Path,
    env: dict[str, str] | None = None,
    *,
    create_root: bool = True,
) -> dict[str, str]:
    root = tmp_path / "state"
    if create_root:
        root.mkdir(exist_ok=True)
    wud_file = root / "images.todo"
    db_path = root / WEB_DB_NAME
    values = {
        "HOME": str(tmp_path),
        "DOCKER_BASE": str(tmp_path / "docker"),
        "WUD_OUT_FILE": str(wud_file),
        "WUD_LOG_DIR": str(root / "logs"),
        "WUD_DB_PATH": str(db_path),
        "WUD_WEB_ALLOWED_HOSTS": "testserver",
    }
    if env:
        values.update(env)
    return values


def _client(
    tmp_path: Path,
    env: dict[str, str] | None = None,
    *,
    create_root: bool = True,
) -> TestClient:
    values = _web_env(tmp_path, env, create_root=create_root)
    return TestClient(create_app(environ=values))


def _doctor_client(
    tmp_path: Path,
    env: dict[str, str] | None = None,
    *,
    client: tuple[str, int] | None = None,
) -> TestClient:
    values = _web_env(
        tmp_path,
        {
            "DOCKER_HOST": "tcp://docker:2375",
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_SYNC_SCRIPTS": "true",
            "WUD_SCRIPTS_DIR": str(tmp_path / "managed-wud"),
            "WUD_APP_DIR": str(tmp_path / "app"),
            "WUD_UPDATER": str(tmp_path / "app" / "bin" / "docker-update-from-wud"),
            "WUD_UPDATER_USE_SUDO": "false",
            "TRUENAS_STATUS_CHECK": "false",
            **(env or {}),
        },
    )
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    values["PATH"] = f"{fake_bin}:{os.environ.get('PATH', '')}"
    _write_doctor_fake_docker(fake_bin / "docker")
    _write_doctor_files(values)
    with open_db(Path(values["WUD_DB_PATH"])) as conn:
        init_db(conn)
    app = create_app(environ=values)
    if client is None:
        return TestClient(app)
    return TestClient(app, client=client)


def _csrf_headers(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return {
        "Origin": "http://testserver",
        "x-wud-csrf-token": response.json()["csrf_token"],
    }


def _self_update_payload(
    *,
    current_tag: str = "v0.24.2",
    latest_tag: str = "v0.25.0",
    target_image: str = "ghcr.io/magrhino/wud-updater:latest",
    restart_container: str = "wud-updater",
) -> dict[str, str]:
    return {
        "confirmation": "pull_image",
        "current_tag": current_tag,
        "latest_tag": latest_tag,
        "target_image": target_image,
        "restart_container": restart_container,
    }


def _setup_admin(
    client: TestClient,
    *,
    username: str = "admin",
    password: Optional[str] = None,
) -> None:
    if password is None:
        password = DEFAULT_CLAIM_PHRASE
    claim = client.app.state.web_setup_claim
    response = client.post(
        "/api/v1/setup/claim",
        json={"claim": claim, "username": username, "password": password},
        headers=_csrf_headers(client),
    )
    assert response.status_code == 200


def _write_doctor_fake_docker(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  --version)
    printf 'Docker version 28.0.0\\n'
    exit 0
    ;;
  version)
    printf 'Server: Docker Engine 28.0.0\\n'
    exit 0
    ;;
  info)
    if [[ -n "${FAKE_DOCKER_INFO_SECRET:-}" ]]; then
      printf 'info failed: %s\\n' "$FAKE_DOCKER_INFO_SECRET" >&2
      exit 17
    fi
    printf 'Docker Root Dir: /var/lib/docker\\n'
    exit 0
    ;;
  ps)
    printf 'CONTAINER ID   IMAGE\\n'
    exit 0
    ;;
  compose)
    if [[ "${2:-}" == "version" ]]; then
      printf 'Docker Compose version v2.30.0\\n'
      exit 0
    fi
    for arg in "$@"; do
      if [[ "$arg" == "json" ]]; then
        printf '{"services":{"app":{"image":"repo/app:latest"}}}\\n'
        exit 0
      fi
    done
    printf 'name: app\\n'
    exit 0
    ;;
esac
printf 'unexpected docker args: %s\\n' "$*" >&2
exit 2
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_doctor_files(env: Mapping[str, str]) -> None:
    docker_base = Path(env["DOCKER_BASE"])
    stack = docker_base / "app"
    stack.mkdir(parents=True)
    (stack / "compose.yml").write_text(
        "services:\n  app:\n    image: repo/app:latest\n",
        encoding="utf-8",
    )
    Path(env["WUD_LOG_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(env["WUD_OUT_FILE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(env["WUD_SCRIPTS_DIR"]).mkdir(parents=True, exist_ok=True)
    app_dir = Path(env["WUD_APP_DIR"])
    packaged_scripts = app_dir / "wud"
    packaged_scripts.mkdir(parents=True)
    for name in (
        "on-update.sh",
        "append-updates.sh",
        "release-parser.sh",
        "release-notes-to-discord.sh",
        "github-release-embed.sh",
        "tag-manager.sh",
    ):
        script = packaged_scripts / name
        script.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
    updater = Path(env["WUD_UPDATER"])
    updater.parent.mkdir(parents=True, exist_ok=True)
    updater.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    updater.chmod(0o755)


def _contains_key(value: object, target: str) -> bool:
    if isinstance(value, dict):
        return target in value or any(
            _contains_key(item, target) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(item, target) for item in value)
    return False


def _assert_generic_auth_failed(response) -> None:
    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}
    assert response.headers["www-authenticate"] == "Bearer"


def _insert_run(tmp_path: Path, *, log_file: str = "") -> int:
    db_path = tmp_path / "state" / WEB_DB_NAME
    with open_db(db_path) as conn:
        init_db(conn)
        return insert_update_run(
            conn,
            started_at="2026-05-27T12:00:00+00:00",
            status="success",
            dry_run=True,
            mode="stop",
            wud_file="/out/images.todo",
            log_file=log_file,
            metadata_json='{"source":"test"}',
        )


def _fake_docker_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    fake_root = tmp_path / "fake-docker"
    for path in (
        fake_root / "images",
        fake_root / "manifests",
        fake_root / "stacks",
        fake_root / "containers",
    ):
        path.mkdir(parents=True, exist_ok=True)
    (fake_root / "containers.tsv").write_text("", encoding="utf-8")
    (fake_root / "calls.log").write_text("", encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    return (
        {
            "DOCKER_HOST": "tcp://docker:2375",
            "FAKE_DOCKER_ROOT": str(fake_root),
            "PATH": f"{repo_root / 'tests' / 'fakes'}:{os.environ['PATH']}",
        },
        fake_root,
    )


def _make_fake_stack(
    tmp_path: Path,
    fake_root: Path,
    stack_id: str,
    services: list[tuple[str, str, str | None]],
    *,
    parent: Path | None = None,
) -> Path:
    directory = (parent or tmp_path / "docker") / stack_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".fake-docker-id").write_text(f"{stack_id}\n", encoding="utf-8")
    stack_state = fake_root / "stacks" / stack_id
    stack_state.mkdir(parents=True, exist_ok=True)

    compose_lines = ["services:\n"]
    service_rows: list[str] = []
    image_rows: list[str] = []
    cids: list[str] = []
    for service, image, cid in services:
        compose_lines.extend([f"  {service}:\n", f"    image: {image}\n"])
        service_rows.append(f"{service}\n")
        image_rows.append(f"{image}\n")
        with (stack_state / "service-images.tsv").open("a", encoding="utf-8") as file:
            file.write(f"{service}\t{image}\n")
        if cid is None:
            continue
        cids.append(cid)
        (stack_state / f"cids-{service}.txt").write_text(
            f"{cid}\n",
            encoding="utf-8",
        )
        (fake_root / "containers" / f"{cid}.summary").write_text(
            f"/{cid}|running|healthy|0|0\n",
            encoding="utf-8",
        )

    (directory / "docker-compose.yml").write_text(
        "".join(compose_lines),
        encoding="utf-8",
    )
    (stack_state / "services.txt").write_text("".join(service_rows), encoding="utf-8")
    (stack_state / "images.txt").write_text("".join(image_rows), encoding="utf-8")
    (stack_state / "cids.txt").write_text(
        "".join(f"{cid}\n" for cid in cids),
        encoding="utf-8",
    )
    return directory


def _write_fake_container_labels(
    fake_root: Path,
    container_id: str,
    labels: dict[str, str],
) -> None:
    (fake_root / "containers" / f"{container_id}.labels").write_text(
        "".join(f"{key}={value}\n" for key, value in labels.items()),
        encoding="utf-8",
    )


def _fake_docker_calls(fake_root: Path) -> str:
    return (fake_root / "calls.log").read_text(encoding="utf-8")


def _assert_pending_grouping_did_not_mutate(calls: str) -> None:
    assert "manifest inspect" not in calls
    assert " pull " not in calls
    assert " stop " not in calls
    assert " up " not in calls


def _fake_image_state_file(fake_root: Path, image: str, suffix: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", image)
    return fake_root / "images" / f"{safe}.{suffix}"


def _fake_manifest_file(fake_root: Path, image: str, suffix: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", image)
    return fake_root / "manifests" / f"{safe}.{suffix}"


def _write_fake_manifest(fake_root: Path, image: str, payload: object) -> None:
    _fake_manifest_file(fake_root, image, "stdout").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _write_fake_image_after_pull(
    fake_root: Path,
    image: str,
    image_id: str,
    digest: str,
) -> None:
    _fake_image_state_file(fake_root, image, "after_id").write_text(
        image_id,
        encoding="utf-8",
    )
    _fake_image_state_file(fake_root, image, "after_digests").write_text(
        f"{image}@{digest}\n",
        encoding="utf-8",
    )


def _manifest_index_digest(digest: str, *children: str) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "Descriptor": {"digest": digest},
        "manifests": [
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": child,
                "platform": {"os": "linux", "architecture": "amd64"},
            }
            for child in children
        ],
    }


def _wait_apply_job(client: TestClient, job_id: str) -> dict[str, object]:
    deadline = time.time() + 5
    while time.time() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] not in {"queued", "running"}:
            return body
        time.sleep(0.02)
    raise AssertionError(f"apply job {job_id} did not finish")


def _sse_events(content: str, expected_name: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in content.split("\n\n"):
        event_name = ""
        data: list[str] = []
        for line in block.splitlines():
            if line.startswith(SSE_EVENT_PREFIX):
                event_name = line.removeprefix(SSE_EVENT_PREFIX)
            elif line.startswith("data: "):
                data.append(line.removeprefix("data: "))
        if event_name == expected_name and data:
            events.append(json.loads("\n".join(data)))
    return events


def _sse_event_names(content: str) -> list[str]:
    names: list[str] = []
    for block in content.split("\n\n"):
        for line in block.splitlines():
            if line.startswith(SSE_EVENT_PREFIX):
                names.append(line.removeprefix(SSE_EVENT_PREFIX))
                break
    return names


def _sse_job_events(content: str) -> list[dict[str, object]]:
    return _sse_events(content, "job")


def _sse_log_events(content: str) -> list[dict[str, object]]:
    return _sse_events(content, "log")


def _sse_progress_events(content: str) -> list[dict[str, object]]:
    return _sse_events(content, "progress")



def _store_web_setting(tmp_path: Path, key: str, value: str) -> None:
    with open_db(tmp_path / "state" / WEB_DB_NAME) as conn:
        init_db(conn)
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO web_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, "2026-06-08T00:00:00+00:00"),
            )

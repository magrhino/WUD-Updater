#!/usr/bin/env python3
"""Create disposable local demo state for WebUI development."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from wud_updater.db import (  # noqa: E402
    connect_db,
    init_db,
    insert_snooze,
    insert_pending_update,
    insert_update_event,
    insert_update_run,
    upsert_known_image,
    upsert_tag_exclusion_rule,
)


PENDING_LINES = (
    "# Demo WUD pending update file for local WebUI development.",
    "ghcr.io/home-assistant/home-assistant:2026.5.1 tag=2026.5.3",
    "lscr.io/linuxserver/radarr:5.21.1 tag=5.22.4",
    "postgres:16@sha256:1111111111111111111111111111111111111111111111111111111111111111",
    "ghcr.io/magrhino/wud-updater:v0.16.0 tag=v0.16.1",
    "ghcr.io/gethomepage/homepage:v0.9.12 tag=v0.10.9",
    "vaultwarden/server:1.31.0 tag=1.32.0",
    "containrrr/watchtower:1.7.1 tag=1.7.2",
)

DEMO_STACKS = (
    {
        "name": "home",
        "services": (
            ("home-assistant", "ghcr.io/home-assistant/home-assistant:2026.5.1"),
        ),
    },
    {
        "name": "media",
        "services": (
            ("radarr", "lscr.io/linuxserver/radarr:5.21.1"),
            ("wud-updater", "ghcr.io/magrhino/wud-updater:v0.16.0"),
        ),
    },
    {
        "name": "data",
        "services": (
            ("postgres", "postgres:16"),
        ),
    },
)

DEMO_UNMATCHED_CONTAINERS = (
    ("homepage", "ghcr.io/gethomepage/homepage:v0.9.12"),
    ("vaultwarden", "vaultwarden/server:1.31.0"),
    ("watchtower", "containrrr/watchtower:1.7.1"),
)

DEMO_CONTAINER_LABELS = {
    "cid-data-postgres": {
        "WUD-UPDATER-RECREATE-STACK": "true",
    },
}

DEMO_PULL_TARGETS = (
    (
        "ghcr.io/home-assistant/home-assistant:2026.5.3",
        "sha256:demo-home-assistant-new",
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ),
    (
        "lscr.io/linuxserver/radarr:5.22.4",
        "sha256:demo-radarr-new",
        "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    ),
    (
        "postgres:16",
        "sha256:demo-postgres-new",
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
    ),
    (
        "ghcr.io/magrhino/wud-updater:v0.16.1",
        "sha256:demo-wud-updater-new",
        "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    ),
)

DEMO_SERVICE_POLICIES = (
    {
        "service_key": "home/home-assistant",
        "update_mode": "live",
        "auto_update": True,
        "snooze_default_seconds": None,
        "auto_update_time": "03:30",
        "auto_update_days_json": '["mon","wed","fri"]',
    },
    {
        "service_key": "media/radarr",
        "update_mode": "stop",
        "auto_update": False,
        "snooze_default_seconds": 86400,
        "auto_update_time": None,
        "auto_update_days_json": "[]",
    },
)

DEMO_SNOOZES = (
    {
        "service_key": "media/radarr",
        "snoozed_until": "2099-01-01T00:00:00+00:00",
        "reason": "demo maintenance window",
        "created_at": "2026-05-28T12:00:00+00:00",
    },
    {
        "service_key": "data/postgres",
        "snoozed_until": "2020-01-01T00:00:00+00:00",
        "reason": "expired demo snooze",
        "created_at": "2020-01-01T00:00:00+00:00",
    },
)

DEMO_TAG_EXCLUSIONS = (
    {
        "scope": "image_repo",
        "image_repo": "ghcr.io/home-assistant/home-assistant",
        "service_key": "",
        "tag": "2026.5.3",
        "status": "active",
    },
    {
        "scope": "service",
        "image_repo": "lscr.io/linuxserver/radarr",
        "service_key": "media/radarr",
        "tag": "5.22.4",
        "status": "disabled",
    },
)

RUNS = (
    {
        "started_at": "2026-05-28T12:12:00+00:00",
        "finished_at": "2026-05-28T12:13:41+00:00",
        "status": "success",
        "dry_run": False,
        "mode": "stop",
        "log": "demo-success.log",
        "metadata": {"source": "demo", "summary": "updated two services"},
        "pending": (
            {
                "line_no": 1,
                "raw": "lscr.io/linuxserver/sonarr:4.0.14 tag=4.0.15",
                "image": "lscr.io/linuxserver/sonarr:4.0.14",
                "desired_tag": "4.0.15",
                "service_key": "media/sonarr",
                "stack_name": "media",
                "service_name": "sonarr",
                "status": "success",
                "status_reason": "container recreated and healthy",
            },
            {
                "line_no": 2,
                "raw": "redis:7.2 tag=7.4",
                "image": "redis:7.2",
                "desired_tag": "7.4",
                "service_key": "infra/redis",
                "stack_name": "infra",
                "service_name": "redis",
                "status": "success",
                "status_reason": "service updated",
            },
        ),
        "events": (
            {
                "service_name": "sonarr",
                "stack_name": "media",
                "image": "lscr.io/linuxserver/sonarr:4.0.14",
                "target_image": "lscr.io/linuxserver/sonarr:4.0.15",
                "status": "success",
                "old_digest": "sha256:sonarr-old",
                "new_digest": "sha256:sonarr-new",
            },
            {
                "service_name": "redis",
                "stack_name": "infra",
                "image": "redis:7.2",
                "target_image": "redis:7.4",
                "status": "success",
                "old_digest": "sha256:redis-old",
                "new_digest": "sha256:redis-new",
            },
        ),
        "log_content": """[2026-05-28T12:12:00+00:00] docker-update-from-wud-v2
[2026-05-28T12:12:02+00:00] Found 2 matching services.
[2026-05-28T12:12:38+00:00] [media/sonarr] Recreated container and health check passed.
[2026-05-28T12:13:40+00:00] [infra/redis] Recreated container and health check passed.
[2026-05-28T12:13:41+00:00] Done.
""",
    },
    {
        "started_at": "2026-05-28T10:04:00+00:00",
        "finished_at": "2026-05-28T10:05:09+00:00",
        "status": "failed",
        "dry_run": False,
        "mode": "pause",
        "log": "demo-failed.log",
        "metadata": {"source": "demo", "summary": "health check failed"},
        "pending": (
            {
                "line_no": 1,
                "raw": "ghcr.io/example/api:2.8.0 tag=2.9.0",
                "image": "ghcr.io/example/api:2.8.0",
                "desired_tag": "2.9.0",
                "service_key": "apps/api",
                "stack_name": "apps",
                "service_name": "api",
                "status": "failed",
                "status_reason": "container health check timed out",
            },
        ),
        "events": (
            {
                "service_name": "api",
                "stack_name": "apps",
                "image": "ghcr.io/example/api:2.8.0",
                "target_image": "ghcr.io/example/api:2.9.0",
                "status": "failed",
                "old_digest": "sha256:api-old",
                "new_digest": "sha256:api-new",
            },
        ),
        "log_content": """[2026-05-28T10:04:00+00:00] docker-update-from-wud-v2
[2026-05-28T10:04:06+00:00] [apps/api] Pull complete.
[2026-05-28T10:04:32+00:00] [apps/api] Container recreated.
[2026-05-28T10:05:09+00:00] [apps/api] Health check timed out; leaving WUD line pending.
""",
    },
    {
        "started_at": "2026-05-27T22:45:00+00:00",
        "finished_at": "2026-05-27T22:45:12+00:00",
        "status": "success",
        "dry_run": True,
        "mode": "live",
        "log": "demo-dry-run.log",
        "metadata": {"source": "demo", "summary": "dry-run plan"},
        "pending": (
            {
                "line_no": 1,
                "raw": "nginx:1.25 tag=1.27",
                "image": "nginx:1.25",
                "desired_tag": "1.27",
                "service_key": "edge/nginx",
                "stack_name": "edge",
                "service_name": "nginx",
                "status": "planned",
                "status_reason": "dry-run only",
            },
        ),
        "events": (),
        "log_content": """[2026-05-27T22:45:00+00:00] docker-update-from-wud-v2
[2026-05-27T22:45:01+00:00] Dry-run: would update edge/nginx from nginx:1.25 to nginx:1.27.
[2026-05-27T22:45:12+00:00] Dry-run completed without mutation.
""",
    },
    {
        "started_at": "2026-05-30T19:20:00+00:00",
        "finished_at": "2026-05-30T19:20:00+00:00",
        "status": "success",
        "dry_run": False,
        "mode": "web-auth",
        "log": "",
        "metadata": {
            "source": "webui",
            "operation": "reset_admin_password",
            "actor_type": "reset_claim",
            "resource_type": "web_user",
            "resource_id": "admin",
            "target": {"username": "admin"},
        },
        "pending": (),
        "events": (
            {
                "service_name": "admin",
                "stack_name": "webui",
                "image": "web_user",
                "target_image": "admin",
                "status": "success",
                "old_digest": "",
                "new_digest": "",
                "metadata": {"source": "webui"},
            },
        ),
        "log_content": "",
    },
    {
        "started_at": "2026-05-30T19:50:00+00:00",
        "finished_at": "2026-05-30T19:50:00+00:00",
        "status": "success",
        "dry_run": False,
        "mode": "web-state",
        "log": "",
        "metadata": {
            "source": "webui",
            "operation": "upsert_service_policy",
            "actor_type": "browser",
            "resource_type": "service_policy",
            "resource_id": "media/radarr",
            "service_key": "media/radarr",
            "target": {"service_key": "media/radarr"},
        },
        "pending": (),
        "events": (
            {
                "service_name": "radarr",
                "stack_name": "media",
                "image": "service-policy",
                "target_image": "media/radarr",
                "status": "success",
                "old_digest": "",
                "new_digest": "",
                "metadata": {"source": "webui"},
            },
        ),
        "log_content": "",
    },
    {
        "started_at": "2026-05-30T20:20:00+00:00",
        "finished_at": "2026-05-30T20:20:00+00:00",
        "status": "success",
        "dry_run": False,
        "mode": "web-settings",
        "log": "",
        "metadata": {
            "source": "webui",
            "operation": "update_managed_settings",
            "actor_type": "browser",
            "resource_type": "managed_settings",
            "resource_id": "webui_preferences",
            "target": {"keys": ["theme_preference"]},
        },
        "pending": (),
        "events": (
            {
                "service_name": "settings",
                "stack_name": "webui",
                "image": "managed-settings",
                "target_image": "webui-preferences",
                "status": "success",
                "old_digest": "",
                "new_digest": "",
                "metadata": {"source": "webui"},
            },
        ),
        "log_content": "",
    },
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT / "local-dev",
        help="demo state directory, default: local-dev",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    paths = seed_demo_state(args.root)
    if not args.quiet:
        print("Created WebUI demo state:")
        print(f"  DOCKER_BASE={paths['docker_base']}")
        print(f"  FAKE_DOCKER_ROOT={paths['fake_docker_root']}")
        print(f"  WUD_OUT_FILE={paths['wud_file']}")
        print(f"  WUD_LOG_DIR={paths['log_dir']}")
        print(f"  WUD_DB_PATH={paths['db_path']}")
    return 0


def seed_demo_state(root: Path) -> dict[str, Path]:
    root = root.resolve()
    out_dir = root / "out"
    log_dir = root / "logs"
    docker_base = root / "docker"
    fake_docker_root = root / "fake-docker"
    wud_file = out_dir / "images.todo"
    db_path = log_dir / "wud-updater.sqlite"

    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    _reset_directory(docker_base)
    _reset_directory(fake_docker_root)

    wud_file.write_text("\n".join(PENDING_LINES) + "\n", encoding="utf-8")
    for path in log_dir.glob("demo-*.log"):
        path.unlink()
    _reset_sqlite(db_path)
    _write_demo_stacks(docker_base, fake_docker_root)

    with connect_db(db_path) as conn:
        init_db(conn)
        _write_demo_management_state(conn)
        for entry in RUNS:
            log_name = str(entry["log"])
            if log_name:
                log_file = log_dir / log_name
                log_file.write_text(str(entry["log_content"]), encoding="utf-8")
                log_file_label = str(log_file)
            else:
                log_file_label = ""
            run_id = insert_update_run(
                conn,
                started_at=str(entry["started_at"]),
                status=str(entry["status"]),
                dry_run=bool(entry["dry_run"]),
                mode=str(entry["mode"]),
                wud_file=str(wud_file),
                log_file=log_file_label,
                metadata_json=json.dumps(entry["metadata"], sort_keys=True),
            )
            with conn:
                conn.execute(
                    "UPDATE update_runs SET finished_at = ? WHERE id = ?",
                    (entry["finished_at"], run_id),
                )
            for pending in entry["pending"]:
                insert_pending_update(
                    conn,
                    run_id=run_id,
                    line_no=int(pending["line_no"]),
                    raw=str(pending["raw"]),
                    image=str(pending["image"]),
                    desired_tag=str(pending["desired_tag"]),
                    service_key=str(pending["service_key"]),
                    stack_name=str(pending["stack_name"]),
                    service_name=str(pending["service_name"]),
                    status=str(pending["status"]),
                    status_reason=str(pending["status_reason"]),
                    metadata_json='{"source":"demo"}',
                )
                upsert_known_image(
                    conn,
                    service_key=str(pending["service_key"]),
                    image=str(pending["image"]),
                    digest="sha256:demo",
                    metadata_json='{"source":"demo"}',
                )
            for event in entry["events"]:
                insert_update_event(
                    conn,
                    run_id=run_id,
                    service_name=str(event["service_name"]),
                    stack_name=str(event["stack_name"]),
                    image=str(event["image"]),
                    target_image=str(event["target_image"]),
                    status=str(event["status"]),
                    old_digest=str(event["old_digest"]),
                    new_digest=str(event["new_digest"]),
                    metadata_json=json.dumps(
                        event.get("metadata", {"source": "demo"}),
                        sort_keys=True,
                    ),
                )

    return {
        "root": root,
        "out_dir": out_dir,
        "log_dir": log_dir,
        "docker_base": docker_base,
        "fake_docker_root": fake_docker_root,
        "wud_file": wud_file,
        "db_path": db_path,
    }


def _write_demo_management_state(conn) -> None:
    created_at = "2026-05-28T12:00:00+00:00"
    for policy in DEMO_SERVICE_POLICIES:
        with conn:
            conn.execute(
                """
                INSERT INTO service_policy (
                    service_key,
                    update_mode,
                    auto_update,
                    snooze_default_seconds,
                    auto_update_time,
                    auto_update_days_json,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(policy["service_key"]),
                    str(policy["update_mode"]),
                    1 if bool(policy["auto_update"]) else 0,
                    policy["snooze_default_seconds"],
                    policy["auto_update_time"],
                    policy["auto_update_days_json"],
                    created_at,
                    created_at,
                    '{"source":"demo"}',
                ),
            )

    for snooze in DEMO_SNOOZES:
        insert_snooze(
            conn,
            service_key=str(snooze["service_key"]),
            snoozed_until=str(snooze["snoozed_until"]),
            reason=str(snooze["reason"]),
            created_at=str(snooze["created_at"]),
            metadata_json='{"source":"demo"}',
        )

    for rule in DEMO_TAG_EXCLUSIONS:
        tag = str(rule["tag"])
        upsert_tag_exclusion_rule(
            conn,
            scope=str(rule["scope"]),
            image_repo=str(rule["image_repo"]),
            service_key=str(rule["service_key"]),
            tag=tag,
            regex_fragment=re.escape(tag),
            status=str(rule["status"]),
            created_at=created_at,
            updated_at=created_at,
            metadata_json='{"source":"demo"}',
        )


def _reset_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _reset_sqlite(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = Path(f"{db_path}{suffix}")
        if path.exists():
            path.unlink()


def _write_demo_stacks(docker_base: Path, fake_docker_root: Path) -> None:
    for directory in (
        fake_docker_root / "stacks",
        fake_docker_root / "images",
        fake_docker_root / "manifests",
        fake_docker_root / "containers",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    containers: list[str] = []
    for stack in DEMO_STACKS:
        stack_name = str(stack["name"])
        services = tuple(stack["services"])
        stack_dir = docker_base / stack_name
        stack_dir.mkdir(parents=True, exist_ok=True)
        (stack_dir / ".fake-docker-id").write_text(f"{stack_name}\n", encoding="utf-8")
        _write_compose_file(stack_dir / "docker-compose.yml", services)
        _write_fake_stack_state(fake_docker_root, stack_name, services, containers)

    for container_id, labels in DEMO_CONTAINER_LABELS.items():
        _write_fake_container_labels(fake_docker_root, container_id, labels)

    (fake_docker_root / "containers" / "demo-wud-updater.summary").write_text(
        "/demo-wud-updater|running|healthy|0|0\n",
        encoding="utf-8",
    )

    for container_name, image in DEMO_UNMATCHED_CONTAINERS:
        (fake_docker_root / "containers" / f"{container_name}.summary").write_text(
            f"/{container_name}|running|healthy|0|0\n",
            encoding="utf-8",
        )
        containers.append(f"{container_name}\t{image}\n")
        _write_fake_image_state(fake_docker_root, image)

    for image, image_id, digest in DEMO_PULL_TARGETS:
        _write_fake_image_after_pull(
            fake_docker_root,
            image,
            image_id=image_id,
            digest=digest,
        )

    (fake_docker_root / "containers.tsv").write_text(
        "".join(containers),
        encoding="utf-8",
    )
    (fake_docker_root / "calls.log").write_text("", encoding="utf-8")


def _write_compose_file(path: Path, services: tuple[tuple[str, str], ...]) -> None:
    lines = ["services:\n"]
    for service, image in services:
        lines.extend(
            [
                f"  {service}:\n",
                f"    image: {image}\n",
                "    restart: unless-stopped\n",
            ]
        )
    path.write_text("".join(lines), encoding="utf-8")


def _write_fake_stack_state(
    fake_docker_root: Path,
    stack_name: str,
    services: tuple[tuple[str, str], ...],
    containers: list[str],
) -> None:
    stack_state = fake_docker_root / "stacks" / stack_name
    stack_state.mkdir(parents=True, exist_ok=True)
    service_lines: list[str] = []
    image_lines: list[str] = []
    cid_lines: list[str] = []
    service_image_rows: list[str] = []
    for service, image in services:
        cid = f"cid-{stack_name}-{service}"
        service_lines.append(f"{service}\n")
        image_lines.append(f"{image}\n")
        cid_lines.append(f"{cid}\n")
        service_image_rows.append(f"{service}\t{image}\n")
        (stack_state / f"cids-{service}.txt").write_text(f"{cid}\n", encoding="utf-8")
        (fake_docker_root / "containers" / f"{cid}.summary").write_text(
            f"/{cid}|running|healthy|0|0\n",
            encoding="utf-8",
        )
        containers.append(f"{stack_name}-{service}\t{image}\n")
        _write_fake_image_state(fake_docker_root, image)

    (stack_state / "services.txt").write_text("".join(service_lines), encoding="utf-8")
    (stack_state / "images.txt").write_text("".join(image_lines), encoding="utf-8")
    (stack_state / "cids.txt").write_text("".join(cid_lines), encoding="utf-8")
    (stack_state / "service-images.tsv").write_text(
        "".join(service_image_rows),
        encoding="utf-8",
    )


def _write_fake_container_labels(
    fake_docker_root: Path,
    container_id: str,
    labels: dict[str, str],
) -> None:
    (fake_docker_root / "containers" / f"{container_id}.labels").write_text(
        "".join(f"{key}={value}\n" for key, value in labels.items()),
        encoding="utf-8",
    )


def _write_fake_image_state(fake_docker_root: Path, image: str) -> None:
    safe = _safe_fake_name(image)
    image_dir = fake_docker_root / "images"
    digest = f"{image}@sha256:{safe[:12].ljust(12, '0')}"
    (image_dir / f"{safe}.id").write_text(f"sha256:{safe}\n", encoding="utf-8")
    (image_dir / f"{safe}.digests").write_text(f"{digest}\n", encoding="utf-8")


def _write_fake_image_after_pull(
    fake_docker_root: Path,
    image: str,
    *,
    image_id: str,
    digest: str,
) -> None:
    safe = _safe_fake_name(image)
    image_dir = fake_docker_root / "images"
    (image_dir / f"{safe}.after_id").write_text(f"{image_id}\n", encoding="utf-8")
    (image_dir / f"{safe}.after_digests").write_text(
        f"{image}@{digest}\n",
        encoding="utf-8",
    )


def _safe_fake_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


if __name__ == "__main__":
    raise SystemExit(main())

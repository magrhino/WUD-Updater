#!/usr/bin/env python3
"""Create disposable local demo state for WebUI development."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from wud_updater.db import (  # noqa: E402
    connect_db,
    init_db,
    insert_pending_update,
    insert_update_event,
    insert_update_run,
    upsert_known_image,
)


PENDING_LINES = (
    "# Demo WUD pending update file for local WebUI development.",
    "ghcr.io/home-assistant/home-assistant:2026.5.1 tag=2026.5.3",
    "lscr.io/linuxserver/radarr:5.21.1 tag=5.22.4",
    "postgres:16@sha256:1111111111111111111111111111111111111111111111111111111111111111",
    "ghcr.io/magrhino/wud-updater:v0.16.0 tag=v0.16.1",
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
        print(f"  WUD_OUT_FILE={paths['wud_file']}")
        print(f"  WUD_LOG_DIR={paths['log_dir']}")
        print(f"  WUD_DB_PATH={paths['db_path']}")
    return 0


def seed_demo_state(root: Path) -> dict[str, Path]:
    root = root.resolve()
    out_dir = root / "out"
    log_dir = root / "logs"
    docker_base = root / "docker"
    wud_file = out_dir / "images.todo"
    db_path = log_dir / "wud-updater.sqlite"

    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    docker_base.mkdir(parents=True, exist_ok=True)

    wud_file.write_text("\n".join(PENDING_LINES) + "\n", encoding="utf-8")
    for path in log_dir.glob("demo-*.log"):
        path.unlink()
    _reset_sqlite(db_path)

    with connect_db(db_path) as conn:
        init_db(conn)
        for entry in RUNS:
            log_file = log_dir / str(entry["log"])
            log_file.write_text(str(entry["log_content"]), encoding="utf-8")
            run_id = insert_update_run(
                conn,
                started_at=str(entry["started_at"]),
                status=str(entry["status"]),
                dry_run=bool(entry["dry_run"]),
                mode=str(entry["mode"]),
                wud_file=str(wud_file),
                log_file=str(log_file),
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
                    metadata_json='{"source":"demo"}',
                )

    return {
        "root": root,
        "out_dir": out_dir,
        "log_dir": log_dir,
        "docker_base": docker_base,
        "wud_file": wud_file,
        "db_path": db_path,
    }


def _reset_sqlite(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = Path(f"{db_path}{suffix}")
        if path.exists():
            path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())

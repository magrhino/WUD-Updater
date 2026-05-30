from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class WebuiDemoStateTests(unittest.TestCase):
    def test_demo_state_seed_is_idempotent(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script = repo_root / "webui" / "scripts" / "seed_demo_state.py"
        with tempfile.TemporaryDirectory(prefix="wud-webui-demo.") as tmpdir:
            root = Path(tmpdir) / "local-dev"

            for _ in range(2):
                subprocess.run(
                    [sys.executable, str(script), "--root", str(root), "--quiet"],
                    cwd=repo_root,
                    check=True,
                    text=True,
                    capture_output=True,
                )

            wud_file = root / "out" / "images.todo"
            db_path = root / "logs" / "wud-updater.sqlite"
            docker_base = root / "docker"
            fake_docker_root = root / "fake-docker"
            logs = sorted(path.name for path in (root / "logs").glob("demo-*.log"))
            compose_files = sorted(
                path.relative_to(docker_base).as_posix()
                for path in docker_base.glob("*/docker-compose.yml")
            )

            self.assertIn("home-assistant", wud_file.read_text(encoding="utf-8"))
            self.assertEqual(
                logs,
                ["demo-dry-run.log", "demo-failed.log", "demo-success.log"],
            )
            self.assertEqual(
                compose_files,
                [
                    "data/docker-compose.yml",
                    "home/docker-compose.yml",
                    "media/docker-compose.yml",
                ],
            )
            self.assertIn(
                "lscr.io/linuxserver/radarr:5.21.1",
                (docker_base / "media" / "docker-compose.yml").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertTrue((fake_docker_root / "calls.log").exists())
            self.assertTrue((fake_docker_root / "containers.tsv").exists())
            self.assertTrue(
                (
                    fake_docker_root
                    / "images"
                    / "postgres_16.after_digests"
                ).exists()
            )
            self.assertTrue(
                (
                    fake_docker_root
                    / "images"
                    / "lscr.io_linuxserver_radarr_5.22.4.after_id"
                ).exists()
            )
            result = subprocess.run(
                ["docker", "compose", "-f", "docker-compose.yml", "config", "--images"],
                cwd=docker_base / "media",
                env={
                    **os.environ,
                    "PATH": f"{repo_root / 'tests' / 'fakes'}:{os.environ['PATH']}",
                    "FAKE_DOCKER_ROOT": str(fake_docker_root),
                },
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertIn("ghcr.io/magrhino/wud-updater:v0.16.0", result.stdout)
            with sqlite3.connect(db_path) as conn:
                run_count = conn.execute("SELECT COUNT(*) FROM update_runs").fetchone()
                pending_count = conn.execute(
                    "SELECT COUNT(*) FROM pending_updates"
                ).fetchone()
                event_count = conn.execute("SELECT COUNT(*) FROM update_events").fetchone()
                policy_count = conn.execute(
                    "SELECT COUNT(*) FROM service_policy"
                ).fetchone()
                snooze_count = conn.execute("SELECT COUNT(*) FROM snoozes").fetchone()
                tag_exclusion_count = conn.execute(
                    "SELECT COUNT(*) FROM tag_exclusion_rules"
                ).fetchone()
                active_exclusions = conn.execute(
                    """
                    SELECT image_repo, status
                    FROM tag_exclusion_rules
                    WHERE status = 'active'
                    """
                ).fetchall()
                versions = conn.execute(
                    """
                    SELECT status, dry_run, log_file
                    FROM update_runs
                    ORDER BY id
                    """
                ).fetchall()

        self.assertEqual(run_count[0], 3)
        self.assertEqual(pending_count[0], 4)
        self.assertEqual(event_count[0], 3)
        self.assertEqual(policy_count[0], 2)
        self.assertEqual(snooze_count[0], 2)
        self.assertEqual(tag_exclusion_count[0], 2)
        self.assertEqual(
            active_exclusions[0][0],
            "ghcr.io/home-assistant/home-assistant",
        )
        self.assertEqual(versions[0][0], "success")
        self.assertEqual(versions[2][1], 1)
        self.assertTrue(versions[0][2].endswith("demo-success.log"))


if __name__ == "__main__":
    unittest.main()

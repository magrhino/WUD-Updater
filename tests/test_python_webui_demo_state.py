from __future__ import annotations

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
            logs = sorted(path.name for path in (root / "logs").glob("demo-*.log"))

            self.assertIn("home-assistant", wud_file.read_text(encoding="utf-8"))
            self.assertEqual(
                logs,
                ["demo-dry-run.log", "demo-failed.log", "demo-success.log"],
            )
            with sqlite3.connect(db_path) as conn:
                run_count = conn.execute("SELECT COUNT(*) FROM update_runs").fetchone()
                pending_count = conn.execute(
                    "SELECT COUNT(*) FROM pending_updates"
                ).fetchone()
                event_count = conn.execute("SELECT COUNT(*) FROM update_events").fetchone()
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
        self.assertEqual(versions[0][0], "success")
        self.assertEqual(versions[2][1], 1)
        self.assertTrue(versions[0][2].endswith("demo-success.log"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import unittest
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from wud_updater.banner import current_tag
from wud_updater.cli import main


class CliTests(unittest.TestCase):
    def _run_main(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(argv)
        return status, stdout.getvalue(), stderr.getvalue()

    def test_update_from_wud_dry_run_accepts_shell_flags(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wud-python-cli.") as tmpdir:
            root = Path(tmpdir)
            base = root / "base"
            wud_file = root / "images.todo"
            log_dir = root / "logs"
            base.mkdir()
            wud_file.write_text("", encoding="utf-8")

            status, stdout, stderr = self._run_main(
                [
                    "update-from-wud",
                    "--dry-run",
                    "--base",
                    str(base),
                    "--file",
                    str(wud_file),
                    "--log-dir",
                    str(log_dir),
                    "--mode",
                    "pause",
                    "--max-wait",
                    "0",
                    "--yes",
                    "--allow-tag-updates",
                    "--no-color",
                    "--only-lines",
                    "",
                    "--remove-lines-before-run",
                    "",
                ]
            )

        self.assertEqual(status, 0)
        self.assertIn(f"Base    : {base}", stdout)
        self.assertIn("Nothing to do; list is empty.", stdout)
        self.assertEqual(stderr, "")

    def test_update_from_wud_rejects_invalid_max_wait(self) -> None:
        status, _stdout, stderr = self._run_main(
            ["update-from-wud", "--max-wait", "not-a-number"]
        )

        self.assertEqual(status, 1)
        self.assertIn("--max-wait must be an integer number of seconds", stderr)

    def test_update_from_wud_uses_environment_log_dir(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wud-python-cli.") as tmpdir:
            root = Path(tmpdir)
            base = root / "base"
            wud_file = root / "images.todo"
            log_dir = root / "env-logs"
            base.mkdir()
            wud_file.write_text("", encoding="utf-8")

            with mock.patch.dict(os.environ, {"WUD_LOG_DIR": str(log_dir)}):
                status, stdout, stderr = self._run_main(
                    [
                        "update-from-wud",
                        "--dry-run",
                        "--base",
                        str(base),
                        "--file",
                        str(wud_file),
                        "--max-wait",
                        "0",
                        "--yes",
                        "--no-color",
                    ]
                )

        self.assertEqual(status, 0)
        self.assertIn(f"Log file: {log_dir}", stdout)
        self.assertEqual(stderr, "")

    def test_update_from_wud_prints_forced_startup_banner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wud-python-cli.") as tmpdir:
            root = Path(tmpdir)
            base = root / "base"
            wud_file = root / "images.todo"
            log_dir = root / "logs"
            base.mkdir()
            wud_file.write_text("", encoding="utf-8")

            env = {
                "WUD_UPDATER_BANNER": "true",
                "WUD_UPDATER_RELEASE_CHECK": "false",
                "PATH": os.environ.get("PATH", ""),
            }
            with mock.patch.dict(os.environ, env, clear=True):
                status, stdout, stderr = self._run_main(
                    [
                        "update-from-wud",
                        "--dry-run",
                        "--base",
                        str(base),
                        "--file",
                        str(wud_file),
                        "--log-dir",
                        str(log_dir),
                        "--max-wait",
                        "0",
                        "--yes",
                    ]
                )

        self.assertEqual(status, 0)
        self.assertIn(f"WUD-Updater {current_tag()}", stdout)
        self.assertIn("Nothing to do; list is empty.", stdout)
        self.assertEqual(stderr, "")

    def test_updates_dry_run_exits_successfully_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wud-python-cli.") as tmpdir:
            env = {
                "HOME": tmpdir,
                "WUD_UPDATER_CONFIG": str(Path(tmpdir) / "missing-env"),
                "WUD_UPDATER_RELEASE_CHECK": "0",
                "PATH": os.environ.get("PATH", ""),
            }
            with mock.patch.dict(os.environ, env, clear=True):
                status, stdout, stderr = self._run_main(
                    [
                        "updates",
                        "--dry-run",
                        "--mode",
                        "pause",
                        "--file",
                        str(Path(tmpdir) / "missing.todo"),
                    ]
                )

        self.assertEqual(status, 0)
        self.assertIn("=== 📦 Docker Updates ===", stdout)
        self.assertIn("✅ No pending Docker updates!", stdout)
        self.assertEqual(stderr, "")

    def test_updates_no_color_option_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wud-python-cli.") as tmpdir:
            env = {
                "HOME": tmpdir,
                "WUD_UPDATER_CONFIG": str(Path(tmpdir) / "missing-env"),
                "WUD_UPDATER_RELEASE_CHECK": "0",
                "PATH": os.environ.get("PATH", ""),
            }
            with mock.patch.dict(os.environ, env, clear=True):
                status, stdout, stderr = self._run_main(
                    [
                        "updates",
                        "--dry-run",
                        "--no-color",
                        "--file",
                        str(Path(tmpdir) / "missing.todo"),
                    ]
                )

        self.assertEqual(status, 0)
        self.assertIn("✅ No pending Docker updates!", stdout)
        self.assertEqual(stderr, "")

    def test_updates_prints_forced_startup_banner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wud-python-cli.") as tmpdir:
            env = {
                "HOME": tmpdir,
                "WUD_UPDATER_CONFIG": str(Path(tmpdir) / "missing-env"),
                "WUD_UPDATER_BANNER": "true",
                "WUD_UPDATER_RELEASE_CHECK": "false",
                "PATH": os.environ.get("PATH", ""),
            }
            with mock.patch.dict(os.environ, env, clear=True):
                status, stdout, stderr = self._run_main(
                    [
                        "updates",
                        "--dry-run",
                        "--file",
                        str(Path(tmpdir) / "missing.todo"),
                    ]
                )

        self.assertEqual(status, 0)
        self.assertIn(f"WUD-Updater {current_tag()}", stdout)
        self.assertIn("✅ No pending Docker updates!", stdout)
        self.assertEqual(stderr, "")

    def test_truenas_status_export_skips_forced_startup_banner(self) -> None:
        env = {
            "WUD_UPDATER_BANNER": "true",
            "WUD_UPDATER_RELEASE_CHECK": "false",
            "PATH": os.environ.get("PATH", ""),
        }
        with mock.patch.dict(os.environ, env, clear=True):
            status, stdout, stderr = self._run_main(["truenas-status-export"])

        self.assertEqual(status, 0)
        self.assertNotIn("WUD-Updater", stdout)
        self.assertTrue(stdout.strip().startswith("{"))
        self.assertEqual(stderr, "")

    def test_updates_yes_without_pending_entries_exits_successfully(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wud-python-cli.") as tmpdir:
            env = {
                "HOME": tmpdir,
                "WUD_UPDATER_CONFIG": str(Path(tmpdir) / "missing-env"),
                "WUD_UPDATER_RELEASE_CHECK": "0",
                "PATH": os.environ.get("PATH", ""),
            }
            with mock.patch.dict(os.environ, env, clear=True):
                status, stdout, stderr = self._run_main(
                    ["updates", "--yes", "--file", str(Path(tmpdir) / "empty.todo")]
                )

        self.assertEqual(status, 0)
        self.assertIn("✅ No pending Docker updates!", stdout)
        self.assertEqual(stderr, "")

    def test_keyboard_interrupt_returns_130_without_traceback(self) -> None:
        with mock.patch(
            "wud_updater.cli._run_updates",
            side_effect=KeyboardInterrupt,
        ):
            status, stdout, stderr = self._run_main(["updates", "--dry-run"])

        self.assertEqual(status, 130)
        self.assertEqual(stdout, "")
        self.assertIn("Interrupted.", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_missing_subcommand_is_rejected_by_parser(self) -> None:
        stderr = StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            main([])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("required", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

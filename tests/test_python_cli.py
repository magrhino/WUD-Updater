from __future__ import annotations

import unittest
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from wud_updater.cli import NOT_WIRED_MESSAGE, main


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

    def test_updates_dry_run_exits_successfully_without_mutation(self) -> None:
        status, _stdout, stderr = self._run_main(
            ["updates", "--dry-run", "--mode", "pause"]
        )

        self.assertEqual(status, 0)
        self.assertIn(NOT_WIRED_MESSAGE, stderr)
        self.assertIn("bin/updates", stderr)
        self.assertIn("No changes were made.", stderr)

    def test_updates_non_dry_run_refuses_mutating_path(self) -> None:
        status, _stdout, stderr = self._run_main(["updates", "--yes"])

        self.assertEqual(status, 1)
        self.assertIn("Refusing to continue", stderr)

    def test_missing_subcommand_is_rejected_by_parser(self) -> None:
        stderr = StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            main([])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("required", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

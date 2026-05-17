from __future__ import annotations

import unittest
from contextlib import redirect_stderr
from io import StringIO

from wud_updater.cli import NOT_WIRED_MESSAGE, main


class CliPlaceholderTests(unittest.TestCase):
    def _run_main(self, argv: list[str]) -> tuple[int, str]:
        stderr = StringIO()
        with redirect_stderr(stderr):
            status = main(argv)
        return status, stderr.getvalue()

    def test_update_from_wud_dry_run_exits_successfully_without_mutation(self) -> None:
        status, stderr = self._run_main(
            [
                "update-from-wud",
                "--dry-run",
                "--base",
                "/srv/docker",
                "--file",
                "/srv/wud/images.todo",
                "--log-dir",
                "/srv/docker/logs",
                "--only-lines",
                "1-2",
                "--remove-lines-before-run",
                "3",
                "--no-color",
            ]
        )

        self.assertEqual(status, 0)
        self.assertIn(NOT_WIRED_MESSAGE, stderr)
        self.assertIn("bin/docker-update-from-wud", stderr)
        self.assertIn("No changes were made.", stderr)

    def test_update_from_wud_non_dry_run_refuses_mutating_path(self) -> None:
        status, stderr = self._run_main(["update-from-wud", "--yes"])

        self.assertEqual(status, 1)
        self.assertIn("Refusing to continue", stderr)
        self.assertNotIn("No changes were made.", stderr)

    def test_updates_dry_run_exits_successfully_without_mutation(self) -> None:
        status, stderr = self._run_main(["updates", "--dry-run", "--mode", "pause"])

        self.assertEqual(status, 0)
        self.assertIn(NOT_WIRED_MESSAGE, stderr)
        self.assertIn("bin/updates", stderr)
        self.assertIn("No changes were made.", stderr)

    def test_updates_non_dry_run_refuses_mutating_path(self) -> None:
        status, stderr = self._run_main(["updates", "--yes"])

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

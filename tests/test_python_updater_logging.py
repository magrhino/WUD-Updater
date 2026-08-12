from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wudup.command import CommandResult
from wudup.file_ops import OwnerConfig
from wudup.updater_logging import (
    Logger,
    _create_unique_text_file_exclusive,
    _render_command_result,
    prepare_log_file,
    safe_component,
    sanitize_stream,
)


class UpdaterLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="wudup-logging.")
        self.root = Path(self.tmp.name)
        self.log_dir = self.root / "logs"
        self.log_dir.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_prepare_log_file_does_not_follow_existing_symlink(self) -> None:
        target = self.root / "symlink-target.log"
        target.write_text("keep\n", encoding="utf-8")
        (self.log_dir / "update-from-wud-v2-fixed.log").symlink_to(target)
        owner = OwnerConfig.from_values(str(os.getuid()), str(os.getgid()))

        with mock.patch(
            "wudup.updater_logging.file_timestamp",
            return_value="fixed",
        ):
            log_file = prepare_log_file(self.log_dir, owner)

        self.assertEqual(log_file.name, "update-from-wud-v2-fixed-1.log")
        self.assertEqual(target.read_text(encoding="utf-8"), "keep\n")
        self.assertFalse(log_file.is_symlink())
        self.assertEqual(log_file.read_text(encoding="utf-8"), "")
        after_stat = log_file.stat()
        self.assertEqual(
            (after_stat.st_uid, after_stat.st_gid),
            (os.getuid(), os.getgid()),
        )

    def test_create_unique_text_file_uses_collision_suffix(self) -> None:
        path = self.log_dir / "report.log"
        path.write_text("keep\n", encoding="utf-8")

        created = _create_unique_text_file_exclusive(path, "new\n")

        self.assertEqual(created, self.log_dir / "report-1.log")
        self.assertEqual(path.read_text(encoding="utf-8"), "keep\n")
        self.assertEqual(created.read_text(encoding="utf-8"), "new\n")

    def test_create_unique_text_file_exhausts_collision_attempts(self) -> None:
        path = self.log_dir / "report.log"
        path.write_text("existing\n", encoding="utf-8")
        (self.log_dir / "report-1.log").write_text("existing\n", encoding="utf-8")

        with mock.patch("wudup.updater_logging._EXCLUSIVE_CREATE_ATTEMPTS", 2):
            with self.assertRaises(FileExistsError) as raised:
                _create_unique_text_file_exclusive(path, "new\n")

        self.assertEqual(raised.exception.filename, str(path))
        self.assertIn(
            "could not create a unique file after 2 attempts",
            str(raised.exception),
        )

    def test_create_unique_text_file_applies_configured_owner(self) -> None:
        path = self.log_dir / "owned.log"
        owner = OwnerConfig.from_values(str(os.getuid()), str(os.getgid()))

        created = _create_unique_text_file_exclusive(path, "owned\n", owner=owner)

        after_stat = created.stat()
        self.assertEqual(created.read_text(encoding="utf-8"), "owned\n")
        self.assertEqual(
            (after_stat.st_uid, after_stat.st_gid),
            (os.getuid(), os.getgid()),
        )

    def test_logger_plain_uses_timestamp_owner(self) -> None:
        log_file = self.log_dir / "update.log"
        logger = Logger(log_file, no_color=True)

        with mock.patch("wudup.updater_logging.timestamp", return_value="fixed-time"):
            logger.plain("INFO", "message")

        self.assertEqual(
            log_file.read_text(encoding="utf-8"),
            "[fixed-time] [INFO] message\n",
        )

    def test_logger_warn_remains_a_compatibility_alias(self) -> None:
        logger = Logger(self.log_dir / "update.log", no_color=True)

        with mock.patch.object(logger, "_term") as term:
            logger.warning("new name")
            logger.warn("legacy name")  # noqa: G010 - compatibility alias coverage

        self.assertEqual(
            term.call_args_list,
            [mock.call("WARN", "new name"), mock.call("WARN", "legacy name")],
        )

    def test_safe_component_and_sanitize_stream(self) -> None:
        self.assertEqual(safe_component("release 2.0/arm64"), "release_2.0_arm64")
        self.assertEqual(safe_component(""), "tag")
        self.assertEqual(sanitize_stream("one\rtwo\x00\n"), "one\ntwo")

    def test_render_command_result_sanitizes_and_marks_empty_streams(self) -> None:
        result = CommandResult(
            args=("docker", "compose", "up"),
            cwd=Path("/stack"),
            returncode=7,
            stdout="pulled\r\n\x00done",
            stderr="",
            stdout_truncated=True,
        )

        rendered = "".join(_render_command_result(result))

        self.assertIn("cwd=/stack", rendered)
        self.assertIn("argv=docker compose up", rendered)
        self.assertIn("exit_code=7", rendered)
        self.assertIn("stdout_tail_truncated=true", rendered)
        self.assertIn("    pulled", rendered)
        self.assertIn("    done", rendered)
        self.assertIn("stderr_tail:\n    (empty)", rendered)


if __name__ == "__main__":
    unittest.main()

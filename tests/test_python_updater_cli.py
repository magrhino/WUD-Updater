from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from wudup.config import DEFAULT_MAX_WAIT
from wudup.updater_cli import (
    options_from_namespace,
    parse_seconds,
    parse_tag_overrides,
)
from wudup.updater_models import UpdaterError


def namespace(**overrides: object) -> SimpleNamespace:
    values = {
        "base": None,
        "file": None,
        "log_dir": None,
        "max_wait": None,
        "tag_override": None,
        "allow_tag_updates": False,
        "mode": None,
        "dry_run": False,
        "yes": False,
        "no_color": False,
        "only_lines": None,
        "remove_lines_before_run": None,
        "exclude_tag_lines": None,
        "recreate_excluded_services": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class UpdaterCliTests(unittest.TestCase):
    def test_options_from_namespace_uses_cli_env_and_defaults(self) -> None:
        args = namespace(
            base="/docker",
            log_dir="/logs",
            max_wait="12",
            dry_run=True,
            yes=True,
            no_color=True,
            only_lines="1,3",
        )
        env = {
            "HOME": "/home/example",
            "WUD_OUT_FILE": "/pending/images.todo",
            "WUD_DB_PATH": "/state/wud.sqlite",
            "WUD_UPDATE_MODE": "stop",
        }

        options = options_from_namespace(args, environ=env)

        self.assertEqual(options.docker_base, Path("/docker"))
        self.assertEqual(options.wud_file, Path("/pending/images.todo"))
        self.assertEqual(options.log_dir, Path("/logs"))
        self.assertEqual(options.db_path, Path("/state/wud.sqlite"))
        self.assertEqual(options.mode, "stop")
        self.assertEqual(options.max_wait, 12)
        self.assertTrue(options.dry_run)
        self.assertTrue(options.assume_yes)
        self.assertTrue(options.no_color)
        self.assertEqual(options.only_lines, "1,3")

    def test_options_from_namespace_defaults_paths_from_home(self) -> None:
        options = options_from_namespace(namespace(), environ={"HOME": "/home/example"})

        self.assertEqual(options.docker_base, Path("/home/example/docker"))
        self.assertEqual(
            options.wud_file,
            Path("/home/example/docker/wud/out/images.todo"),
        )
        self.assertEqual(options.log_dir, Path("logs"))
        self.assertEqual(options.max_wait, DEFAULT_MAX_WAIT)

    def test_host_docker_base_requires_absolute_paths(self) -> None:
        env = {"HOME": "/home/example", "HOST_DOCKER_BASE": "relative-host"}

        with self.assertRaisesRegex(
            UpdaterError,
            "HOST_DOCKER_BASE must be an absolute path",
        ):
            options_from_namespace(namespace(), environ=env)

    def test_tag_override_requires_tag_update_mode(self) -> None:
        args = namespace(tag_override=["1=2.0"])

        with self.assertRaisesRegex(
            UpdaterError,
            "--tag-override requires --allow-tag-updates",
        ):
            options_from_namespace(args, environ={"HOME": "/home/example"})

    def test_parse_seconds_default_and_validation(self) -> None:
        self.assertEqual(parse_seconds(None, "WUD_MAX_WAIT"), DEFAULT_MAX_WAIT)
        self.assertEqual(parse_seconds("", "WUD_MAX_WAIT"), DEFAULT_MAX_WAIT)
        self.assertEqual(parse_seconds("30", "WUD_MAX_WAIT"), 30)

        with self.assertRaisesRegex(
            UpdaterError,
            "WUD_MAX_WAIT must be an integer number of seconds",
        ):
            parse_seconds("3.5", "WUD_MAX_WAIT")

    def test_parse_tag_overrides_validates_duplicates_and_tags(self) -> None:
        overrides = parse_tag_overrides(("2=release-2026.06",))

        self.assertEqual(len(overrides), 1)
        self.assertEqual(overrides[0].line_no, 2)
        self.assertEqual(overrides[0].tag, "release-2026.06")

        with self.assertRaisesRegex(
            UpdaterError,
            "--tag-override line 2 was provided more than once",
        ):
            parse_tag_overrides(("2=stable", "2=latest"))

        with self.assertRaisesRegex(
            UpdaterError,
            "--tag-override line must be a positive integer",
        ):
            parse_tag_overrides(("0=stable",))

        with self.assertRaisesRegex(
            UpdaterError,
            "--tag-override line 1 has invalid tag",
        ):
            parse_tag_overrides(("1=bad tag",))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo, reset_tzpath
import zoneinfo

from wud_updater.config import ConfigError, load_config


class LoadConfigTests(unittest.TestCase):
    def test_defaults_use_home_docker_layout(self) -> None:
        config = load_config({}, home="/home/wud")

        self.assertEqual(config.docker_base, Path("/home/wud/docker"))
        self.assertEqual(
            config.wud_out_file,
            Path("/home/wud/docker/wud/out/images.todo"),
        )
        self.assertEqual(config.log_dir, Path("logs"))
        self.assertEqual(config.db_path, Path("logs/wud-updater.sqlite"))
        self.assertEqual(config.update_mode, "stop")
        self.assertEqual(config.max_wait, 180)
        self.assertEqual(config.lock_timeout, 30)
        self.assertEqual(config.timezone_name, "UTC")
        self.assertIsNone(config.out_uid)
        self.assertIsNone(config.out_gid)

    def test_environment_overrides_defaults(self) -> None:
        config = load_config(
            {
                "DOCKER_BASE": "/srv/docker",
                "WUD_OUT_FILE": "/srv/wud/images.todo",
                "WUD_LOG_DIR": "/srv/logs",
                "WUD_DB_PATH": "/srv/state/wud.sqlite",
                "WUD_UPDATE_MODE": "live",
                "WUD_MAX_WAIT": "7",
                "WUD_LOCK_TIMEOUT": "2",
                "WUD_TIMEZONE": "America/Chicago",
                "OUT_UID": "1000",
                "OUT_GID": "1001",
            },
            home="/home/wud",
        )

        self.assertEqual(config.docker_base, Path("/srv/docker"))
        self.assertEqual(config.wud_out_file, Path("/srv/wud/images.todo"))
        self.assertEqual(config.log_dir, Path("/srv/logs"))
        self.assertEqual(config.db_path, Path("/srv/state/wud.sqlite"))
        self.assertEqual(config.update_mode, "live")
        self.assertEqual(config.max_wait, 7)
        self.assertEqual(config.lock_timeout, 2)
        self.assertEqual(config.timezone_name, "America/Chicago")
        self.assertEqual(config.out_uid, 1000)
        self.assertEqual(config.out_gid, 1001)

    def test_empty_environment_values_use_defaults(self) -> None:
        config = load_config(
            {
                "HOME": "",
                "DOCKER_BASE": "",
                "WUD_OUT_FILE": "",
                "WUD_LOG_DIR": "",
                "WUD_DB_PATH": "",
                "WUD_UPDATE_MODE": "",
                "WUD_MAX_WAIT": "",
                "WUD_LOCK_TIMEOUT": "",
                "WUD_TIMEZONE": "",
            },
            home="/home/wud",
        )

        self.assertEqual(config.docker_base, Path("/home/wud/docker"))
        self.assertEqual(
            config.wud_out_file,
            Path("/home/wud/docker/wud/out/images.todo"),
        )
        self.assertEqual(config.log_dir, Path("logs"))
        self.assertEqual(config.db_path, Path("logs/wud-updater.sqlite"))
        self.assertEqual(config.update_mode, "stop")
        self.assertEqual(config.max_wait, 180)
        self.assertEqual(config.lock_timeout, 30)
        self.assertEqual(config.timezone_name, "UTC")

    def test_db_path_defaults_under_configured_log_dir(self) -> None:
        config = load_config({"WUD_LOG_DIR": "/srv/logs"}, home="/home/wud")

        self.assertEqual(config.db_path, Path("/srv/logs/wud-updater.sqlite"))

    def test_out_guid_alias_is_used_when_out_gid_is_absent(self) -> None:
        config = load_config(
            {
                "OUT_UID": "1000",
                "OUT_GUID": "1002",
            },
            home="/home/wud",
        )

        self.assertEqual(config.out_uid, 1000)
        self.assertEqual(config.out_gid, 1002)

    def test_out_gid_takes_precedence_over_out_guid(self) -> None:
        config = load_config(
            {
                "OUT_UID": "1000",
                "OUT_GID": "1001",
                "OUT_GUID": "1002",
            },
            home="/home/wud",
        )

        self.assertEqual(config.out_gid, 1001)

    def test_owner_ids_must_be_set_together(self) -> None:
        with self.assertRaisesRegex(ConfigError, "must be set together"):
            load_config({"OUT_UID": "1000"}, home="/home/wud")

        with self.assertRaisesRegex(ConfigError, "must be set together"):
            load_config({"OUT_GID": "1000"}, home="/home/wud")

    def test_non_negative_second_values_are_validated(self) -> None:
        invalid_cases = (
            ({"WUD_MAX_WAIT": "slow"}, "WUD_MAX_WAIT.*integer"),
            ({"WUD_MAX_WAIT": "-1"}, "WUD_MAX_WAIT.*zero or greater"),
            ({"WUD_LOCK_TIMEOUT": "slow"}, "WUD_LOCK_TIMEOUT.*integer"),
            ({"WUD_LOCK_TIMEOUT": "-1"}, "WUD_LOCK_TIMEOUT.*zero or greater"),
        )

        for env, error in invalid_cases:
            with self.subTest(env=env):
                with self.assertRaisesRegex(ConfigError, error):
                    load_config(env, home="/home/wud")

    def test_owner_ids_are_validated(self) -> None:
        invalid_cases = (
            ({"OUT_UID": "user", "OUT_GID": "1000"}, "OUT_UID must be numeric"),
            ({"OUT_UID": "-1", "OUT_GID": "1000"}, "OUT_UID.*zero or greater"),
            ({"OUT_UID": "1000", "OUT_GID": "group"}, "OUT_GID/OUT_GUID must be numeric"),
            ({"OUT_UID": "1000", "OUT_GID": "-1"}, "OUT_GID/OUT_GUID.*zero or greater"),
            ({"OUT_UID": "1000", "OUT_GUID": "group"}, "OUT_GID/OUT_GUID must be numeric"),
            ({"OUT_UID": "1000", "OUT_GUID": "-1"}, "OUT_GID/OUT_GUID.*zero or greater"),
        )

        for env, error in invalid_cases:
            with self.subTest(env=env):
                with self.assertRaisesRegex(ConfigError, error):
                    load_config(env, home="/home/wud")

    def test_update_mode_is_validated(self) -> None:
        with self.assertRaisesRegex(ConfigError, "WUD_UPDATE_MODE"):
            load_config({"WUD_UPDATE_MODE": "restart"}, home="/home/wud")

    def test_timezone_is_validated(self) -> None:
        with self.assertRaisesRegex(ConfigError, "WUD_TIMEZONE"):
            load_config({"WUD_TIMEZONE": "Mars/Base"}, home="/home/wud")

    def test_timezone_uses_tzdata_when_system_paths_are_empty(self) -> None:
        original_tzpath = zoneinfo.TZPATH
        try:
            with patch.dict(os.environ, {"PYTHONTZPATH": ""}):
                ZoneInfo.clear_cache()
                reset_tzpath()
                config = load_config(
                    {"WUD_TIMEZONE": "America/Chicago"},
                    home="/home/wud",
                )
        finally:
            reset_tzpath(original_tzpath)
            ZoneInfo.clear_cache()

        self.assertEqual(config.timezone_name, "America/Chicago")


if __name__ == "__main__":
    unittest.main()

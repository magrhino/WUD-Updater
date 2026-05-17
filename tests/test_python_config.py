from __future__ import annotations

import unittest
from pathlib import Path

from wud_updater.config import ConfigError, load_config


class LoadConfigTests(unittest.TestCase):
    def test_defaults_use_home_docker_layout(self) -> None:
        config = load_config({}, home="/home/wud")

        self.assertEqual(config.docker_base, Path("/home/wud/docker"))
        self.assertEqual(
            config.wud_out_file,
            Path("/home/wud/docker/wud/out/images.todo"),
        )
        self.assertEqual(config.log_dir, Path("/home/wud/docker/logs"))
        self.assertEqual(config.update_mode, "stop")
        self.assertEqual(config.max_wait, 180)
        self.assertEqual(config.lock_timeout, 30)
        self.assertIsNone(config.out_uid)
        self.assertIsNone(config.out_gid)

    def test_environment_overrides_defaults(self) -> None:
        config = load_config(
            {
                "DOCKER_BASE": "/srv/docker",
                "WUD_OUT_FILE": "/srv/wud/images.todo",
                "WUD_UPDATE_MODE": "live",
                "WUD_MAX_WAIT": "7",
                "WUD_LOCK_TIMEOUT": "2",
                "OUT_UID": "1000",
                "OUT_GID": "1001",
            },
            home="/home/wud",
        )

        self.assertEqual(config.docker_base, Path("/srv/docker"))
        self.assertEqual(config.wud_out_file, Path("/srv/wud/images.todo"))
        self.assertEqual(config.log_dir, Path("/srv/docker/logs"))
        self.assertEqual(config.update_mode, "live")
        self.assertEqual(config.max_wait, 7)
        self.assertEqual(config.lock_timeout, 2)
        self.assertEqual(config.out_uid, 1000)
        self.assertEqual(config.out_gid, 1001)

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

    def test_numeric_values_are_validated(self) -> None:
        with self.assertRaisesRegex(ConfigError, "WUD_MAX_WAIT"):
            load_config({"WUD_MAX_WAIT": "slow"}, home="/home/wud")

    def test_update_mode_is_validated(self) -> None:
        with self.assertRaisesRegex(ConfigError, "WUD_UPDATE_MODE"):
            load_config({"WUD_UPDATE_MODE": "restart"}, home="/home/wud")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from wud_updater.self_update import current_container_image, release_self_update_target


class SelfUpdateTests(unittest.TestCase):
    def test_current_container_image_prefers_config_image_reference(self) -> None:
        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["docker"],
                0,
                stdout=(
                    '[{"Image":"sha256:aaaaaaaa",'
                    '"Config":{"Image":"ghcr.io/magrhino/wud-updater:latest"}}]'
                ),
                stderr="",
            ),
        ):
            image = current_container_image({"HOSTNAME": "wud-updater-1"})

        self.assertEqual(image, "ghcr.io/magrhino/wud-updater:latest")

    def test_release_self_update_target_rewrites_pinned_release_tag(self) -> None:
        target = release_self_update_target(
            "ghcr.io/magrhino/wud-updater:v0.12.2",
            "v0.12.3",
        )

        self.assertEqual(
            target,
            "ghcr.io/magrhino/wud-updater:v0.12.2 tag=v0.12.3",
        )

    def test_release_self_update_target_keeps_floating_tag(self) -> None:
        target = release_self_update_target(
            "ghcr.io/magrhino/wud-updater:latest",
            "v0.12.3",
        )

        self.assertEqual(target, "ghcr.io/magrhino/wud-updater:latest")


if __name__ == "__main__":
    unittest.main()

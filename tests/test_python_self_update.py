from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from wud_updater.container_identity import container_identity_candidates
from wud_updater.self_update import current_container_image, release_self_update_target


class ContainerIdentityTests(unittest.TestCase):
    def test_candidates_include_restart_target_hostname_and_cgroup_id(self) -> None:
        with mock.patch(
            "pathlib.Path.read_text",
            return_value=(
                "0::/docker/"
                "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef\n"
            ),
        ):
            candidates = container_identity_candidates(
                {
                    "WUD_WEB_RESTART_CONTAINER": "wud-updater",
                    "HOSTNAME": "custom-hostname",
                }
            )

        self.assertEqual(
            candidates,
            [
                "wud-updater",
                "custom-hostname",
                "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            ],
        )


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

    def test_current_container_image_tries_next_candidate_after_missing_name(self) -> None:
        run_mock = mock.Mock(
            side_effect=[
                subprocess.CompletedProcess(["docker"], 1, stdout="", stderr="missing"),
                subprocess.CompletedProcess(
                    ["docker"],
                    0,
                    stdout='[{"Config":{"Image":"ghcr.io/magrhino/wud-updater:latest"}}]',
                    stderr="",
                ),
            ]
        )

        with (
            mock.patch(
                "wud_updater.self_update.container_identity_candidates",
                return_value=["custom-hostname", "actual-container-id"],
            ),
            mock.patch("subprocess.run", run_mock),
        ):
            image = current_container_image({"HOSTNAME": "custom-hostname"})

        self.assertEqual(image, "ghcr.io/magrhino/wud-updater:latest")
        self.assertEqual(
            run_mock.call_args_list[1].args[0],
            ["docker", "container", "inspect", "actual-container-id"],
        )

    def test_release_self_update_target_rewrites_pinned_release_tag(self) -> None:
        target = release_self_update_target(
            "ghcr.io/magrhino/wud-updater:v0.12.2",
            "v0.12.2",
            "v0.12.3",
        )

        self.assertEqual(
            target,
            "ghcr.io/magrhino/wud-updater:v0.12.2 tag=v0.12.3",
        )

    def test_release_self_update_target_keeps_floating_tag(self) -> None:
        target = release_self_update_target(
            "ghcr.io/magrhino/wud-updater:latest",
            "v0.12.2",
            "v0.12.3",
        )

        self.assertEqual(target, "ghcr.io/magrhino/wud-updater:latest")

    def test_release_self_update_target_uses_local_tag_when_image_unknown(self) -> None:
        target = release_self_update_target(
            "",
            "v0.12.2",
            "v0.12.3",
        )

        self.assertEqual(
            target,
            "ghcr.io/magrhino/wud-updater:v0.12.2 tag=v0.12.3",
        )

    def test_release_self_update_target_falls_back_when_local_tag_is_not_image_tag(
        self,
    ) -> None:
        target = release_self_update_target(
            "",
            "v0.12.2+build",
            "v0.12.3",
        )

        self.assertEqual(target, "ghcr.io/magrhino/wud-updater:latest")


if __name__ == "__main__":
    unittest.main()

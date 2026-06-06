from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from wud_updater.container_identity import (
    _container_ids_from_cgroup,
    _unique,
    container_identity_candidates,
)
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

    def test_candidates_empty_when_no_env_vars_and_no_cgroup(self) -> None:
        with mock.patch("pathlib.Path.read_text", side_effect=OSError("not found")):
            candidates = container_identity_candidates({})

        self.assertEqual(candidates, [])

    def test_candidates_only_restart_container_when_hostname_missing(self) -> None:
        with mock.patch("pathlib.Path.read_text", side_effect=OSError("not found")):
            candidates = container_identity_candidates(
                {"WUD_WEB_RESTART_CONTAINER": "wud-updater-1"}
            )

        self.assertEqual(candidates, ["wud-updater-1"])

    def test_candidates_only_hostname_when_restart_container_missing(self) -> None:
        with mock.patch("pathlib.Path.read_text", side_effect=OSError("not found")):
            candidates = container_identity_candidates({"HOSTNAME": "my-host"})

        self.assertEqual(candidates, ["my-host"])

    def test_candidates_deduplicates_when_restart_container_equals_hostname(
        self,
    ) -> None:
        with mock.patch("pathlib.Path.read_text", side_effect=OSError("not found")):
            candidates = container_identity_candidates(
                {
                    "WUD_WEB_RESTART_CONTAINER": "same-name",
                    "HOSTNAME": "same-name",
                }
            )

        self.assertEqual(candidates, ["same-name"])

    def test_candidates_strips_whitespace_from_env_values(self) -> None:
        with mock.patch("pathlib.Path.read_text", side_effect=OSError("not found")):
            candidates = container_identity_candidates(
                {
                    "WUD_WEB_RESTART_CONTAINER": "  wud-updater  ",
                    "HOSTNAME": "  my-host  ",
                }
            )

        self.assertEqual(candidates, ["wud-updater", "my-host"])

    def test_candidates_skips_empty_env_values(self) -> None:
        with mock.patch("pathlib.Path.read_text", side_effect=OSError("not found")):
            candidates = container_identity_candidates(
                {
                    "WUD_WEB_RESTART_CONTAINER": "",
                    "HOSTNAME": "",
                }
            )

        self.assertEqual(candidates, [])

    def test_candidates_cgroup_oserror_returns_no_cgroup_entries(self) -> None:
        with mock.patch("pathlib.Path.read_text", side_effect=OSError("permission denied")):
            candidates = container_identity_candidates({"HOSTNAME": "my-host"})

        self.assertEqual(candidates, ["my-host"])

    def test_candidates_extracts_multiple_ids_from_cgroup(self) -> None:
        id_a = "a" * 64
        id_b = "b" * 64
        cgroup_text = f"0::/docker/{id_a}\n12:memory:/docker/{id_b}\n"
        with mock.patch("pathlib.Path.read_text", return_value=cgroup_text):
            candidates = container_identity_candidates({})

        self.assertIn(id_a, candidates)
        self.assertIn(id_b, candidates)

    def test_candidates_deduplicates_cgroup_id_matching_hostname(self) -> None:
        container_id = "c" * 64
        cgroup_text = f"0::/docker/{container_id}\n"
        with mock.patch("pathlib.Path.read_text", return_value=cgroup_text):
            candidates = container_identity_candidates({"HOSTNAME": container_id})

        self.assertEqual(candidates.count(container_id), 1)

    def test_candidates_uses_custom_cgroup_path(self) -> None:
        container_id = "d" * 64
        cgroup_text = f"0::/docker/{container_id}\n"
        custom_path = Path("/custom/cgroup")
        with mock.patch.object(Path, "read_text", return_value=cgroup_text):
            candidates = container_identity_candidates({}, cgroup_path=custom_path)

        self.assertIn(container_id, candidates)

    def test_container_ids_from_cgroup_ignores_short_hex_strings(self) -> None:
        # A 63-char hex string must NOT match (needs exactly 64)
        short_id = "a" * 63
        long_id = "b" * 64
        result = _container_ids_from_cgroup(f"/docker/{short_id}\n/docker/{long_id}\n")

        self.assertNotIn(short_id, result)
        self.assertIn(long_id, result)

    def test_unique_removes_duplicate_strings(self) -> None:
        result = _unique(["alpha", "beta", "alpha", "gamma", "beta"])

        self.assertEqual(result, ["alpha", "beta", "gamma"])

    def test_unique_skips_non_string_values(self) -> None:
        result = _unique(["valid", 42, None, "also-valid"])  # type: ignore[list-item]

        self.assertEqual(result, ["valid", "also-valid"])

    def test_unique_skips_empty_strings(self) -> None:
        result = _unique(["", "  ", "real-value", ""])

        self.assertEqual(result, ["real-value"])


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

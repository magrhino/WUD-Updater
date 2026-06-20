from __future__ import annotations

import subprocess
import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest import mock

from wudup.container_identity import container_identity_candidates
from wudup.self_update import (
    _image_reference_tag,
    _inspected_container_image,
    _is_release_image_tag,
    current_container_image,
    is_self_update_target,
    main,
    release_self_update_target,
    self_update_display_numbers,
    self_update_enabled,
)


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
                    "WUD_WEB_RESTART_CONTAINER": "wudup",
                    "HOSTNAME": "custom-hostname",
                }
            )

        self.assertEqual(
            candidates,
            [
                "wudup",
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
                    '"Config":{"Image":"ghcr.io/magrhino/wudup:latest"}}]'
                ),
                stderr="",
            ),
        ):
            image = current_container_image({"HOSTNAME": "wudup-1"})

        self.assertEqual(image, "ghcr.io/magrhino/wudup:latest")

    def test_current_container_image_tries_next_candidate_after_missing_name(self) -> None:
        run_mock = mock.Mock(
            side_effect=[
                subprocess.CompletedProcess(["docker"], 1, stdout="", stderr="missing"),
                subprocess.CompletedProcess(
                    ["docker"],
                    0,
                    stdout='[{"Config":{"Image":"ghcr.io/magrhino/wudup:latest"}}]',
                    stderr="",
                ),
            ]
        )

        with (
            mock.patch(
                "wudup.self_update.container_identity_candidates",
                return_value=["custom-hostname", "actual-container-id"],
            ),
            mock.patch("subprocess.run", run_mock),
        ):
            image = current_container_image({"HOSTNAME": "custom-hostname"})

        self.assertEqual(image, "ghcr.io/magrhino/wudup:latest")
        self.assertEqual(
            run_mock.call_args_list[1].args[0],
            ["docker", "container", "inspect", "actual-container-id"],
        )

    def test_release_self_update_target_rewrites_pinned_release_tag(self) -> None:
        target = release_self_update_target(
            "ghcr.io/magrhino/wudup:v0.12.2",
            "v0.12.2",
            "v0.12.3",
        )

        self.assertEqual(
            target,
            "ghcr.io/magrhino/wudup:v0.12.2 tag=v0.12.3",
        )

    def test_release_self_update_target_keeps_floating_tag(self) -> None:
        target = release_self_update_target(
            "ghcr.io/magrhino/wudup:latest",
            "v0.12.2",
            "v0.12.3",
        )

        self.assertEqual(target, "ghcr.io/magrhino/wudup:latest")

    def test_release_self_update_target_uses_local_tag_when_image_unknown(self) -> None:
        target = release_self_update_target(
            "",
            "v0.12.2",
            "v0.12.3",
        )

        self.assertEqual(
            target,
            "ghcr.io/magrhino/wudup:v0.12.2 tag=v0.12.3",
        )

    def test_release_self_update_target_falls_back_when_local_tag_is_not_image_tag(
        self,
    ) -> None:
        target = release_self_update_target(
            "",
            "v0.12.2+build",
            "v0.12.3",
        )

        self.assertEqual(target, "ghcr.io/magrhino/wudup:latest")

    def test_release_self_update_target_keeps_current_image_when_tag_matches_latest(
        self,
    ) -> None:
        # When the pinned tag already matches the latest, return the image as-is.
        target = release_self_update_target(
            "ghcr.io/magrhino/wudup:v0.12.3",
            "v0.12.3",
            "v0.12.3",
        )

        self.assertEqual(target, "ghcr.io/magrhino/wudup:v0.12.3")

    def test_current_container_image_returns_empty_without_candidates(self) -> None:
        with mock.patch(
            "wudup.self_update.container_identity_candidates",
            return_value=[],
        ):
            image = current_container_image({})

        self.assertEqual(image, "")

    def test_current_container_image_returns_empty_on_os_error(self) -> None:
        with (
            mock.patch(
                "wudup.self_update.container_identity_candidates",
                return_value=["wudup-1"],
            ),
            mock.patch(
                "subprocess.run",
                side_effect=OSError("docker not found"),
            ),
        ):
            image = current_container_image({"HOSTNAME": "wudup-1"})

        self.assertEqual(image, "")

    def test_current_container_image_returns_empty_on_timeout(self) -> None:
        with (
            mock.patch(
                "wudup.self_update.container_identity_candidates",
                return_value=["wudup-1"],
            ),
            mock.patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(["docker"], 5),
            ),
        ):
            image = current_container_image({"HOSTNAME": "wudup-1"})

        self.assertEqual(image, "")

    def test_current_container_image_returns_empty_on_invalid_json(self) -> None:
        with (
            mock.patch(
                "wudup.self_update.container_identity_candidates",
                return_value=["wudup-1"],
            ),
            mock.patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["docker"], 0, stdout="not valid json", stderr=""
                ),
            ),
        ):
            image = current_container_image({"HOSTNAME": "wudup-1"})

        self.assertEqual(image, "")

    def test_current_container_image_returns_empty_for_non_list_payload(self) -> None:
        with (
            mock.patch(
                "wudup.self_update.container_identity_candidates",
                return_value=["wudup-1"],
            ),
            mock.patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["docker"], 0, stdout='{"Config":{"Image":"x"}}', stderr=""
                ),
            ),
        ):
            image = current_container_image({"HOSTNAME": "wudup-1"})

        self.assertEqual(image, "")

    def test_current_container_image_returns_empty_for_empty_list_payload(
        self,
    ) -> None:
        with (
            mock.patch(
                "wudup.self_update.container_identity_candidates",
                return_value=["wudup-1"],
            ),
            mock.patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["docker"], 0, stdout="[]", stderr=""
                ),
            ),
        ):
            image = current_container_image({"HOSTNAME": "wudup-1"})

        self.assertEqual(image, "")

    def test_current_container_image_returns_empty_for_non_dict_container(
        self,
    ) -> None:
        with (
            mock.patch(
                "wudup.self_update.container_identity_candidates",
                return_value=["wudup-1"],
            ),
            mock.patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["docker"], 0, stdout='["not-a-dict"]', stderr=""
                ),
            ),
        ):
            image = current_container_image({"HOSTNAME": "wudup-1"})

        self.assertEqual(image, "")


class InspectedContainerImageTests(unittest.TestCase):
    def test_prefers_config_image_over_top_level_image(self) -> None:
        container = {
            "Config": {"Image": "ghcr.io/magrhino/wudup:latest"},
            "Image": "sha256:aaaa",
        }
        self.assertEqual(
            _inspected_container_image(container),
            "ghcr.io/magrhino/wudup:latest",
        )

    def test_falls_back_to_top_level_image_when_no_config(self) -> None:
        container = {"Image": "ghcr.io/magrhino/wudup:latest"}
        self.assertEqual(
            _inspected_container_image(container),
            "ghcr.io/magrhino/wudup:latest",
        )

    def test_returns_empty_when_no_image_fields(self) -> None:
        container: dict[str, object] = {}
        self.assertEqual(_inspected_container_image(container), "")

    def test_returns_empty_when_config_image_is_empty_string(self) -> None:
        container = {"Config": {"Image": ""}}
        self.assertEqual(_inspected_container_image(container), "")

    def test_returns_empty_when_top_level_image_is_empty_string(self) -> None:
        container = {"Image": ""}
        self.assertEqual(_inspected_container_image(container), "")

    def test_returns_empty_when_config_is_not_a_dict(self) -> None:
        container = {"Config": "not-a-dict"}
        self.assertEqual(_inspected_container_image(container), "")


class ImageReferenceTagTests(unittest.TestCase):
    def test_extracts_tag_from_standard_image(self) -> None:
        self.assertEqual(_image_reference_tag("ghcr.io/org/app:v1.2.3"), "v1.2.3")

    def test_strips_digest_before_extracting_tag(self) -> None:
        self.assertEqual(
            _image_reference_tag(
                "ghcr.io/org/app:v1.2.3@sha256:deadbeef"
            ),
            "v1.2.3",
        )

    def test_returns_empty_when_no_tag(self) -> None:
        self.assertEqual(_image_reference_tag("ghcr.io/org/app"), "")

    def test_returns_latest_tag(self) -> None:
        self.assertEqual(_image_reference_tag("repo/app:latest"), "latest")


class IsReleaseImageTagTests(unittest.TestCase):
    def test_semver_tag_is_release(self) -> None:
        self.assertTrue(_is_release_image_tag("v1.2.3"))
        self.assertTrue(_is_release_image_tag("1.2.3"))
        self.assertTrue(_is_release_image_tag("v0.12.2-beta.1"))

    def test_latest_is_not_release_tag(self) -> None:
        self.assertFalse(_is_release_image_tag("latest"))

    def test_empty_is_not_release_tag(self) -> None:
        self.assertFalse(_is_release_image_tag(""))

    def test_partial_version_is_not_release_tag(self) -> None:
        self.assertFalse(_is_release_image_tag("v1.2"))


class SelfUpdateEnabledTests(unittest.TestCase):
    def test_returns_true_by_default(self) -> None:
        self.assertTrue(self_update_enabled({}))

    def test_cli_false_overrides_default(self) -> None:
        self.assertFalse(self_update_enabled({}, cli_value=False))

    def test_cli_true_overrides_env_false(self) -> None:
        self.assertTrue(
            self_update_enabled({"WUDUP_SELF_UPDATE": "false"}, cli_value=True)
        )

    def test_env_false_disables(self) -> None:
        self.assertFalse(
            self_update_enabled({"WUDUP_SELF_UPDATE": "false"})
        )

    def test_legacy_env_false_disables(self) -> None:
        self.assertFalse(
            self_update_enabled({"WUD_UPDATER_SELF_UPDATE": "false"})
        )

    def test_env_zero_disables(self) -> None:
        self.assertFalse(self_update_enabled({"WUDUP_SELF_UPDATE": "0"}))

    def test_env_no_disables(self) -> None:
        self.assertFalse(self_update_enabled({"WUDUP_SELF_UPDATE": "no"}))

    def test_env_off_disables(self) -> None:
        self.assertFalse(self_update_enabled({"WUDUP_SELF_UPDATE": "off"}))

    def test_env_true_enables(self) -> None:
        self.assertTrue(self_update_enabled({"WUDUP_SELF_UPDATE": "true"}))


class IsAndDisplaySelfUpdateTests(unittest.TestCase):
    def test_is_self_update_target_matches_known_repos(self) -> None:
        self.assertTrue(is_self_update_target("ghcr.io/magrhino/wudup:latest"))
        self.assertTrue(is_self_update_target("ghcr.io/Magrhino/WUDup:v1.0.0"))
        self.assertTrue(
            is_self_update_target("ghcr.io/magrhino/wud-updater:latest")
        )

    def test_is_self_update_target_rejects_other_repos(self) -> None:
        self.assertFalse(is_self_update_target("ghcr.io/someone/other-app:latest"))

    def test_self_update_display_numbers_finds_positions(self) -> None:
        entry_a = mock.Mock()
        entry_a.first = "ghcr.io/magrhino/wudup:latest"
        entry_b = mock.Mock()
        entry_b.first = "other/app:latest"
        entry_c = mock.Mock()
        entry_c.first = "ghcr.io/magrhino/wudup:v1.0.0"

        result = self_update_display_numbers([entry_a, entry_b, entry_c])

        self.assertEqual(result, [1, 3])

    def test_self_update_display_numbers_empty_list(self) -> None:
        self.assertEqual(self_update_display_numbers([]), [])

    def test_self_update_display_numbers_no_matches(self) -> None:
        entry = mock.Mock()
        entry.first = "other/app:latest"
        self.assertEqual(self_update_display_numbers([entry]), [])


class MainTests(unittest.TestCase):
    def test_main_returns_2_for_wrong_args(self) -> None:
        stderr = StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(main(["wrong"]), 2)
            self.assertEqual(main([]), 2)
            self.assertEqual(main(["github-target", "extra"]), 2)

    def test_main_returns_0_when_no_update_available(self) -> None:
        with (
            mock.patch(
                "wudup.self_update.github_release_self_update",
                return_value=None,
            ),
        ):
            self.assertEqual(main(["github-target"]), 0)

    def test_main_prints_target_when_update_available(self) -> None:
        from wudup.self_update import ReleaseSelfUpdate
        from io import StringIO
        from contextlib import redirect_stdout

        update = ReleaseSelfUpdate(
            local_tag="v0.12.2",
            latest_tag="v0.12.3",
            target="ghcr.io/magrhino/wudup:v0.12.2 tag=v0.12.3",
        )
        buf = StringIO()
        with (
            mock.patch(
                "wudup.self_update.github_release_self_update",
                return_value=update,
            ),
            redirect_stdout(buf),
        ):
            result = main(["github-target"])

        self.assertEqual(result, 0)
        self.assertIn("tag=v0.12.3", buf.getvalue())


if __name__ == "__main__":
    unittest.main()

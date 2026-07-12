from __future__ import annotations

import os
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import mock

from wudup.updates import (
    _self_update_desired_tag,
    run_updates_from_namespace,
)

from tests.updates_wrapper_helpers import UpdatesWrapperTestCase, _updater_arg_lines

class UpdatesWrapperSelfUpdateTests(UpdatesWrapperTestCase):
    def _run_github_release_self_update(
        self,
        current_image: str,
        *,
        env_overrides: dict[str, str] | None = None,
    ) -> tuple[int, StringIO, StringIO]:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.fake_bin}:{env.get('PATH', '')}",
                "WUDUP_UPDATER": str(self.updater),
                "WUDUP_CONFIG": str(self.root / "missing-env"),
                "FAKE_SUDO_LOG": str(self.sudo_log),
                "FAKE_UPDATER_LOG": str(self.updater_log),
                "FAKE_DOCKER_LOG": str(self.docker_log),
                "WUDUP_BANNER": "0",
                "WUDUP_RELEASE_CHECK": "1",
                "HOSTNAME": "wudup-1",
            }
        )
        if env_overrides is not None:
            env.update(env_overrides)
        args = Namespace(
            base=str(self.root / "docker"),
            file=str(self.wud_file),
            log_dir=None,
            mode=None,
            max_wait=None,
            dry_run=False,
            yes=True,
            allow_tag_updates=False,
            no_color=True,
            no_updater_sudo=False,
            self_update=None,
        )
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch(
                "wudup.self_update.fetch_latest_release_tag",
                return_value="v999.0.0",
            ),
            mock.patch(
                "wudup.self_update.current_container_image",
                return_value=current_image,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = run_updates_from_namespace(
                args,
                repo_root=self.repo_root,
                environ=env,
            )

        return status, stdout, stderr
    def test_self_update_desired_tag_uses_canonical_wud_parsing(self) -> None:
        self.assertEqual(
            _self_update_desired_tag("repo/app:1.0 note=ignored tag=2.0"),
            "2.0",
        )
        self.assertEqual(_self_update_desired_tag("repo/app tag=2.0"), "")
    def test_self_update_yes_runs_wud_entry_before_remaining_updates(self) -> None:
        self.wud_file.write_text(
            "ghcr.io/magrhino/wudup:latest\nrepo/app:latest\n",
            encoding="utf-8",
        )

        result = self.run_updates(
            "--yes",
            env_overrides={"FAKE_UPDATER_REMOVE_ONLY_LINES": "1"},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        arg_lines = _updater_arg_lines(self.updater_log.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(arg_lines), 2)
        self.assertIn("--only-lines 1", arg_lines[0])
        self.assertNotIn("--only-lines", arg_lines[1])
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:latest\n",
        )
    def test_self_update_tag_entry_enables_tag_updates(self) -> None:
        self.wud_file.write_text(
            "ghcr.io/magrhino/wudup:1.0 tag=2.0\nrepo/app:latest\n",
            encoding="utf-8",
        )

        result = self.run_updates(
            "--yes",
            env_overrides={"FAKE_UPDATER_REMOVE_ONLY_LINES": "1"},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        arg_lines = _updater_arg_lines(self.updater_log.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(arg_lines), 2)
        self.assertIn("--only-lines 1 --allow-tag-updates --yes", arg_lines[0])
        self.assertNotIn("--allow-tag-updates", arg_lines[1])
    def test_self_update_prompt_decline_continues_to_normal_selection(self) -> None:
        self.wud_file.write_text(
            "ghcr.io/magrhino/wudup:latest\nrepo/app:latest\n",
            encoding="utf-8",
        )

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="n\ns\n2\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Skipped WUDup self-update", result.stdout)
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn("--only-lines 2 --yes", updater_log)
        self.assertNotIn("--only-lines 1", updater_log)
    def test_self_update_eof_declines_without_invoking_updater(self) -> None:
        self.wud_file.write_text(
            "ghcr.io/magrhino/wudup:latest\nrepo/app:latest\n",
            encoding="utf-8",
        )

        result = self.run_updates(input_text="")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Skipped WUDup self-update", result.stdout)
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(self.updater_log.exists())
    def test_self_update_dry_run_reports_without_invoking_updater(self) -> None:
        self.wud_file.write_text(
            "ghcr.io/magrhino/wudup:latest\n",
            encoding="utf-8",
        )

        result = self.run_updates("--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("WUDup self-update detected", result.stdout)
        self.assertIn("not running WUDup self-update", result.stdout)
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(self.updater_log.exists())
    def test_no_self_update_flag_leaves_default_update_order(self) -> None:
        self.wud_file.write_text(
            "ghcr.io/magrhino/wudup:latest\n",
            encoding="utf-8",
        )

        result = self.run_updates("--yes", "--no-self-update")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("WUDup self-update detected", result.stdout)
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertNotIn("--only-lines", updater_log)
    def test_self_update_env_can_disable_preflight(self) -> None:
        self.wud_file.write_text("wudup\n", encoding="utf-8")

        result = self.run_updates(
            "--yes",
            env_overrides={"WUDUP_SELF_UPDATE": "0"},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("WUDup self-update detected", result.stdout)
        self.assertNotIn(
            "--only-lines",
            self.updater_log.read_text(encoding="utf-8"),
        )
    def test_github_release_self_update_pulls_release_image_and_exits(self) -> None:
        status, stdout, stderr = self._run_github_release_self_update(
            "ghcr.io/magrhino/wudup:latest",
            env_overrides={"DOCKER_HOST": "tcp://docker:2375"},
        )

        self.assertEqual(status, 0, stderr.getvalue() + stdout.getvalue())
        self.assertFalse(self.updater_log.exists())
        self.assertIn(
            "pull ghcr.io/magrhino/wudup:latest",
            self.docker_log.read_text(encoding="utf-8"),
        )
        self.assertFalse(self.sudo_log.exists())
        self.assertIn(
            "Please restart the wudup container before running updates again.",
            stdout.getvalue(),
        )
    def test_github_release_self_update_rewrites_pinned_release_tag(self) -> None:
        status, stdout, stderr = self._run_github_release_self_update(
            "ghcr.io/magrhino/wudup:v0.12.2",
            env_overrides={"FAKE_UPDATER_LOG_WUD_CONTENT": "1"},
        )

        self.assertEqual(status, 0, stderr.getvalue() + stdout.getvalue())
        log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn(
            "WUD_CONTENT=ghcr.io/magrhino/wudup:v0.12.2 tag=v999.0.0|",
            log,
        )
        arg_lines = _updater_arg_lines(log)
        self.assertEqual(len(arg_lines), 1)
        self.assertIn("--allow-tag-updates", arg_lines[0])
        self.assertIn("--yes", arg_lines[0])
        self.assertNotIn(f"--file {self.wud_file}", arg_lines[0])
        self.assertFalse(self.docker_log.exists())
        self.assertNotIn(
            "Please restart the wudup container before running updates again.",
            stdout.getvalue(),
        )
    def test_github_release_self_update_rewrites_pinned_trivy_release_tag(
        self,
    ) -> None:
        status, stdout, stderr = self._run_github_release_self_update(
            "ghcr.io/magrhino/wudup:v0.12.2-trivy",
            env_overrides={"FAKE_UPDATER_LOG_WUD_CONTENT": "1"},
        )

        self.assertEqual(status, 0, stderr.getvalue() + stdout.getvalue())
        log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn(
            "WUD_CONTENT=ghcr.io/magrhino/wudup:v0.12.2-trivy tag=v999.0.0-trivy|",
            log,
        )
        arg_lines = _updater_arg_lines(log)
        self.assertEqual(len(arg_lines), 1)
        self.assertIn("--allow-tag-updates", arg_lines[0])
        self.assertFalse(self.docker_log.exists())
        self.assertNotIn(
            "Please restart the wudup container before running updates again.",
            stdout.getvalue(),
        )
    def test_github_release_self_update_failed_pull_exits_without_restart_message(
        self,
    ) -> None:
        status, stdout, stderr = self._run_github_release_self_update(
            "ghcr.io/magrhino/wudup:latest",
            env_overrides={"FAKE_DOCKER_PULL_RETURN": "17"},
        )

        self.assertEqual(status, 17, stderr.getvalue() + stdout.getvalue())
        self.assertFalse(self.updater_log.exists())
        self.assertIn(
            "pull ghcr.io/magrhino/wudup:latest",
            self.docker_log.read_text(encoding="utf-8"),
        )
        self.assertNotIn(
            "Please restart the wudup container before running updates again.",
            stdout.getvalue(),
        )

    def test_github_release_self_update_fails_when_image_variant_is_unknown(self) -> None:
        for current_image in (
            "",
            f"ghcr.io/magrhino/wudup@sha256:{'a' * 64}",
            f"sha256:{'b' * 64}",
        ):
            with self.subTest(current_image=current_image):
                status, stdout, stderr = self._run_github_release_self_update(
                    current_image
                )

                self.assertEqual(status, 1)
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn("cannot preserve the image variant", stderr.getvalue())

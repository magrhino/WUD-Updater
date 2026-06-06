from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from wud_updater.updates import run_updates_from_namespace


class PythonUpdatesWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="wud-python-updates.")
        self.root = Path(self.tmp.name)
        self.repo_root = Path(__file__).resolve().parents[1]
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        self.wud_file = self.root / "images.todo"
        self.updater = self.root / "updater"
        self.sudo_log = self.root / "sudo.log"
        self.updater_log = self.root / "updater.log"
        self.docker_log = self.root / "docker.log"
        self._write_fakes()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_updates(
        self,
        *args: str,
        input_text: str | None = None,
        env_overrides: dict[str, str] | None = None,
        command: list[str] | None = None,
        include_file: bool = True,
        include_pythonpath: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("WUD_UPDATER_PYTHON", None)
        env_defaults = {
            "PATH": f"{self.fake_bin}:{env.get('PATH', '')}",
            "WUD_UPDATER": str(self.updater),
            "WUD_UPDATER_CONFIG": str(self.root / "missing-env"),
            "FAKE_SUDO_LOG": str(self.sudo_log),
            "FAKE_UPDATER_LOG": str(self.updater_log),
            "FAKE_WUD_FILE": str(self.wud_file),
            "WUD_UPDATER_BANNER": "false",
            "WUD_UPDATER_RELEASE_CHECK": "false",
        }
        if include_pythonpath:
            env_defaults["PYTHONPATH"] = str(self.repo_root / "src")
        else:
            env.pop("PYTHONPATH", None)
        env.update(env_defaults)
        if env_overrides is not None:
            env.update(env_overrides)

        if command is None:
            command = [sys.executable, "-m", "wud_updater.cli", "updates"]
        if include_file:
            command = [*command, "--file", str(self.wud_file)]
        command = [*command, *args]

        return subprocess.run(
            command,
            env=env,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    def test_dry_run_does_not_invoke_updater(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates("--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(self.updater_log.exists())
        self.assertIn("Dry-run mode: not running updates", result.stdout)

    def test_self_update_yes_runs_wud_entry_before_remaining_updates(self) -> None:
        self.wud_file.write_text(
            "ghcr.io/magrhino/wud-updater:latest\nrepo/app:latest\n",
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
            "ghcr.io/magrhino/wud-updater:1.0 tag=2.0\nrepo/app:latest\n",
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
            "ghcr.io/magrhino/wud-updater:latest\nrepo/app:latest\n",
            encoding="utf-8",
        )

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="n\ns\n2\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Skipped WUD-Updater self-update", result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        self.assertIn("--only-lines 2 --yes", sudo_log)
        self.assertNotIn("--only-lines 1", sudo_log)

    def test_self_update_eof_declines_without_invoking_updater(self) -> None:
        self.wud_file.write_text(
            "ghcr.io/magrhino/wud-updater:latest\nrepo/app:latest\n",
            encoding="utf-8",
        )

        result = self.run_updates(input_text="")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Skipped WUD-Updater self-update", result.stdout)
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(self.updater_log.exists())

    def test_self_update_dry_run_reports_without_invoking_updater(self) -> None:
        self.wud_file.write_text(
            "ghcr.io/magrhino/wud-updater:latest\n",
            encoding="utf-8",
        )

        result = self.run_updates("--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("WUD-Updater self-update detected", result.stdout)
        self.assertIn("not running WUD-Updater self-update", result.stdout)
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(self.updater_log.exists())

    def test_no_self_update_flag_leaves_default_update_order(self) -> None:
        self.wud_file.write_text(
            "ghcr.io/magrhino/wud-updater:latest\n",
            encoding="utf-8",
        )

        result = self.run_updates("--yes", "--no-self-update")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("WUD-Updater self-update detected", result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        self.assertNotIn("--only-lines", sudo_log)

    def test_self_update_env_can_disable_preflight(self) -> None:
        self.wud_file.write_text("wud-updater\n", encoding="utf-8")

        result = self.run_updates(
            "--yes",
            env_overrides={"WUD_UPDATER_SELF_UPDATE": "0"},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("WUD-Updater self-update detected", result.stdout)
        self.assertNotIn(
            "--only-lines",
            self.updater_log.read_text(encoding="utf-8"),
        )

    def test_github_release_self_update_pulls_release_image_and_exits(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.fake_bin}:{env.get('PATH', '')}",
                "WUD_UPDATER": str(self.updater),
                "WUD_UPDATER_CONFIG": str(self.root / "missing-env"),
                "FAKE_SUDO_LOG": str(self.sudo_log),
                "FAKE_UPDATER_LOG": str(self.updater_log),
                "FAKE_DOCKER_LOG": str(self.docker_log),
                "WUD_UPDATER_BANNER": "0",
                "WUD_UPDATER_RELEASE_CHECK": "1",
                "HOSTNAME": "wud-updater-1",
            }
        )
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
                "wud_updater.self_update.fetch_latest_release_tag",
                return_value="v999.0.0",
            ),
            mock.patch(
                "wud_updater.self_update.current_container_image",
                return_value="ghcr.io/magrhino/wud-updater:latest",
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = run_updates_from_namespace(
                args,
                repo_root=self.repo_root,
                environ=env,
            )

        self.assertEqual(status, 0, stderr.getvalue() + stdout.getvalue())
        self.assertFalse(self.updater_log.exists())
        self.assertIn(
            "pull ghcr.io/magrhino/wud-updater:latest",
            self.docker_log.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "docker pull ghcr.io/magrhino/wud-updater:latest",
            self.sudo_log.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "Please restart the wud-updater container before running updates again.",
            stdout.getvalue(),
        )

    def test_github_release_self_update_rewrites_pinned_release_tag(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.fake_bin}:{env.get('PATH', '')}",
                "WUD_UPDATER": str(self.updater),
                "WUD_UPDATER_CONFIG": str(self.root / "missing-env"),
                "FAKE_SUDO_LOG": str(self.sudo_log),
                "FAKE_UPDATER_LOG": str(self.updater_log),
                "FAKE_DOCKER_LOG": str(self.docker_log),
                "FAKE_UPDATER_LOG_WUD_CONTENT": "1",
                "WUD_UPDATER_BANNER": "0",
                "WUD_UPDATER_RELEASE_CHECK": "1",
                "HOSTNAME": "wud-updater-1",
            }
        )
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
                "wud_updater.self_update.fetch_latest_release_tag",
                return_value="v999.0.0",
            ),
            mock.patch(
                "wud_updater.self_update.current_container_image",
                return_value="ghcr.io/magrhino/wud-updater:v0.12.2",
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = run_updates_from_namespace(
                args,
                repo_root=self.repo_root,
                environ=env,
            )

        self.assertEqual(status, 0, stderr.getvalue() + stdout.getvalue())
        log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn(
            "WUD_CONTENT=ghcr.io/magrhino/wud-updater:v0.12.2 tag=v999.0.0|",
            log,
        )
        arg_lines = _updater_arg_lines(log)
        self.assertEqual(len(arg_lines), 1)
        self.assertIn("--allow-tag-updates", arg_lines[0])
        self.assertIn("--yes", arg_lines[0])
        self.assertNotIn(f"--file {self.wud_file}", arg_lines[0])
        self.assertFalse(self.docker_log.exists())
        self.assertNotIn(
            "Please restart the wud-updater container before running updates again.",
            stdout.getvalue(),
        )

    def test_github_release_self_update_failed_pull_exits_without_restart_message(
        self,
    ) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.fake_bin}:{env.get('PATH', '')}",
                "WUD_UPDATER": str(self.updater),
                "WUD_UPDATER_CONFIG": str(self.root / "missing-env"),
                "FAKE_SUDO_LOG": str(self.sudo_log),
                "FAKE_UPDATER_LOG": str(self.updater_log),
                "FAKE_DOCKER_LOG": str(self.docker_log),
                "FAKE_DOCKER_PULL_RETURN": "17",
                "WUD_UPDATER_BANNER": "0",
                "WUD_UPDATER_RELEASE_CHECK": "1",
                "HOSTNAME": "wud-updater-1",
            }
        )
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
                "wud_updater.self_update.fetch_latest_release_tag",
                return_value="v999.0.0",
            ),
            mock.patch(
                "wud_updater.self_update.current_container_image",
                return_value="ghcr.io/magrhino/wud-updater:latest",
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = run_updates_from_namespace(
                args,
                repo_root=self.repo_root,
                environ=env,
            )

        self.assertEqual(status, 17, stderr.getvalue() + stdout.getvalue())
        self.assertFalse(self.updater_log.exists())
        self.assertIn(
            "pull ghcr.io/magrhino/wud-updater:latest",
            self.docker_log.read_text(encoding="utf-8"),
        )
        self.assertNotIn(
            "Please restart the wud-updater container before running updates again.",
            stdout.getvalue(),
        )

    def test_yes_invokes_configured_updater_through_sudo_env(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--yes",
            "--allow-tag-updates",
            "--base",
            str(self.root / "docker"),
            env_overrides={
                "OUT_UID": "1000",
                "OUT_GUID": "1001",
                "WUD_LOCK_TIMEOUT": "0",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn(
            "env OUT_UID=1000 OUT_GID=1001 WUD_LOCK_TIMEOUT=0 "
            f"{self.updater} --base {self.root / 'docker'} --file {self.wud_file} "
            "--log-dir ./logs --mode stop --max-wait 180 --allow-tag-updates --yes",
            sudo_log,
        )
        self.assertIn("OUT_UID=1000 OUT_GID=1001", updater_log)
        self.assertIn("--allow-tag-updates --yes", updater_log)

    def test_yes_preserves_db_path_through_sudo_env(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        db_path = self.root / "state" / "wud-updater.sqlite"

        result = self.run_updates(
            "--yes",
            env_overrides={"WUD_DB_PATH": str(db_path)},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn(f"env WUD_DB_PATH={db_path} {self.updater}", sudo_log)
        self.assertIn(f"WUD_DB_PATH={db_path}", updater_log)

    def test_yes_preserves_host_docker_base_through_sudo_env(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        host_base = self.root / "host-docker"

        result = self.run_updates(
            "--yes",
            env_overrides={"HOST_DOCKER_BASE": str(host_base)},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn(
            f"env HOST_DOCKER_BASE={host_base} {self.updater}",
            sudo_log,
        )
        self.assertIn(f"HOST_DOCKER_BASE={host_base}", updater_log)

    def test_yes_preserves_compose_ignore_paths_through_sudo_env(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--yes",
            env_overrides={"WUD_COMPOSE_IGNORE_PATHS": "old,archive/disabled"},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn(
            f"env WUD_COMPOSE_IGNORE_PATHS=old,archive/disabled {self.updater}",
            sudo_log,
        )
        self.assertIn(
            "WUD_COMPOSE_IGNORE_PATHS=old,archive/disabled",
            updater_log,
        )

    def test_no_updater_sudo_flag_invokes_updater_directly(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--yes",
            "--no-updater-sudo",
            "--base",
            str(self.root / "docker"),
            env_overrides={
                "OUT_UID": "1000",
                "OUT_GID": "1001",
                "WUD_LOCK_TIMEOUT": "0",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(self.sudo_log.exists())
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn("OUT_UID=1000 OUT_GID=1001 WUD_LOCK_TIMEOUT=0", updater_log)
        self.assertIn(
            f"--base {self.root / 'docker'} --file {self.wud_file} --log-dir ./logs",
            updater_log,
        )
        self.assertIn("Running Docker updates via: env OUT_UID=1000", result.stdout)

    def test_log_dir_cli_overrides_environment(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        cli_log_dir = self.root / "cli-logs"

        result = self.run_updates(
            "--yes",
            "--no-updater-sudo",
            "--log-dir",
            str(cli_log_dir),
            env_overrides={
                "WUD_LOG_DIR": str(self.root / "env-logs"),
                "WUD_UPDATER_USE_SUDO": "false",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(self.sudo_log.exists())
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn(f"--log-dir {cli_log_dir}", updater_log)
        self.assertNotIn("env-logs", updater_log)

    def test_no_updater_sudo_env_invokes_updater_directly(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--yes",
            env_overrides={"WUD_UPDATER_USE_SUDO": "false"},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(self.sudo_log.exists())
        self.assertIn("--yes", self.updater_log.read_text(encoding="utf-8"))

    def test_no_updater_sudo_fails_when_wud_file_is_unreadable(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.wud_file.chmod(0)

        try:
            result = self.run_updates("--dry-run", "--no-updater-sudo")
        finally:
            self.wud_file.chmod(0o600)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Cannot read WUD file without sudo", result.stderr)
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(self.updater_log.exists())

    def test_interactive_select_remove_passes_original_line_numbers(self) -> None:
        self.wud_file.write_text(
            "# comment\nrepo/app:one\n\nrepo/app:two\nrepo/app:three\n",
            encoding="utf-8",
        )

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1,3\ny\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        self.assertIn("--only-lines 2,5 --remove-lines-before-run 4 --yes", sudo_log)

    def test_interactive_tag_change_passes_original_line_number(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=wrong\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\nc\n3.0\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        self.assertIn(
            "--only-lines 1 --allow-tag-updates --tag-override 1=3.0 --yes",
            sudo_log,
        )
        self.assertIn("Selected tag update(s):", result.stdout)

    def test_interactive_tag_yes_keeps_wud_tag_without_override_prompt(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\ny\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        self.assertIn("--only-lines 1 --allow-tag-updates --yes", sudo_log)
        self.assertNotIn("--tag-override", sudo_log)
        self.assertIn("[y]es/[n]o/[c]hange", result.stdout)
        self.assertNotIn("Override tag for update", result.stdout)

    def test_interactive_tag_exclude_passes_line_and_recreate_flag(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\ne\ny\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        self.assertIn(
            "--only-lines 1 --exclude-tag-lines 1 --recreate-excluded-services --yes",
            sudo_log,
        )
        self.assertNotIn("--allow-tag-updates", sudo_log)
        self.assertNotIn("--tag-override", sudo_log)

    def test_interactive_tag_exclude_can_skip_recreate(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\ne\nn\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        self.assertIn("--only-lines 1 --exclude-tag-lines 1 --yes", sudo_log)
        self.assertNotIn("--recreate-excluded-services", sudo_log)

    def test_interactive_tag_exclude_selects_subset_of_tag_lines(self) -> None:
        self.wud_file.write_text(
            "\n".join(
                [
                    "repo/app:1.0 tag=2.0",
                    "repo/sidecar:latest",
                    "repo/db:1.0 tag=1.1",
                    "repo/cache:1.0 tag=1.2",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1-4\ne\n1,4\nn\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        self.assertIn(
            "--only-lines 1,2,3,4 --exclude-tag-lines 1,4 --yes",
            sudo_log,
        )
        self.assertNotIn("--allow-tag-updates", sudo_log)
        self.assertNotIn("--tag-override", sudo_log)

    def test_interactive_tag_exclude_rejects_non_tag_selection(self) -> None:
        self.wud_file.write_text(
            "\n".join(
                [
                    "repo/app:1.0 tag=2.0",
                    "repo/sidecar:latest",
                    "repo/db:1.0 tag=1.1",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1-3\ne\n2\n1,3\nn\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "Invalid tag selection. Use listed tag update numbers/ranges like 1,3-5.",
            result.stdout,
        )
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        self.assertIn(
            "--only-lines 1,2,3 --exclude-tag-lines 1,3 --yes",
            sudo_log,
        )
        self.assertNotIn("--allow-tag-updates", sudo_log)
        self.assertNotIn("--tag-override", sudo_log)

    def test_interactive_declined_tag_updates_do_not_enable_allow_flag(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\nn\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        self.assertIn("--only-lines 1 --yes", sudo_log)
        self.assertNotIn("--allow-tag-updates", sudo_log)
        self.assertNotIn("--tag-override", sudo_log)

    def test_interactive_untagged_tag_token_does_not_prompt(self) -> None:
        self.wud_file.write_text("repo/app tag=2.0\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="a\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("Selected tag update(s):", result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        self.assertNotIn("--allow-tag-updates", sudo_log)
        self.assertNotIn("--tag-override", sudo_log)

    def test_interactive_all_tag_override_aborts_when_snapshot_lines_change(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=wrong\n", encoding="utf-8")
        hook = self.root / "change-wud-file"
        hook.write_text(
            f"#!/usr/bin/env bash\nprintf 'repo/app:changed tag=wrong\\n' > {self.wud_file}\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="a\nc\n3.0\n",
            env_overrides={"FAKE_COLUMN_HOOK": str(hook)},
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "WUD file changed while selecting updates; please rerun updates.",
            result.stderr,
        )
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(Path(f"{self.wud_file}.lock").exists())

    def test_interactive_holds_wud_lock_for_updater_handoff(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\nn\n",
            env_overrides={"FAKE_UPDATER_ASSERT_LOCK": "1"},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "WUD_LOCK_HELD_BY_PARENT=1",
            self.updater_log.read_text(encoding="utf-8"),
        )
        self.assertFalse(Path(f"{self.wud_file}.lock").exists())

    def test_interactive_select_aborts_when_snapshot_lines_change(self) -> None:
        self.wud_file.write_text("repo/app:one\nrepo/app:two\n", encoding="utf-8")
        hook = self.root / "change-wud-file"
        hook.write_text(
            f"#!/usr/bin/env bash\nprintf 'repo/app:changed\\nrepo/app:two\\n' > {self.wud_file}\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        result = self.run_updates(
            "--base",
            str(self.root / "docker"),
            input_text="s\n1\nn\n",
            env_overrides={"FAKE_COLUMN_HOOK": str(hook)},
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "WUD file changed while selecting updates; please rerun updates.",
            result.stderr,
        )
        self.assertFalse(self.sudo_log.exists())
        self.assertFalse(Path(f"{self.wud_file}.lock").exists())

    def test_config_file_supplies_defaults(self) -> None:
        home = self.root / "home"
        docker_base = home / "from-config"
        docker_base.mkdir(parents=True)
        config_wud_file = docker_base / "images.todo"
        config_wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        config_file = home / ".config" / "wud-updater" / "env"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            "\n".join(
                [
                    'DOCKER_BASE="$HOME/from-config"',
                    'WUD_OUT_FILE="$DOCKER_BASE/images.todo"',
                    'WUD_UPDATE_MODE="live"',
                    'WUD_MAX_WAIT="7"',
                    f'WUD_UPDATER="{self.updater}"',
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_updates(
            "--yes",
            include_file=False,
            env_overrides={
                "HOME": str(home),
                "WUD_UPDATER_CONFIG": str(config_file),
                "FAKE_WUD_FILE": str(config_wud_file),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            f"{self.updater} --base {docker_base} --file {config_wud_file} "
            "--log-dir ./logs --mode live --max-wait 7 --yes",
            self.sudo_log.read_text(encoding="utf-8"),
        )

    def test_truenas_checks_skip_when_not_enabled(self) -> None:
        result = self.run_updates("--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("TrueNAS System Update", result.stdout)
        self.assertNotIn("TrueNAS Alerts", result.stdout)

    def test_truenas_check_runs_helper_container_and_prints_status(self) -> None:
        docker_log = self.root / "docker.log"

        result = self.run_updates(
            "--dry-run",
            env_overrides={
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "wud-updater-1",
                "FAKE_DOCKER_LOG": str(docker_log),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("⚠️  System update available!", result.stdout)
        self.assertIn("25.10.1", result.stdout)
        self.assertIn("Pool needs attention", result.stdout)
        docker_calls = docker_log.read_text(encoding="utf-8")
        self.assertIn("container inspect wud-updater-1", docker_calls)
        self.assertIn(
            "run --rm --pull never --network none --read-only --cap-drop ALL "
            "--security-opt no-new-privileges",
            docker_calls,
        )
        self.assertNotIn("-v wud-out:", docker_calls)
        self.assertNotIn("WUD_OUT_FILE=", docker_calls)
        self.assertIn(
            "--mount type=bind,src=/var/run/middleware,"
            "dst=/var/run/middleware,readonly",
            docker_calls,
        )
        self.assertNotIn("-v /var/run/middleware:/var/run/middleware:ro", docker_calls)
        self.assertIn("wud-updater:test truenas-status-export", docker_calls)
        self.assertNotIn("--volumes-from", docker_calls)
        self.assertNotIn("--uri", docker_calls)
        self.assertNotIn("-K", docker_calls)

    def test_truenas_helper_failure_reports_unreachable_without_failing(self) -> None:
        result = self.run_updates(
            "--dry-run",
            env_overrides={
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "wud-updater-1",
                "FAKE_DOCKER_RUN_RETURN": "2",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "TrueNAS not reachable; skipping system update check.",
            result.stdout,
        )
        self.assertIn("docker run exited 2", result.stdout)
        self.assertIn("TrueNAS not reachable; skipping alert check.", result.stdout)

    def test_truenas_inspect_failure_reports_unreachable_without_failing(self) -> None:
        result = self.run_updates(
            "--dry-run",
            env_overrides={
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "wud-updater-1",
                "FAKE_DOCKER_INSPECT_RETURN": "2",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "TrueNAS not reachable; skipping system update check.",
            result.stdout,
        )
        self.assertIn("docker inspect exited 2", result.stdout)
        self.assertIn("TrueNAS not reachable; skipping alert check.", result.stdout)

    def test_truenas_malformed_helper_status_reports_unreachable(self) -> None:
        result = self.run_updates(
            "--dry-run",
            env_overrides={
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "wud-updater-1",
                "FAKE_DOCKER_STATUS_RESPONSE": "invalid",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "TrueNAS not reachable; skipping system update check.",
            result.stdout,
        )
        self.assertIn("invalid JSON response", result.stdout)

    def test_truenas_status_export_uses_local_midclt_without_api_flags(self) -> None:
        key_file = self.root / "truenas-api-key"
        key_file.write_text("super-secret-api-key\n", encoding="utf-8")
        midclt_log = self.root / "midclt.log"

        result = self.run_updates(
            command=[sys.executable, "-m", "wud_updater.cli", "truenas-status-export"],
            include_file=False,
            env_overrides={
                "WUD_OUT_FILE": str(self.wud_file),
                "FAKE_MIDCLT_LOG": str(midclt_log),
                "TRUENAS_API_URI": "wss://truenas.example.local/api/current",
                "TRUENAS_API_KEY_FILE": str(key_file),
                "TRUENAS_API_USERNAME": "admin",
                "TRUENAS_API_INSECURE": "1",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        midclt_calls = midclt_log.read_text(encoding="utf-8")
        self.assertIn("call update.status", midclt_calls)
        self.assertIn("call alert.list", midclt_calls)
        self.assertNotIn("--uri", midclt_calls)
        self.assertNotIn("-K", midclt_calls)
        self.assertNotIn(str(key_file), midclt_calls)
        self.assertNotIn("super-secret-api-key", result.stdout)
        self.assertNotIn("super-secret-api-key", result.stderr)
        self.assertNotIn("super-secret-api-key", midclt_calls)
        self.assertFalse((self.root / "truenas-status.json").exists())
        status_payload = json.loads(result.stdout)
        self.assertTrue(status_payload["update"]["ok"])
        self.assertTrue(status_payload["alerts"]["ok"])
        self.assertEqual(
            status_payload["update"]["data"],
            {"status": "AVAILABLE", "version": "25.10.1"},
        )
        self.assertEqual(status_payload["alerts"]["data"], ["Pool needs attention"])
        self.assertNotIn("private-update-detail", result.stdout)
        self.assertNotIn("private-alert-arg", result.stdout)

    def test_truenas_update_status_up_to_date(self) -> None:
        result = self.run_updates(
            "--dry-run",
            env_overrides={
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "wud-updater-1",
                "FAKE_TRUENAS_UPDATE_STATUS": "unavailable",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("✅ System up to date", result.stdout)

    def test_truenas_update_status_error_is_reported_without_failing(self) -> None:
        result = self.run_updates(
            "--dry-run",
            env_overrides={
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "wud-updater-1",
                "FAKE_TRUENAS_UPDATE_STATUS": "error",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("TrueNAS update status error: update train failed", result.stdout)

    def test_truenas_alert_status_no_active_alerts(self) -> None:
        result = self.run_updates(
            "--dry-run",
            env_overrides={
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "wud-updater-1",
                "FAKE_TRUENAS_ALERT_STATUS": "none",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("✅ No active alerts", result.stdout)

    def test_truenas_status_export_records_midclt_failure(self) -> None:
        result = self.run_updates(
            command=[sys.executable, "-m", "wud_updater.cli", "truenas-status-export"],
            include_file=False,
            env_overrides={
                "WUD_OUT_FILE": str(self.wud_file),
                "FAKE_MIDCLT_RETURN": "2",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse((self.root / "truenas-status.json").exists())
        status_payload = json.loads(result.stdout)
        self.assertFalse(status_payload["update"]["ok"])
        self.assertEqual(status_payload["update"]["reason"], "midclt exited 2")

    def test_bin_updates_dispatches_python_wrapper_by_default(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--dry-run",
            command=[str(self.repo_root / "bin" / "updates")],
            env_overrides={"PYTHON_BIN": sys.executable},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Dry-run mode: not running updates", result.stdout)
        self.assertFalse(self.sudo_log.exists())

    def test_bin_updates_accepts_explicit_true(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--dry-run",
            command=[str(self.repo_root / "bin" / "updates")],
            env_overrides={
                "WUD_UPDATER_PYTHON": "true",
                "PYTHON_BIN": sys.executable,
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Dry-run mode: not running updates", result.stdout)
        self.assertFalse(self.sudo_log.exists())

    def test_bin_updates_opt_in_accepts_legacy_one(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--dry-run",
            command=[str(self.repo_root / "bin" / "updates")],
            env_overrides={
                "WUD_UPDATER_PYTHON": "1",
                "PYTHON_BIN": sys.executable,
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Dry-run mode: not running updates", result.stdout)
        self.assertFalse(self.sudo_log.exists())

    def test_bin_updates_default_resolves_installed_symlink(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        installed_bin = self.root / "installed-bin"
        installed_bin.mkdir()
        installed_updates = installed_bin / "updates"
        installed_updates.symlink_to(self.repo_root / "bin" / "updates")

        result = self.run_updates(
            "--dry-run",
            command=[str(installed_updates)],
            env_overrides={"PYTHON_BIN": sys.executable},
            include_pythonpath=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Dry-run mode: not running updates", result.stdout)
        self.assertFalse(self.sudo_log.exists())

    def test_bin_updates_config_file_is_sourced_before_python_dispatch(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        config_file = self.root / "host-env"
        config_file.write_text(
            "\n".join(
                [
                    f'PYTHON_BIN="{sys.executable}"',
                    "WUD_UPDATER_USE_SUDO=false",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_updates(
            "--dry-run",
            "--no-updater-sudo",
            command=[str(self.repo_root / "bin" / "updates")],
            env_overrides={"WUD_UPDATER_CONFIG": str(config_file)},
            include_pythonpath=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Dry-run mode: not running updates", result.stdout)
        self.assertFalse(self.sudo_log.exists())

    def test_bin_updates_default_accepts_no_updater_sudo(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--yes",
            "--no-updater-sudo",
            command=[str(self.repo_root / "bin" / "updates")],
            env_overrides={"PYTHON_BIN": sys.executable},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(self.sudo_log.exists())
        self.assertIn("--yes", self.updater_log.read_text(encoding="utf-8"))

    def test_bin_updates_zero_flag_uses_legacy_bash_fallback(self) -> None:
        result = self.run_updates(
            "--dry-run",
            "--no-updater-sudo",
            command=[str(self.repo_root / "bin" / "updates")],
            env_overrides={"WUD_UPDATER_PYTHON": "0"},
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown argument: --no-updater-sudo", result.stderr)

    def test_bin_updates_invalid_python_flag_fails(self) -> None:
        result = self.run_updates(
            "--dry-run",
            command=[str(self.repo_root / "bin" / "updates")],
            env_overrides={"WUD_UPDATER_PYTHON": "maybe"},
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "WUD_UPDATER_PYTHON must be one of",
            result.stderr,
        )
        self.assertEqual(result.stdout, "")

    def _write_fakes(self) -> None:
        self._write_executable(
            self.fake_bin / "column",
            """#!/usr/bin/env bash
if [[ -n "${FAKE_COLUMN_LOCK_LOG:-}" ]]; then
  if [[ -d "${FAKE_WUD_FILE:?FAKE_WUD_FILE is required}.lock" ]]; then
    printf 'present\\n' >> "$FAKE_COLUMN_LOCK_LOG"
  else
    printf 'missing\\n' >> "$FAKE_COLUMN_LOCK_LOG"
  fi
fi
cat
if [[ -n "${FAKE_COLUMN_HOOK:-}" ]]; then
  "$FAKE_COLUMN_HOOK"
fi
""",
        )
        self._write_executable(
            self.fake_bin / "sudo",
            """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "${FAKE_SUDO_LOG:?FAKE_SUDO_LOG is required}"
"$@"
""",
        )
        self._write_executable(
            self.fake_bin / "docker",
            """#!/usr/bin/env bash
if [[ -n "${FAKE_DOCKER_LOG:-}" ]]; then
  printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
fi
if [[ "$1" == "pull" ]]; then
  exit "${FAKE_DOCKER_PULL_RETURN:-0}"
fi
if [[ "$1 $2" == "container inspect" ]]; then
  if [[ "${FAKE_DOCKER_INSPECT_RETURN:-0}" != "0" ]]; then
    exit "$FAKE_DOCKER_INSPECT_RETURN"
  fi
  out_dir="$(dirname "${FAKE_WUD_FILE:?FAKE_WUD_FILE is required}")"
  printf '[{"Config":{"Image":"wud-updater:test"},"Mounts":[{"Type":"volume","Name":"wud-out","Destination":"%s"}]}]\\n' "$out_dir"
  exit 0
fi
if [[ "$1" == "run" ]]; then
  if [[ "${FAKE_DOCKER_RUN_RETURN:-0}" != "0" ]]; then
    exit "$FAKE_DOCKER_RUN_RETURN"
  fi
  if [[ "${FAKE_DOCKER_STATUS_RESPONSE:-}" == "invalid" ]]; then
    printf 'not json\\n'
    exit 0
  fi
  case "${FAKE_TRUENAS_UPDATE_STATUS:-available}" in
    unavailable)
      update_data='{"status":"UNAVAILABLE"}'
      ;;
    error)
      update_data='{"status":"ERROR","reason":"update train failed"}'
      ;;
    *)
      update_data='{"status":"AVAILABLE","version":"25.10.1"}'
      ;;
  esac
  case "${FAKE_TRUENAS_ALERT_STATUS:-active}" in
    none)
      alert_data='[]'
      ;;
    *)
      alert_data='["Pool needs attention"]'
      ;;
  esac
  printf '{"update":{"ok":true,"data":%s,"reason":""},"alerts":{"ok":true,"data":%s,"reason":""}}\\n' "$update_data" "$alert_data"
  exit 0
fi
exit 1
""",
        )
        self._write_executable(
            self.fake_bin / "midclt",
            """#!/usr/bin/env bash
if [[ -n "${FAKE_MIDCLT_LOG:-}" ]]; then
  printf '%s\\n' "$*" >> "$FAKE_MIDCLT_LOG"
fi
if [[ "${FAKE_MIDCLT_RETURN:-0}" != "0" ]]; then
  exit "$FAKE_MIDCLT_RETURN"
fi
if [[ "${FAKE_MIDCLT_RESPONSE:-}" == "empty" ]]; then
  exit 0
fi
if [[ "${FAKE_MIDCLT_RESPONSE:-}" == "invalid" ]]; then
  printf 'not json\\n'
  exit 0
fi
if [[ "${FAKE_MIDCLT_RESPONSE:-}" == "timeout" ]]; then
  sleep 1
fi
case "$*" in
  *"call update.status")
    case "${FAKE_TRUENAS_UPDATE_STATUS:-available}" in
      unavailable)
        printf '{"code":"NORMAL","status":{"new_version":null},"error":null}\\n'
        ;;
      error)
        printf '{"code":"ERROR","status":null,"error":{"reason":"update train failed"}}\\n'
        ;;
      *)
        printf '{"code":"NORMAL","status":{"new_version":{"version":"25.10.1"}},"error":null,"private":"private-update-detail"}\\n'
        ;;
    esac
    ;;
  *"call alert.list")
    case "${FAKE_TRUENAS_ALERT_STATUS:-active}" in
      none)
        printf '[]\\n'
        ;;
      *)
        printf '[{"dismissed":false,"formatted":"Pool needs attention","args":{"private":"private-alert-arg"},"mail":{"to":"private@example.test"}},{"dismissed":true,"formatted":"Dismissed alert"}]\\n'
        ;;
    esac
    ;;
esac
""",
        )
        self._write_executable(
            self.fake_bin / "jq",
            """#!/usr/bin/env bash
filter="${*: -1}"
if [[ "$filter" == ".status" ]]; then
  printf 'AVAILABLE\\n'
else
  printf 'Pool needs attention\\n'
fi
""",
        )
        self._write_executable(
            self.updater,
            """#!/usr/bin/env bash
args=("$@")
wud_file=""
only_lines=""
while (($#)); do
  case "$1" in
    --file)
      wud_file="${2:-}"
      shift 2
      ;;
    --only-lines)
      only_lines="${2:-}"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
printf 'OUT_UID=%s OUT_GID=%s WUD_LOCK_TIMEOUT=%s WUD_LOCK_HELD_BY_PARENT=%s WUD_DB_PATH=%s HOST_DOCKER_BASE=%s WUD_COMPOSE_IGNORE_PATHS=%s\\n' "${OUT_UID:-}" "${OUT_GID:-}" "${WUD_LOCK_TIMEOUT:-}" "${WUD_LOCK_HELD_BY_PARENT:-}" "${WUD_DB_PATH:-}" "${HOST_DOCKER_BASE:-}" "${WUD_COMPOSE_IGNORE_PATHS:-}" >> "${FAKE_UPDATER_LOG:?FAKE_UPDATER_LOG is required}"
if [[ "${FAKE_UPDATER_ASSERT_LOCK:-}" = "1" ]]; then
  if [[ "${WUD_LOCK_HELD_BY_PARENT:-}" != "1" ]]; then
    printf 'missing WUD_LOCK_HELD_BY_PARENT\\n' >> "$FAKE_UPDATER_LOG"
    exit 21
  fi
  if [[ -z "$wud_file" || ! -d "${wud_file}.lock" ]]; then
    printf 'missing WUD file lock\\n' >> "$FAKE_UPDATER_LOG"
    exit 22
  fi
fi
if [[ -n "$wud_file" && "${FAKE_UPDATER_LOG_WUD_CONTENT:-}" = "1" ]]; then
  printf 'WUD_CONTENT=%s\\n' "$(tr '\\n' '|' < "$wud_file")" >> "${FAKE_UPDATER_LOG:?FAKE_UPDATER_LOG is required}"
fi
if [[ -n "$wud_file" && -n "$only_lines" && "${FAKE_UPDATER_REMOVE_ONLY_LINES:-}" = "1" ]]; then
  tmp="${wud_file}.fake-update.$$"
  awk -v spec="$only_lines" 'BEGIN {
    split(spec, items, ",")
    for (idx in items) {
      if (items[idx] != "") {
        remove[items[idx]] = 1
      }
    }
  }
  !(FNR in remove)' "$wud_file" > "$tmp"
  mv "$tmp" "$wud_file"
fi
printf '%s\\n' "${args[*]}" >> "${FAKE_UPDATER_LOG:?FAKE_UPDATER_LOG is required}"
exit 0
""",
        )

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)


def _updater_arg_lines(log: str) -> list[str]:
    return [line for line in log.splitlines() if line.startswith("--base ")]


if __name__ == "__main__":
    unittest.main()

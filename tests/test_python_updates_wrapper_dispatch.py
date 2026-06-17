from __future__ import annotations

import sys


from tests.updates_wrapper_helpers import UpdatesWrapperTestCase

class UpdatesWrapperDispatchTests(UpdatesWrapperTestCase):
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
    def test_bin_updates_config_file_argument_is_sourced_by_python_cli(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        default_config_file = self.root / "default-env"
        default_config_file.write_text(
            "\n".join(
                [
                    "export WUD_UPDATER_USE_SUDO=true",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        config_file = self.root / "host-env"
        config_file.write_text(
            "\n".join(
                [
                    "WUD_UPDATER_USE_SUDO=false",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_updates(
            "--yes",
            "--config-file",
            str(config_file),
            command=[str(self.repo_root / "bin" / "updates")],
            env_overrides={
                "PYTHON_BIN": sys.executable,
                "WUD_UPDATER_CONFIG": str(default_config_file),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Update script completed", result.stdout)
        self.assertFalse(self.sudo_log.exists())
        self.assertIn("--yes", self.updater_log.read_text(encoding="utf-8"))
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
    def test_bin_updates_auto_run_alias_invokes_updater(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--auto-run",
            "--no-updater-sudo",
            command=[str(self.repo_root / "bin" / "updates")],
            env_overrides={"PYTHON_BIN": sys.executable},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(self.sudo_log.exists())
        self.assertIn("--yes", self.updater_log.read_text(encoding="utf-8"))
    def test_bin_updates_legacy_python_false_does_not_disable_python(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--dry-run",
            "--no-updater-sudo",
            command=[str(self.repo_root / "bin" / "updates")],
            env_overrides={
                "WUD_UPDATER_PYTHON": "false",
                "PYTHON_BIN": sys.executable,
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Dry-run mode: not running updates", result.stdout)
        self.assertFalse(self.sudo_log.exists())
    def test_updates_help_describes_admin_convenience(self) -> None:
        result = self.run_updates(
            "--help",
            command=[str(self.repo_root / "bin" / "updates")],
            env_overrides={"PYTHON_BIN": sys.executable},
            include_file=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Admin convenience", result.stdout)
        self.assertIn(
            "CLI/WebUI feature parity is not a project goal",
            result.stdout,
        )

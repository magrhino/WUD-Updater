from __future__ import annotations



from tests.updates_wrapper_helpers import UpdatesWrapperTestCase

class UpdatesWrapperInvocationTests(UpdatesWrapperTestCase):
    def test_yes_invokes_configured_updater_through_sudo_env(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")

        result = self.run_updates(
            "--yes",
            "--allow-tag-updates",
            "--base",
            str(self.root / "docker"),
            env_overrides={
                "OUT_UID": "1000",
                "OUT_GID": "1001",
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
        db_path = self.root / "state" / "wudup.sqlite"

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
                "WUDUP_USE_SUDO": "false",
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
            env_overrides={"WUDUP_USE_SUDO": "false"},
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

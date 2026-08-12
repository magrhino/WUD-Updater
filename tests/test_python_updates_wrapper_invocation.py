from __future__ import annotations

import subprocess

from tests.updates_wrapper_helpers import UpdatesWrapperTestCase


class UpdatesWrapperInvocationTests(UpdatesWrapperTestCase):
    def _write_pending_update(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
    def _run_standard_base_update(
        self,
        *args: str,
        env_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "OUT_UID": "1000",
            "OUT_GID": "1001",
            "WUD_LOCK_TIMEOUT": "0",
        }
        if env_overrides is not None:
            env.update(env_overrides)

        self._write_pending_update()
        return self.run_updates(
            "--yes",
            *args,
            "--base",
            str(self.root / "docker"),
            env_overrides=env,
        )
    def _assert_standard_direct_update(
        self,
        result: subprocess.CompletedProcess[str],
    ) -> str:
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(self.sudo_log.exists())
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn("OUT_UID=1000 OUT_GID=1001 WUD_LOCK_TIMEOUT=0", updater_log)
        self.assertIn(
            f"--base {self.root / 'docker'} --file {self.wud_file} --log-dir ./logs",
            updater_log,
        )
        return updater_log
    def _assert_sudo_env_passthrough(self, name: str, value: str) -> None:
        self._write_pending_update()

        result = self.run_updates(
            "--yes",
            env_overrides={
                name: value,
                "WUDUP_USE_SUDO": "true",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        sudo_log = self.sudo_log.read_text(encoding="utf-8")
        updater_log = self.updater_log.read_text(encoding="utf-8")
        self.assertIn(f"env {name}={value} {self.updater}", sudo_log)
        self.assertIn(f"{name}={value}", updater_log)
    def test_yes_invokes_configured_updater_through_sudo_env(self) -> None:
        result = self._run_standard_base_update(
            "--allow-tag-updates",
            env_overrides={
                "WUDUP_USE_SUDO": "true",
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
    def test_yes_invokes_configured_updater_directly_by_default(self) -> None:
        result = self._run_standard_base_update()

        self._assert_standard_direct_update(result)
    def test_no_updater_sudo_overrides_env_var(self) -> None:
        result = self._run_standard_base_update(
            "--allow-tag-updates",
            "--no-updater-sudo",
            env_overrides={
                "WUDUP_USE_SUDO": "true",
            },
        )

        updater_log = self._assert_standard_direct_update(result)
        self.assertIn(
            "--log-dir ./logs --mode stop --max-wait 180 --allow-tag-updates --yes",
            updater_log,
        )
    def test_yes_preserves_db_path_through_sudo_env(self) -> None:
        db_path = self.root / "state" / "wudup.sqlite"

        self._assert_sudo_env_passthrough("WUD_DB_PATH", str(db_path))
    def test_yes_preserves_host_docker_base_through_sudo_env(self) -> None:
        host_base = self.root / "host-docker"

        self._assert_sudo_env_passthrough("HOST_DOCKER_BASE", str(host_base))
    def test_yes_preserves_compose_ignore_paths_through_sudo_env(self) -> None:
        self._assert_sudo_env_passthrough(
            "WUD_COMPOSE_IGNORE_PATHS",
            "old,archive/disabled",
        )
    def test_no_updater_sudo_flag_invokes_updater_directly(self) -> None:
        result = self._run_standard_base_update("--no-updater-sudo")

        self._assert_standard_direct_update(result)
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

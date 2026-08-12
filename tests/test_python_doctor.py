from __future__ import annotations

import argparse
import concurrent.futures
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from wudup.command import CommandResult
from wudup.doctor import (
    REQUIRED_WUD_SCRIPTS,
    Doctor,
    DoctorOptions,
    _write_probe,
    doctor_result_from_namespace,
    run_doctor_from_namespace,
)
from wudup.truenas import DEFAULT_TRUENAS_STATUS_TIMEOUT


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="wud-doctor.")
        self.root = Path(self.tmp.name)
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        self.docker_base = self.root / "docker"
        self.stack_dir = self.docker_base / "app"
        self.stack_dir.mkdir(parents=True)
        self.out_dir = self.root / "out"
        self.out_dir.mkdir()
        self.log_dir = self.root / "logs"
        self.log_dir.mkdir()
        self.scripts_dir = self.root / "managed-wud"
        self.scripts_dir.mkdir()
        self.app_dir = self.root / "app"
        self.packaged_scripts = self.app_dir / "wud"
        self.packaged_scripts.mkdir(parents=True)
        self.updater = self.app_dir / "bin" / "docker-update-from-wud"
        self.updater.parent.mkdir(parents=True)
        self.updater.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        self.updater.chmod(0o755)
        self._write_docker()
        self._write_packaged_scripts()
        self._write_compose()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_doctor_passes_with_container_prerequisites(self) -> None:
        status, stdout = self._run_doctor()

        self.assertEqual(status, 0, stdout)
        self.assertIn("[PASS] docker cli: Docker version 28.0.0", stdout)
        self.assertIn("[PASS] compose discovery: 1 stack(s) rendered", stdout)
        self.assertIn("[WARN] TrueNAS status helper", stdout)
        self.assertIn("Result: 0 failure(s)", stdout)

    def test_doctor_fails_when_required_packaged_script_is_missing(self) -> None:
        for script_name in REQUIRED_WUD_SCRIPTS:
            with self.subTest(script_name=script_name):
                self._write_packaged_scripts()
                (self.packaged_scripts / script_name).unlink()

                status, stdout = self._run_doctor()

                self.assertEqual(status, 1, stdout)
                self.assertIn(
                    f"[FAIL] packaged WUD scripts: {script_name} missing",
                    stdout,
                )

    def test_doctor_fails_when_no_compose_stacks_are_found(self) -> None:
        for path in self.stack_dir.iterdir():
            path.unlink()

        status, stdout = self._run_doctor()

        self.assertEqual(status, 1, stdout)
        self.assertIn("[FAIL] compose discovery: no compose stacks found", stdout)
        self.assertNotIn("Ignored paths:", stdout)

    def test_doctor_reports_configured_compose_ignore_paths(self) -> None:
        status, stdout = self._run_doctor({"WUD_COMPOSE_IGNORE_PATHS": "app"})

        self.assertEqual(status, 1, stdout)
        self.assertIn("Ignored paths: app", stdout)
        self.assertNotIn("./old", stdout)

    def test_doctor_passes_script_sync_auto_when_env_is_unset(self) -> None:
        env = self._doctor_env()
        env.pop("WUD_SYNC_SCRIPTS")

        stdout = StringIO()
        with redirect_stdout(stdout):
            status = run_doctor_from_namespace(
                self._doctor_args(),
                repo_root=self.root,
                environ=env,
            )

        self.assertEqual(status, 0, stdout.getvalue())
        self.assertIn(
            f"[PASS] WUD script sync: {self.scripts_dir} (auto)",
            stdout.getvalue(),
        )

    def test_doctor_warns_when_script_sync_auto_destination_is_missing(self) -> None:
        self.scripts_dir.rmdir()
        env = self._doctor_env()
        env.pop("WUD_SYNC_SCRIPTS")

        stdout = StringIO()
        with redirect_stdout(stdout):
            status = run_doctor_from_namespace(
                self._doctor_args(),
                repo_root=self.root,
                environ=env,
            )

        self.assertEqual(status, 0, stdout.getvalue())
        self.assertIn("[WARN] WUD script sync: auto-sync inactive", stdout.getvalue())

    def test_doctor_warns_when_legacy_scripts_are_disabled(self) -> None:
        status, stdout = self._run_doctor({"WUDUP_LEGACY_SCRIPTS": "FALSE"})

        self.assertEqual(status, 0, stdout)
        self.assertIn(
            "[WARN] WUD script sync: legacy WUD callbacks are disabled",
            stdout,
        )

    def test_doctor_result_includes_structured_checks(self) -> None:
        for path in self.stack_dir.iterdir():
            path.unlink()

        result = self._run_doctor_result()

        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.failures, 1)
        compose = next(
            check for check in result.checks if check.name == "compose discovery"
        )
        self.assertEqual(compose.status, "FAIL")
        self.assertEqual(compose.code, "compose-discovery")
        self.assertEqual(compose.category, "compose")
        self.assertTrue(compose.suggestions)
        self.assertIn("docker compose", compose.suggestions[0].snippet)

    def test_doctor_fails_when_compose_config_cannot_render(self) -> None:
        status, stdout = self._run_doctor(
            {"FAKE_DOCKER_CONFIG_FAIL": "1"},
        )

        self.assertEqual(status, 1, stdout)
        self.assertIn("[FAIL] compose config", stdout)
        self.assertIn("config failed", stdout)

    def test_doctor_warns_for_helper_only_bind_mount_sources(self) -> None:
        status, stdout = self._run_doctor(
            {"FAKE_DOCKER_BIND_SOURCE": "/host/app/config"},
        )

        self.assertEqual(status, 0, stdout)
        self.assertIn("[WARN] bind mount path safety", stdout)
        self.assertIn("app: /host/app/config", stdout)

    def test_doctor_fails_for_invalid_boolean_environment_values(self) -> None:
        labels = (
            "WUD_SYNC_SCRIPTS",
            "WUDUP_LEGACY_SCRIPTS",
            "WUDUP_USE_SUDO",
            "TRUENAS_STATUS_CHECK",
        )
        for label in labels:
            with self.subTest(label=label):
                status, stdout = self._run_doctor({label: "treu"})

                self.assertEqual(status, 1, stdout)
                self.assertIn(
                    f"[FAIL] configuration: {label} must be one of",
                    stdout,
                )
                self.assertIn("Result: 1 failure(s), 0 warning(s)", stdout)

    def test_doctor_uses_restart_container_for_truenas_inspect(self) -> None:
        status, stdout = self._run_doctor(
            {
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "custom-hostname",
                "WUD_WEB_RESTART_CONTAINER": "wudup-1",
            },
        )

        self.assertEqual(status, 0, stdout)
        self.assertIn("[PASS] TrueNAS helper container inspect", stdout)

    def test_truenas_fails_with_invalid_timeout(self) -> None:
        status, stdout = self._run_doctor(
            {
                "TRUENAS_STATUS_CHECK": "true",
                "TRUENAS_STATUS_TIMEOUT": "not-a-number",
                "HOSTNAME": "wudup-1",
            },
        )

        self.assertEqual(status, 1, stdout)
        self.assertIn("[FAIL] TrueNAS status timeout", stdout)
        self.assertIn("must be an integer number of seconds", stdout)

    def test_truenas_fails_when_no_identity_candidates(self) -> None:
        with mock.patch(
            "wudup.doctor.container_identity_candidates",
            return_value=[],
        ):
            status, stdout = self._run_doctor(
                {"TRUENAS_STATUS_CHECK": "true"},
            )

        self.assertEqual(status, 1, stdout)
        self.assertIn("[FAIL] TrueNAS helper container inspect", stdout)
        self.assertIn("HOSTNAME is not set", stdout)

    def test_truenas_fails_when_all_candidates_fail_inspect(self) -> None:
        options = self._make_doctor_options(truenas_status_check=True)
        fail_result = CommandResult(
            args=("docker", "container", "inspect", "c1"),
            cwd=None,
            returncode=1,
            stderr="no such container",
        )
        runner_mock = mock.Mock()
        runner_mock.capture.return_value = fail_result

        with mock.patch(
            "wudup.doctor.container_identity_candidates",
            return_value=["c1", "c2"],
        ):
            doctor = Doctor(
                options,
                environ={"HOSTNAME": "c1"},
                runner=runner_mock,
            )
            doctor._check_truenas()

        inspect_check = next(
            c for c in doctor.checks if c.name == "TrueNAS helper container inspect"
        )
        self.assertEqual(inspect_check.status, "FAIL")
        self.assertIn("no such container", inspect_check.detail)

    def test_truenas_passes_on_second_candidate_when_first_fails(self) -> None:
        options = self._make_doctor_options(truenas_status_check=True)
        fail_result = CommandResult(
            args=("docker", "container", "inspect", "c1"),
            cwd=None,
            returncode=1,
            stderr="not found",
        )
        ok_result = CommandResult(
            args=("docker", "container", "inspect", "c2"),
            cwd=None,
            returncode=0,
            stdout='[{"Config":{"Image":"wudup:test"}}]',
        )
        runner_mock = mock.Mock()
        runner_mock.capture.side_effect = [fail_result, ok_result]

        with mock.patch(
            "wudup.doctor.container_identity_candidates",
            return_value=["c1", "c2"],
        ):
            doctor = Doctor(
                options,
                environ={"HOSTNAME": "c1"},
                runner=runner_mock,
            )
            doctor._check_truenas()

        inspect_check = next(
            c for c in doctor.checks if c.name == "TrueNAS helper container inspect"
        )
        self.assertEqual(inspect_check.status, "PASS")

    def test_check_updater_fails_when_empty(self) -> None:
        # options_from_namespace treats WUDUP_UPDATER="" as unset and uses the default
        # path, so we create DoctorOptions with updater="" directly to test this path.
        options = self._make_doctor_options(updater="")
        doctor = Doctor(options, environ={})
        doctor._check_updater()

        updater_check = next(c for c in doctor.checks if c.name == "updater executable")
        self.assertEqual(updater_check.status, "FAIL")
        self.assertIn("WUDUP_UPDATER is empty", updater_check.detail)

    def test_check_updater_fails_when_not_executable(self) -> None:
        non_exec = self.root / "non-executable"
        non_exec.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        non_exec.chmod(0o644)

        status, stdout = self._run_doctor({"WUDUP_UPDATER": str(non_exec)})

        self.assertEqual(status, 1, stdout)
        self.assertIn("[FAIL] updater executable", stdout)
        self.assertIn("not executable", stdout)

    def test_check_updater_fails_when_absolute_path_missing(self) -> None:
        status, stdout = self._run_doctor(
            {"WUDUP_UPDATER": str(self.root / "nonexistent-updater")}
        )

        self.assertEqual(status, 1, stdout)
        self.assertIn("[FAIL] updater executable", stdout)
        self.assertIn("does not exist", stdout)

    def test_check_updater_fails_when_not_found_on_path(self) -> None:
        status, stdout = self._run_doctor(
            {"WUDUP_UPDATER": "no-such-updater-on-path"},
        )

        self.assertEqual(status, 1, stdout)
        self.assertIn("[FAIL] updater executable", stdout)
        self.assertIn("not found on PATH", stdout)

    def test_check_updater_passes_for_bare_name_on_path(self) -> None:
        bare_bin = self.fake_bin / "my-updater"
        bare_bin.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        bare_bin.chmod(0o755)

        status, stdout = self._run_doctor({"WUDUP_UPDATER": "my-updater"})

        self.assertEqual(status, 0, stdout)
        self.assertIn("[PASS] updater executable", stdout)

    def test_check_sudo_fails_when_required_but_missing(self) -> None:
        status, stdout = self._run_doctor(
            {
                "WUDUP_USE_SUDO": "true",
                "PATH": str(self.root / "empty-bin"),
            },
        )

        self.assertEqual(status, 1, stdout)
        self.assertIn("[FAIL] sudo: required but not found on PATH", stdout)

    def test_check_sudo_passes_when_disabled(self) -> None:
        status, stdout = self._run_doctor({"WUDUP_USE_SUDO": "false"})

        self.assertEqual(status, 0, stdout)
        self.assertIn("[PASS] sudo: disabled by WUDUP_USE_SUDO=false", stdout)

    def test_check_sudo_reports_configured_falsey_value(self) -> None:
        for value in ("0", "no", "off"):
            with self.subTest(value=value):
                status, stdout = self._run_doctor({"WUDUP_USE_SUDO": value})

                self.assertEqual(status, 0, stdout)
                self.assertIn(f"[PASS] sudo: disabled by WUDUP_USE_SUDO={value}", stdout)

    def test_check_sudo_passes_when_legacy_env_disabled(self) -> None:
        env = self._doctor_env({"WUD_UPDATER_USE_SUDO": "false"})
        env.pop("WUDUP_USE_SUDO")
        stdout = StringIO()

        with redirect_stdout(stdout):
            status = run_doctor_from_namespace(
                self._doctor_args(),
                repo_root=self.root,
                environ=env,
            )

        output = stdout.getvalue()
        self.assertEqual(status, 0, output)
        self.assertIn("[PASS] sudo: disabled by WUD_UPDATER_USE_SUDO=false", output)

    def test_check_sudo_requires_sudo_when_legacy_env_enabled(self) -> None:
        env = self._doctor_env(
            {
                "PATH": str(self.root / "empty-bin"),
                "WUD_UPDATER_USE_SUDO": "true",
            }
        )
        env.pop("WUDUP_USE_SUDO")
        stdout = StringIO()

        with redirect_stdout(stdout):
            status = run_doctor_from_namespace(
                self._doctor_args(),
                repo_root=self.root,
                environ=env,
            )

        output = stdout.getvalue()
        self.assertEqual(status, 1, output)
        self.assertIn("[FAIL] sudo: required but not found on PATH", output)
        self.assertNotIn("[PASS] sudo: disabled by default", output)

    def test_check_sudo_passes_when_unset(self) -> None:
        env = self._doctor_env()
        env.pop("WUDUP_USE_SUDO")
        stdout = StringIO()

        with redirect_stdout(stdout):
            status = run_doctor_from_namespace(
                self._doctor_args(),
                repo_root=self.root,
                environ=env,
            )

        output = stdout.getvalue()
        self.assertEqual(status, 0, output)
        self.assertIn("[PASS] sudo: disabled by default", output)

    def test_readiness_result_passes_with_accessible_docker_and_wud_file(self) -> None:
        # Use a tcp DOCKER_HOST so no Unix socket check is needed.
        options = self._make_doctor_options(docker_host="tcp://docker:2375")
        env = self._doctor_env()
        ok_result = CommandResult(
            args=("docker", "version"),
            cwd=None,
            returncode=0,
            stdout="Docker Engine 28.0.0",
        )
        runner_mock = mock.Mock()
        runner_mock.capture.return_value = ok_result

        doctor = Doctor(options, environ=env, runner=runner_mock)
        result = doctor.run_readiness_result()

        self.assertEqual(result.failures, 0)
        self.assertTrue(result.ok)

    def test_readiness_result_fails_when_docker_unavailable(self) -> None:
        options = self._make_doctor_options(docker_host="tcp://docker:2375")
        env = self._doctor_env()
        fail_result = CommandResult(
            args=("docker", "version"),
            cwd=None,
            returncode=1,
            stderr="connection refused",
        )
        runner_mock = mock.Mock()
        runner_mock.capture.return_value = fail_result

        doctor = Doctor(options, environ=env, runner=runner_mock)
        result = doctor.run_readiness_result()

        self.assertFalse(result.ok)
        self.assertGreater(result.failures, 0)

    def test_permission_probe_names_are_safe_for_concurrent_doctor_runs(self) -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            issues = list(executor.map(lambda _: _write_probe(self.log_dir), range(64)))

        self.assertEqual([issue for issue in issues if issue], [])

    def _run_doctor(
        self,
        env_overrides: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        env = self._doctor_env(env_overrides)

        stdout = StringIO()
        args = self._doctor_args()
        with redirect_stdout(stdout):
            status = run_doctor_from_namespace(
                args,
                repo_root=self.root,
                environ=env,
            )
        return status, stdout.getvalue()

    def _run_doctor_result(
        self,
        env_overrides: dict[str, str] | None = None,
    ):
        return doctor_result_from_namespace(
            self._doctor_args(),
            repo_root=self.root,
            environ=self._doctor_env(env_overrides),
        )

    def _doctor_env(
        self,
        env_overrides: dict[str, str] | None = None,
    ) -> dict[str, str]:
        env = {
            "PATH": f"{self.fake_bin}:{os.environ.get('PATH', '')}",
            "DOCKER_HOST": "tcp://docker:2375",
            "DOCKER_BASE": str(self.docker_base),
            "WUD_OUT_FILE": str(self.out_dir / "images.todo"),
            "WUD_LOG_DIR": str(self.log_dir),
            "WUD_SCRIPTS_DIR": str(self.scripts_dir),
            "WUD_APP_DIR": str(self.app_dir),
            "WUD_SYNC_SCRIPTS": "true",
            "WUDUP_UPDATER": str(self.updater),
            "WUDUP_CONFIG": str(self.root / "missing-env"),
            "WUDUP_USE_SUDO": "false",
            "TRUENAS_STATUS_CHECK": "false",
        }
        if env_overrides is not None:
            env.update(env_overrides)
        return env

    def _doctor_args(self) -> argparse.Namespace:
        return argparse.Namespace(
            base=None,
            file=None,
            log_dir=None,
            scripts_dir=None,
            no_color=True,
        )

    def _make_doctor_options(self, **overrides: object) -> DoctorOptions:
        defaults: dict[str, object] = {
            "docker_base": self.docker_base,
            "wud_file": self.out_dir / "images.todo",
            "log_dir": self.log_dir,
            "scripts_dir": self.scripts_dir,
            "packaged_scripts_dir": self.packaged_scripts,
            "app_dir": self.app_dir,
            "updater": str(self.updater),
            "truenas_status_timeout": DEFAULT_TRUENAS_STATUS_TIMEOUT,
        }
        defaults.update(overrides)
        return DoctorOptions(**defaults)  # type: ignore[arg-type]

    def _write_docker(self) -> None:
        docker = self.fake_bin / "docker"
        docker.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  --version)
    printf 'Docker version 28.0.0\\n'
    exit 0
    ;;
  version)
    printf 'Server: Docker Engine 28.0.0\\n'
    exit 0
    ;;
  info)
    printf 'Docker Root Dir: /var/lib/docker\\n'
    exit 0
    ;;
  ps)
    printf 'CONTAINER ID   IMAGE\\n'
    exit 0
    ;;
  container)
    if [[ "${2:-}" == "inspect" ]]; then
      printf '[{"Config":{"Image":"wudup:test"}}]\\n'
      exit 0
    fi
    ;;
  compose)
    if [[ "${2:-}" == "version" ]]; then
      printf 'Docker Compose version v2.30.0\\n'
      exit 0
    fi
    if [[ "${FAKE_DOCKER_CONFIG_FAIL:-}" == "1" ]]; then
      printf 'config failed\\n' >&2
      exit 22
    fi
    for arg in "$@"; do
      if [[ "$arg" == "json" ]]; then
        if [[ -n "${FAKE_DOCKER_BIND_SOURCE:-}" ]]; then
          printf '{"services":{"app":{"image":"repo/app:latest","volumes":[{"type":"bind","source":"%s","target":"/config"}]}}}\\n' "$FAKE_DOCKER_BIND_SOURCE"
        else
          printf '{"services":{"app":{"image":"repo/app:latest"}}}\\n'
        fi
        exit 0
      fi
    done
    printf 'name: app\\n'
    exit 0
    ;;
esac
printf 'unexpected docker args: %s\\n' "$*" >&2
exit 2
""",
            encoding="utf-8",
        )
        docker.chmod(0o755)

    def _write_packaged_scripts(self) -> None:
        for name in REQUIRED_WUD_SCRIPTS:
            path = self.packaged_scripts / name
            path.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)

    def _write_compose(self) -> None:
        (self.stack_dir / "compose.yml").write_text(
            "services:\n  app:\n    image: repo/app:latest\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import argparse
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from wud_updater.doctor import run_doctor_from_namespace


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

    def test_doctor_fails_when_no_compose_stacks_are_found(self) -> None:
        for path in self.stack_dir.iterdir():
            path.unlink()

        status, stdout = self._run_doctor()

        self.assertEqual(status, 1, stdout)
        self.assertIn("[FAIL] compose discovery: no compose stacks found", stdout)

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
            "WUD_UPDATER_USE_SUDO",
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

    def _run_doctor(
        self,
        env_overrides: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        env = {
            "PATH": f"{self.fake_bin}:{os.environ.get('PATH', '')}",
            "DOCKER_HOST": "tcp://docker:2375",
            "DOCKER_BASE": str(self.docker_base),
            "WUD_OUT_FILE": str(self.out_dir / "images.todo"),
            "WUD_LOG_DIR": str(self.log_dir),
            "WUD_SCRIPTS_DIR": str(self.scripts_dir),
            "WUD_APP_DIR": str(self.app_dir),
            "WUD_SYNC_SCRIPTS": "true",
            "WUD_UPDATER": str(self.updater),
            "WUD_UPDATER_CONFIG": str(self.root / "missing-env"),
            "WUD_UPDATER_USE_SUDO": "false",
            "TRUENAS_STATUS_CHECK": "false",
        }
        if env_overrides is not None:
            env.update(env_overrides)

        stdout = StringIO()
        args = argparse.Namespace(
            base=None,
            file=None,
            log_dir=None,
            scripts_dir=None,
            no_color=True,
        )
        with redirect_stdout(stdout):
            status = run_doctor_from_namespace(
                args,
                repo_root=self.root,
                environ=env,
            )
        return status, stdout.getvalue()

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
        for name in (
            "on-update.sh",
            "append-updates.sh",
            "release-notes-to-discord.sh",
            "github-release-embed.sh",
            "tag-manager.sh",
        ):
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

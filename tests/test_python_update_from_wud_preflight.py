from __future__ import annotations

import re
import sqlite3
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from wud_updater.command import CommandRunner
from wud_updater.compose import (
    ComposeBindMount,
)
from wud_updater.updater import (
    UpdateFromWudRunner,
)
from wud_updater.updater_models import (
    UpdaterOptions,
)


from tests.update_from_wud_helpers import (
    UpdateFromWudRunnerTestCase,
)

class UpdateFromWudPreflightTests(UpdateFromWudRunnerTestCase):
    def test_malformed_audit_db_fails_before_mutation(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA user_version = 99")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn("Could not initialize audit database:", result.stderr)
        self.assertIn("Unsupported database schema version: 99", result.stderr)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "repo/app:latest\n")
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
    def test_container_bridge_bind_mount_preflight_fails_before_mutation(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            no_color=True,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch.object(
                runner.compose,
                "try_service_bind_mounts",
                return_value=(ComposeBindMount("app", "/host/docker/app/config", "/config"),),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 1, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "repo/app:latest\n")
        self.assertIn("helper-only prefix /host", stderr.getvalue())
        self.assertIn("HOST_DOCKER_BASE=/srv/docker", stderr.getvalue())
        self.assertIn("error report:", stderr.getvalue())
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=preflight", report)
        self.assertIn("reason=bind-mount-path-invalid", report)
        self.assertIn("/host/docker/app/config", report)
        self.assertIn("helper-only prefix /host", report)
        runs = self.db_rows("SELECT * FROM update_runs")
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failure")
        self.assertTrue(runs[0]["finished_at"].endswith("+00:00"))
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(pending[0]["status_reason"], "bind-mount-path-invalid")
        self.assertEqual(pending[0]["stack_name"], "app")
        self.assertEqual(pending[0]["service_name"], "app")
    def test_container_bridge_bind_mount_preflight_marks_unaffected_matches_pending(self) -> None:
        self.wud_file.write_text("repo/bad:latest\nrepo/ok:latest\n", encoding="utf-8")
        self.make_stack("bad", [("app", "repo/bad:latest", "cid-bad")])
        self.make_stack("ok", [("app", "repo/ok:latest", "cid-ok")])
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            no_color=True,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        stdout = StringIO()
        stderr = StringIO()

        def bind_mounts(directory: Path, file: str, **_: object) -> tuple[ComposeBindMount, ...]:
            if Path(directory).name == "bad":
                return (ComposeBindMount("app", "/host/docker/bad/config", "/config"),)
            return ()

        with (
            mock.patch.object(
                runner.compose,
                "try_service_bind_mounts",
                side_effect=bind_mounts,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 1, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/bad:latest\nrepo/ok:latest\n",
        )
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
        runs = self.db_rows("SELECT * FROM update_runs")
        pending = self.db_rows("SELECT * FROM pending_updates ORDER BY line_no")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failure")
        self.assertEqual(
            [
                (
                    row["line_no"],
                    row["status"],
                    row["status_reason"],
                    row["stack_name"],
                    row["service_name"],
                )
                for row in pending
            ],
            [
                (1, "failed", "bind-mount-path-invalid", "bad", "app"),
                (2, "pending", "preflight-skipped", "ok", "app"),
            ],
        )
    def test_container_bridge_bind_mount_preflight_warns_on_dry_run(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            dry_run=True,
            no_color=True,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch.object(
                runner.compose,
                "try_service_bind_mounts",
                return_value=(ComposeBindMount("app", "/host/docker/app/config", "/config"),),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 0, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "repo/app:latest\n")
        self.assertIn("helper-only prefix /host", stdout.getvalue())
        self.assertIn("reported container bind-mount path issue", stdout.getvalue())
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
        self.assertFalse(self.db_path.exists())
        self.assertFalse(list(self.log_dir.glob("update-from-wud-v2-*.errors.log")))
    def test_container_bridge_bind_mount_preflight_allows_host_paths(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            no_color=True,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch.object(
                runner.compose,
                "try_service_bind_mounts",
                return_value=(
                    ComposeBindMount("app", "/mnt/nvme-pool/docker/app/config", "/config"),
                ),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 0, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertRegex(self.calls(), r"compose -f docker-compose.yml pull app")
        self.assertRegex(self.calls(), r"compose -f docker-compose.yml up -d .* app")
    def test_host_docker_base_maps_project_directory_and_allows_binds(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        host_base = self.root / "host-docker"
        expected_project_directory = host_base / "app"
        expected_project_directory.mkdir(parents=True)
        (expected_project_directory / "docker-compose.yml").write_text(
            (self.base / "app" / "docker-compose.yml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            no_color=True,
            host_docker_base=host_base,
            host_docker_base_label=str(host_base),
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        stdout = StringIO()
        stderr = StringIO()
        project_directories: list[Path | None] = []

        def bind_mounts(
            directory: Path,
            file: str,
            *,
            project_directory: Path | None = None,
        ) -> tuple[ComposeBindMount, ...]:
            self.assertEqual(directory, self.base / "app")
            self.assertEqual(file, "docker-compose.yml")
            project_directories.append(project_directory)
            source = str((project_directory or directory) / "config")
            return (ComposeBindMount("app", source, "/config"),)

        with (
            mock.patch.object(
                runner.compose,
                "try_service_bind_mounts",
                side_effect=bind_mounts,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 0, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(project_directories, [expected_project_directory])
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn(f"HostBase: {host_base}", stdout.getvalue())
        self.assertRegex(
            self.calls(),
            rf"compose --project-directory {re.escape(str(expected_project_directory))} "
            r"-f docker-compose.yml pull app",
        )
        self.assertRegex(
            self.calls(),
            rf"compose --project-directory {re.escape(str(expected_project_directory))} "
            r"-f docker-compose.yml up -d .* app",
        )
    def test_invalid_runtime_port_fails_preflight_before_pull(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        (stack_dir / "docker-compose.yml").write_text(
            "\n".join(
                [
                    "services:",
                    "  app:",
                    "    image: repo/app:latest",
                    "    expose:",
                    "      - \u201c8083\u201d",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "repo/app:latest\n")
        calls = self.calls()
        self.assertNotRegex(calls, r"compose -f docker-compose.yml pull")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml stop")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml up")
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=preflight", report)
        self.assertIn("reason=compose-port-invalid", report)
        self.assertIn("Compose service app has invalid expose value", report)
        self.assertIn("\u201c8083\u201d", report)

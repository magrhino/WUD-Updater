from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from wud_updater.command import CommandRunner
from wud_updater.compose import (
    ComposeBindMount,
    ComposeStack,
    ServiceImage,
)
from wud_updater.file_ops import OwnerConfig
from wud_updater.updater import (
    ComposeTagRewriteError,
    TagExclusionUpdate,
    TagUpdate,
    UpdaterError,
    UpdaterOptions,
    UpdateFromWudRunner,
    _apply_sqlite_owner,
    apply_compose_tag_updates,
    apply_compose_tag_exclusions,
    exact_tags_regex,
    merge_wud_exclude_regex,
    prepare_log_file,
)


class PythonUpdateFromWudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="wud-python-update.")
        self.root = Path(self.tmp.name)
        self.repo_root = Path(__file__).resolve().parents[1]
        self.base = self.root / "base"
        self.wud_file = self.root / "images.todo"
        self.log_dir = self.root / "logs"
        self.db_path = self.root / "state" / "wud-updater.sqlite"
        self.fake_root = self.root / "fake"
        for path in (
            self.base,
            self.log_dir,
            self.fake_root / "images",
            self.fake_root / "manifests",
            self.fake_root / "stacks",
            self.fake_root / "containers",
        ):
            path.mkdir(parents=True, exist_ok=True)
        (self.fake_root / "containers.tsv").write_text("", encoding="utf-8")
        (self.fake_root / "calls.log").write_text("", encoding="utf-8")

        self.env = os.environ.copy()
        self.env["FAKE_DOCKER_ROOT"] = str(self.fake_root)
        self.env["PATH"] = f"{self.repo_root / 'tests' / 'fakes'}:{self.env['PATH']}"
        self.env["PYTHONPATH"] = str(self.repo_root / "src")
        self.env["WUD_UPDATER_BANNER"] = "false"
        self.env["WUD_DB_PATH"] = str(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_python(self, *args: str, wrapper: bool = False) -> subprocess.CompletedProcess[str]:
        common = [
            "--base",
            str(self.base),
            "--file",
            str(self.wud_file),
            "--log-dir",
            str(self.log_dir),
            "--max-wait",
            "0",
            "--no-color",
            *args,
        ]
        env = dict(self.env)
        if wrapper:
            env["PYTHON_BIN"] = sys.executable
            command = [str(self.repo_root / "bin" / "docker-update-from-wud"), *common]
        else:
            command = [
                sys.executable,
                "-m",
                "wud_updater.cli",
                "update-from-wud",
                *common,
            ]
        return subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    def make_stack(
        self,
        stack_id: str,
        services: list[tuple[str, str, str | None]],
        *,
        parent: Path | None = None,
    ) -> Path:
        directory = (parent or self.base) / stack_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".fake-docker-id").write_text(f"{stack_id}\n", encoding="utf-8")
        stack_state = self.fake_root / "stacks" / stack_id
        stack_state.mkdir(parents=True, exist_ok=True)
        cids: list[str] = []

        compose_lines = ["services:\n"]
        service_rows: list[str] = []
        image_rows: list[str] = []
        for service, image, cid in services:
            compose_lines.extend([f"  {service}:\n", f"    image: {image}\n"])
            service_rows.append(f"{service}\n")
            image_rows.append(f"{image}\n")
            with (stack_state / "service-images.tsv").open("a", encoding="utf-8") as file:
                file.write(f"{service}\t{image}\n")
            if cid is not None:
                cids.append(cid)
                (stack_state / f"cids-{service}.txt").write_text(
                    f"{cid}\n",
                    encoding="utf-8",
                )
                (self.fake_root / "containers" / f"{cid}.summary").write_text(
                    f"/{cid}|running|healthy|0|0\n",
                    encoding="utf-8",
                )

        (directory / "docker-compose.yml").write_text("".join(compose_lines), encoding="utf-8")
        (stack_state / "services.txt").write_text("".join(service_rows), encoding="utf-8")
        (stack_state / "images.txt").write_text("".join(image_rows), encoding="utf-8")
        (stack_state / "cids.txt").write_text(
            "".join(f"{cid}\n" for cid in cids),
            encoding="utf-8",
        )
        return directory

    def set_image_state(self, image: str, image_id: str, digest: str = "") -> None:
        safe = safe_name(image)
        (self.fake_root / "images" / f"{safe}.id").write_text(
            f"{image_id}\n",
            encoding="utf-8",
        )
        (self.fake_root / "images" / f"{safe}.digests").write_text(
            f"{image}@{digest}\n" if digest else "",
            encoding="utf-8",
        )

    def set_image_after_pull(self, image: str, image_id: str, digest: str = "") -> None:
        safe = safe_name(image)
        (self.fake_root / "images" / f"{safe}.after_id").write_text(
            f"{image_id}\n",
            encoding="utf-8",
        )
        (self.fake_root / "images" / f"{safe}.after_digests").write_text(
            f"{image}@{digest}\n" if digest else "",
            encoding="utf-8",
        )

    def set_manifest_failure(self, image: str, stderr: str) -> None:
        safe = safe_name(image)
        (self.fake_root / "manifests" / f"{safe}.fail").write_text(
            "",
            encoding="utf-8",
        )
        (self.fake_root / "manifests" / f"{safe}.stderr").write_text(
            stderr,
            encoding="utf-8",
        )

    def calls(self) -> str:
        return (self.fake_root / "calls.log").read_text(encoding="utf-8")

    def latest_error_report(self) -> Path:
        reports = sorted(self.log_dir.glob("update-from-wud-v2-*.errors.log"))
        self.assertTrue(reports, "expected updater error report")
        return reports[-1]

    def db_rows(self, query: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            return list(conn.execute(query, params))

    def test_wrapper_default_dry_run_plans_without_mutation(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")

        result = self.run_python("--dry-run", wrapper=True)

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "repo/app:latest\n")
        self.assertIn("line 1: repo/app:latest", result.stdout)
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
        self.assertFalse(self.db_path.exists())

    def test_python_updates_matched_service_and_cleans_wud_line(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack(
            "stack",
            [
                ("app", "repo/app:latest", "cid-app"),
                ("db", "repo/db:latest", "cid-db"),
            ],
        )
        self.set_image_state("repo/app:latest", "old-app", "sha256:old-app")
        self.set_image_after_pull("repo/app:latest", "new-app", "sha256:new-app")
        self.set_image_state("repo/db:latest", "old-db", "sha256:old-db")
        self.set_image_after_pull("repo/db:latest", "new-db", "sha256:new-db")

        result = self.run_python("--yes", "--mode", "stop")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        calls = self.calls()
        self.assertRegex(calls, r"compose -f docker-compose.yml pull app")
        self.assertRegex(calls, r"compose -f docker-compose.yml stop app")
        self.assertRegex(calls, r"compose -f docker-compose.yml up -d .* app")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml pull db")
        runs = self.db_rows("SELECT * FROM update_runs")
        pending = self.db_rows("SELECT * FROM pending_updates")
        events = self.db_rows("SELECT * FROM update_events")
        known = self.db_rows("SELECT * FROM known_images")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "success")
        self.assertTrue(runs[0]["finished_at"].endswith("+00:00"))
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "resolved")
        self.assertEqual(pending[0]["status_reason"], "updated")
        self.assertEqual(pending[0]["service_key"], "stack/app")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "success")
        self.assertEqual(events[0]["service_name"], "app")
        self.assertEqual(len(known), 1)
        self.assertEqual(known[0]["service_key"], "stack/app")
        self.assertEqual(known[0]["image"], "repo/app:latest")
        self.assertEqual(known[0]["image_id"], "new-app")
        self.assertTrue(known[0]["digest"].endswith("@sha256:new-app"))

    def test_python_updates_honors_configured_compose_ignore_paths(self) -> None:
        self.wud_file.write_text("repo/ignored:latest\n", encoding="utf-8")
        self.make_stack("active", [("app", "repo/app:latest", "cid-app")])
        self.make_stack(
            "ignored",
            [("app", "repo/ignored:latest", "cid-ignored")],
            parent=self.base / "old",
        )
        self.set_image_state("repo/ignored:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/ignored:latest", "new", "sha256:new")
        self.env["WUD_COMPOSE_IGNORE_PATHS"] = "old"

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/ignored:latest\n",
        )
        self.assertNotRegex(self.calls(), r"repo/ignored")
        self.assertNotRegex(self.calls(), r"compose -f .* pull")

    def test_remove_lines_before_run_records_discarded_audit_entries(self) -> None:
        self.wud_file.write_text(
            "repo/app:one\nrepo/app:two\nrepo/app:three\n",
            encoding="utf-8",
        )
        self.make_stack("stack", [("app", "repo/app:two", "cid-app")])
        self.set_image_state("repo/app:two", "old", "sha256:old")
        self.set_image_after_pull("repo/app:two", "new", "sha256:new")

        result = self.run_python(
            "--yes",
            "--only-lines",
            "2",
            "--remove-lines-before-run",
            "1,3",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        pending = self.db_rows(
            "SELECT * FROM pending_updates ORDER BY line_no"
        )
        self.assertEqual(len(pending), 3)
        self.assertEqual(
            [(row["line_no"], row["status"], row["status_reason"]) for row in pending],
            [
                (1, "resolved", "removed-before-run"),
                (2, "resolved", "updated"),
                (3, "resolved", "removed-before-run"),
            ],
        )

    def test_digest_mismatch_restores_line_and_skips_recreate(self) -> None:
        self.wud_file.write_text("repo/app@sha256:good\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:bad")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app@sha256:good\n",
        )
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
        pending = self.db_rows("SELECT * FROM pending_updates")
        runs = self.db_rows("SELECT * FROM update_runs")
        self.assertEqual(runs[0]["status"], "failure")
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(pending[0]["status_reason"], "expected-digest-not-reached")

    def test_multi_stack_failure_keeps_failure_reason_in_pending_audit(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("ok", [("app", "repo/app:latest", "cid-ok")])
        self.make_stack("zbad", [("app", "repo/app:latest", "cid-bad")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        stack_state = self.fake_root / "stacks" / "zbad"
        (stack_state / "pull_fail").write_text("", encoding="utf-8")
        (stack_state / "pull_stderr").write_text("manifest fetch failed\n", encoding="utf-8")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(pending[0]["status_reason"], "pull-failed")
        self.assertEqual(pending[0]["service_key"], "zbad/app")
        self.assertEqual(pending[0]["stack_name"], "zbad")
        self.assertEqual(pending[0]["service_name"], "app")

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

    def test_audit_owner_failure_marks_started_run_failed(self) -> None:
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
            db_path=self.db_path,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch(
                "wud_updater.updater._apply_sqlite_owner",
                side_effect=OSError("chown failed"),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            with self.assertRaisesRegex(
                UpdaterError,
                "Could not initialize audit database: chown failed",
            ):
                runner.run()

        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "repo/app:latest\n")
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
        runs = self.db_rows("SELECT * FROM update_runs")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failure")
        self.assertIsNotNone(runs[0]["finished_at"])

    def test_late_audit_write_failure_marks_run_failed(self) -> None:
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
            db_path=self.db_path,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch(
                "wud_updater.updater.insert_update_event",
                side_effect=sqlite3.OperationalError("database is locked"),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            with self.assertRaisesRegex(
                UpdaterError,
                "Could not update audit database: database is locked",
            ):
                runner.run()

        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        runs = self.db_rows("SELECT * FROM update_runs")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failure")
        self.assertIsNotNone(runs[0]["finished_at"])

    def test_wud_file_rewrite_failure_is_user_facing(self) -> None:
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
            db_path=self.db_path,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch(
                "wud_updater.updater.remove_lines_before_run",
                side_effect=OSError("metadata verification failed"),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            with self.assertRaisesRegex(
                UpdaterError,
                "Filesystem operation failed: metadata verification failed",
            ):
                runner.run()

        runs = self.db_rows("SELECT * FROM update_runs")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failure")
        self.assertIsNotNone(runs[0]["finished_at"])

    def test_audit_start_applies_configured_owner_to_db_path(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        self.env["OUT_UID"] = str(os.getuid())
        self.env["OUT_GID"] = str(os.getgid())
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            no_color=True,
            db_path=self.db_path,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch("wud_updater.updater._apply_sqlite_owner") as apply_owner,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 0, stderr.getvalue() + stdout.getvalue())
        apply_owner.assert_any_call(self.db_path, runner.owner, chown_parent=True)

    def test_apply_sqlite_owner_leaves_existing_db_directory_alone(self) -> None:
        db_path = self.root / "state" / "wud-updater.sqlite"
        sidecars = [
            db_path,
            Path(f"{db_path}-wal"),
            Path(f"{db_path}-shm"),
            Path(f"{db_path}-journal"),
        ]
        db_path.parent.mkdir(parents=True, exist_ok=True)
        for path in sidecars:
            path.write_text("", encoding="utf-8")
        owner = OwnerConfig.from_values(str(os.getuid()), str(os.getgid()))

        with mock.patch("wud_updater.updater.apply_configured_owner") as apply_owner:
            _apply_sqlite_owner(db_path, owner)

        called_paths = [Path(call.args[0]) for call in apply_owner.call_args_list]
        self.assertEqual(called_paths, sidecars)

    def test_apply_sqlite_owner_updates_created_db_directory_and_sidecars(self) -> None:
        db_path = self.root / "created-state" / "wud-updater.sqlite"
        sidecars = [
            db_path,
            Path(f"{db_path}-wal"),
            Path(f"{db_path}-shm"),
            Path(f"{db_path}-journal"),
        ]
        db_path.parent.mkdir(parents=True, exist_ok=True)
        for path in sidecars:
            path.write_text("", encoding="utf-8")
        owner = OwnerConfig.from_values(str(os.getuid()), str(os.getgid()))

        with mock.patch("wud_updater.updater.apply_configured_owner") as apply_owner:
            _apply_sqlite_owner(db_path, owner, chown_parent=True)

        called_paths = [Path(call.args[0]) for call in apply_owner.call_args_list]
        self.assertEqual(called_paths, [db_path.parent, *sidecars])

    def test_up_wait_failure_writes_error_report_with_command_output(self) -> None:
        self.env["FAKE_COMPOSE_UP_WAIT"] = "1"
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", None)])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        stack_state = self.fake_root / "stacks" / "app"
        (stack_state / "up_fail").write_text("", encoding="utf-8")
        (stack_state / "up_stdout").write_text("compose stdout before failure\n", encoding="utf-8")
        (stack_state / "up_stderr").write_text("network create failed\n", encoding="utf-8")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn("error report:", result.stderr)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "repo/app:latest\n")
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=up", report)
        self.assertIn("reason=up-or-health-failed", report)
        self.assertIn("wud_entries_restored=yes", report)
        self.assertIn("exit_code=19", report)
        self.assertIn("--wait --wait-timeout 0 app", report)
        self.assertIn("compose stdout before failure", report)
        self.assertIn("network create failed", report)
        self.assertIn("health: docker compose ps -q returned no containers", report)

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

    def test_pull_failure_writes_error_report(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        stack_state = self.fake_root / "stacks" / "app"
        (stack_state / "pull_fail").write_text("", encoding="utf-8")
        (stack_state / "pull_stderr").write_text("manifest fetch failed\n", encoding="utf-8")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=pull", report)
        self.assertIn("reason=pull-failed", report)
        self.assertIn("exit_code=17", report)
        self.assertIn("manifest fetch failed", report)
        self.assertIn("health: container=cid-app status=running health=healthy", report)

    def test_stop_failure_reports_failed_phase_after_recovery(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        stack_state = self.fake_root / "stacks" / "app"
        (stack_state / "stop_fail").write_text("", encoding="utf-8")
        (stack_state / "stop_stderr").write_text("container stop failed\n", encoding="utf-8")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=stop", report)
        self.assertIn("reason=down-failed", report)
        self.assertIn("exit_code=18", report)
        self.assertIn("container stop failed", report)
        self.assertIn("Compose up recovery succeeded", report)

    def test_tag_update_stack_recreate_reports_recovery_up_failure(self) -> None:
        self.env["FAKE_COMPOSE_UP_WAIT"] = "1"
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")
        stack_state = self.fake_root / "stacks" / "app"
        (self.fake_root / "containers" / "cid-app.labels").write_text(
            "WUD-UPDATER-RECREATE-STACK=true\n",
            encoding="utf-8",
        )
        (stack_state / "stop_fail").write_text("", encoding="utf-8")
        (stack_state / "stop_stderr").write_text(
            "container stop failed\n",
            encoding="utf-8",
        )
        (stack_state / "up_fail").write_text("", encoding="utf-8")
        (stack_state / "up_stderr").write_text(
            "recovery up failed\n",
            encoding="utf-8",
        )

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=stop", report)
        self.assertIn("reason=down-failed", report)
        self.assertIn("argv=docker compose -f docker-compose.yml up", report)
        self.assertNotIn("--force-recreate", report)
        self.assertIn("recovery up failed", report)
        self.assertNotIn("argv=docker compose -f docker-compose.yml down", report)

    def test_tag_update_requires_explicit_flag(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn("require --allow-tag-updates", result.stdout)
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "pending")
        self.assertEqual(pending[0]["status_reason"], "tag-update-disabled")

    def test_exclude_tag_line_writes_wud_label_and_cleans_line(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])

        result = self.run_python("--yes", "--exclude-tag-lines", "1")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        content = (stack_dir / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("wud.tag.exclude=^2\\.0$$", content)
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
        pending = self.db_rows("SELECT * FROM pending_updates")
        rules = self.db_rows("SELECT * FROM tag_exclusion_rules")
        self.assertEqual(pending[0]["status"], "resolved")
        self.assertEqual(pending[0]["status_reason"], "tag-excluded")
        self.assertEqual(rules[0]["scope"], "image_repo")
        self.assertEqual(rules[0]["image_repo"], "repo/app")
        self.assertEqual(rules[0]["tag"], "2.0")

    def test_exclude_tag_line_updates_all_services_for_image_repo(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        app_stack = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        worker_stack = self.make_stack(
            "worker",
            [("worker", "registry.example.com/repo/app:1.1", "cid-worker")],
        )

        result = self.run_python("--yes", "--exclude-tag-lines", "1")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "wud.tag.exclude=^2\\.0$$",
            (app_stack / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "wud.tag.exclude=^2\\.0$$",
            (worker_stack / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        rules = self.db_rows("SELECT * FROM tag_exclusion_rules")
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["scope"], "image_repo")

    def test_exclude_tag_line_can_recreate_affected_services(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])

        result = self.run_python(
            "--yes",
            "--exclude-tag-lines",
            "1",
            "--recreate-excluded-services",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertRegex(
            self.calls(),
            r"compose -f docker-compose.yml up -d --remove-orphans --no-deps app",
        )

    def test_exclude_tag_line_recreate_includes_missing_network_provider(self) -> None:
        self.wud_file.write_text(
            "ghcr.io/linuxserver/qbittorrent:5.1.4 tag=5.2.0\n",
            encoding="utf-8",
        )
        stack_dir = self.base / "media"
        stack_dir.mkdir()
        (stack_dir / ".fake-docker-id").write_text("media\n", encoding="utf-8")
        compose_file = stack_dir / "docker-compose.yml"
        compose_file.write_text(
            "\n".join(
                [
                    "services:",
                    "  gluetun:",
                    "    image: qmcgaw/gluetun:latest",
                    "  qbittorrent:",
                    "    image: ghcr.io/linuxserver/qbittorrent:5.1.4",
                    "    network_mode: service:gluetun",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stack_state = self.fake_root / "stacks" / "media"
        stack_state.mkdir()
        (stack_state / "cids.txt").write_text(
            "cid-qbittorrent\n",
            encoding="utf-8",
        )
        (stack_state / "cids-qbittorrent.txt").write_text(
            "cid-qbittorrent\n",
            encoding="utf-8",
        )
        for cid in ("cid-gluetun", "cid-qbittorrent"):
            (self.fake_root / "containers" / f"{cid}.summary").write_text(
                f"/{cid}|running|healthy|0|0\n",
                encoding="utf-8",
            )
        hook = self.fake_root / "post-up-hook"
        hook.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "set -euo pipefail",
                    'printf "cid-gluetun\\n" > "$FAKE_DOCKER_ROOT/stacks/media/cids-gluetun.txt"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        hook.chmod(0o755)

        result = self.run_python(
            "--yes",
            "--exclude-tag-lines",
            "1",
            "--recreate-excluded-services",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn(
            "wud.tag.exclude=^5\\.2\\.0$$",
            compose_file.read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertRegex(
            calls,
            r"compose -f docker-compose.yml up -d --remove-orphans gluetun qbittorrent",
        )
        self.assertNotRegex(calls, r"compose -f docker-compose.yml up -d .*--no-deps")

    def test_exclude_tag_line_recreates_only_successful_label_writes(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        app_stack = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        worker_stack = self.make_stack(
            "worker",
            [("worker", "registry.example.com/repo/app:1.1", "cid-worker")],
        )
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            no_color=True,
            exclude_tag_lines="1",
            recreate_excluded_services=True,
            db_path=self.db_path,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )

        def flaky_apply_compose_tag_exclusions(
            compose_path: Path,
            updates: tuple[TagExclusionUpdate, ...],
            *,
            existing_exact_tags: dict[str, set[str]],
        ) -> object:
            if compose_path.parent.name == "worker":
                raise ComposeTagRewriteError("synthetic label write failure")
            return apply_compose_tag_exclusions(
                compose_path,
                updates,
                existing_exact_tags=existing_exact_tags,
            )

        with mock.patch(
            "wud_updater.updater.apply_compose_tag_exclusions",
            side_effect=flaky_apply_compose_tag_exclusions,
        ):
            result = runner.run()

        self.assertEqual(result, 1)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        calls = self.calls()
        self.assertIn(
            f"{app_stack}\tcompose -f docker-compose.yml up -d "
            "--remove-orphans --no-deps app",
            calls,
        )
        self.assertNotIn(
            f"{worker_stack}\tcompose -f docker-compose.yml up -d "
            "--remove-orphans --no-deps worker",
            calls,
        )
        self.assertIn(
            "wud.tag.exclude=^2\\.0$$",
            (app_stack / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertNotIn(
            "wud.tag.exclude",
            (worker_stack / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(pending[0]["status_reason"], "tag-exclusion-label-failed")

    def test_exclude_tag_line_failure_leaves_line_pending(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        compose_file = stack_dir / "docker-compose.yml"
        compose_file.write_text(
            "services:\n  app:\n    image: repo/app:1.0\n    labels: unsupported\n",
            encoding="utf-8",
        )

        result = self.run_python("--yes", "--exclude-tag-lines", "1")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(
            pending[0]["status_reason"],
            "tag-exclusion-compose-label-unsupported",
        )

    def test_unmatched_entry_remains_pending_with_reason(self) -> None:
        self.wud_file.write_text("repo/missing:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/missing:latest\n",
        )
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        pending = self.db_rows("SELECT * FROM pending_updates")
        runs = self.db_rows("SELECT * FROM update_runs")
        self.assertEqual(runs[0]["status"], "success")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "pending")
        self.assertEqual(pending[0]["status_reason"], "unmatched")

    def test_tag_update_dry_run_does_not_rewrite_compose(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")

        result = self.run_python("--dry-run", "--allow-tag-updates")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn("repo/app:1.0 -> repo/app:2.0 (tag update)", result.stdout)
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertNotRegex(self.calls(), r"compose -f .* pull")
        self.assertNotRegex(self.calls(), r"compose -f .* up -d")
        self.assertFalse(self.db_path.exists())

    def test_allowed_tag_update_rewrites_compose_and_cleans_line(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        compose_file = stack_dir / "docker-compose.yml"
        compose_file.chmod(0o640)
        before_stat = compose_file.stat()
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn("image: repo/app:2.0", compose_file.read_text(encoding="utf-8"))
        after_stat = compose_file.stat()
        self.assertEqual(after_stat.st_mode & 0o7777, before_stat.st_mode & 0o7777)
        self.assertEqual(after_stat.st_uid, before_stat.st_uid)
        self.assertEqual(after_stat.st_gid, before_stat.st_gid)
        calls = self.calls()
        self.assertRegex(calls, r"compose -f docker-compose.yml pull app")
        self.assertRegex(calls, r"compose -f docker-compose.yml up -d .* app")

    def test_network_mode_consumer_tag_update_stays_service_scoped(self) -> None:
        self.wud_file.write_text(
            "ghcr.io/linuxserver/qbittorrent:5.1.4 tag=5.2.0\n",
            encoding="utf-8",
        )
        stack_dir = self.base / "media"
        stack_dir.mkdir()
        (stack_dir / ".fake-docker-id").write_text("media\n", encoding="utf-8")
        compose_file = stack_dir / "docker-compose.yml"
        compose_file.write_text(
            "\n".join(
                [
                    "services:",
                    "  gluetun:",
                    "    image: qmcgaw/gluetun:latest",
                    "  qbittorrent:",
                    "    image: ghcr.io/linuxserver/qbittorrent:5.1.4",
                    "    network_mode: service:gluetun",
                    "  mamapi:",
                    "    image: ghcr.io/example/mamapi:latest",
                    "    network_mode: service:gluetun",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stack_state = self.fake_root / "stacks" / "media"
        stack_state.mkdir()
        (stack_state / "cids.txt").write_text(
            "cid-gluetun\ncid-qbittorrent\ncid-mamapi\n",
            encoding="utf-8",
        )
        (stack_state / "cids-gluetun.txt").write_text(
            "cid-gluetun\n",
            encoding="utf-8",
        )
        (stack_state / "cids-qbittorrent.txt").write_text(
            "cid-qbittorrent\n",
            encoding="utf-8",
        )
        for cid in ("cid-gluetun", "cid-qbittorrent", "cid-mamapi"):
            (self.fake_root / "containers" / f"{cid}.summary").write_text(
                f"/{cid}|running|healthy|0|0\n",
                encoding="utf-8",
            )
        self.set_image_state(
            "ghcr.io/linuxserver/qbittorrent:5.1.4",
            "old-qbit",
            "sha256:old-qbit",
        )
        self.set_image_after_pull(
            "ghcr.io/linuxserver/qbittorrent:5.2.0",
            "new-qbit",
            "sha256:new-qbit",
        )

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn(
            "image: ghcr.io/linuxserver/qbittorrent:5.2.0",
            compose_file.read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertRegex(calls, r"compose -f docker-compose.yml pull qbittorrent")
        self.assertRegex(calls, r"compose -f docker-compose.yml stop qbittorrent")
        self.assertRegex(
            calls,
            r"compose -f docker-compose.yml up -d --remove-orphans --no-deps qbittorrent",
        )
        self.assertNotRegex(calls, r"compose -f docker-compose.yml pull gluetun")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml pull mamapi")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml stop .*gluetun")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml stop .*mamapi")

    def test_network_mode_consumer_up_includes_missing_provider(self) -> None:
        self.wud_file.write_text(
            "ghcr.io/linuxserver/qbittorrent:5.1.4 tag=5.2.0\n",
            encoding="utf-8",
        )
        stack_dir = self.base / "media"
        stack_dir.mkdir()
        (stack_dir / ".fake-docker-id").write_text("media\n", encoding="utf-8")
        compose_file = stack_dir / "docker-compose.yml"
        compose_file.write_text(
            "\n".join(
                [
                    "services:",
                    "  gluetun:",
                    "    image: qmcgaw/gluetun:latest",
                    "  qbittorrent:",
                    "    image: ghcr.io/linuxserver/qbittorrent:5.1.4",
                    "    network_mode: service:gluetun",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stack_state = self.fake_root / "stacks" / "media"
        stack_state.mkdir()
        (stack_state / "cids.txt").write_text(
            "cid-qbittorrent\n",
            encoding="utf-8",
        )
        (stack_state / "cids-qbittorrent.txt").write_text(
            "cid-qbittorrent\n",
            encoding="utf-8",
        )
        for cid in ("cid-gluetun", "cid-qbittorrent"):
            (self.fake_root / "containers" / f"{cid}.summary").write_text(
                f"/{cid}|running|healthy|0|0\n",
                encoding="utf-8",
            )
        hook = self.fake_root / "post-up-hook"
        hook.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "set -euo pipefail",
                    'printf "cid-gluetun\\n" > "$FAKE_DOCKER_ROOT/stacks/media/cids-gluetun.txt"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        hook.chmod(0o755)
        self.set_image_state(
            "ghcr.io/linuxserver/qbittorrent:5.1.4",
            "old-qbit",
            "sha256:old-qbit",
        )
        self.set_image_after_pull(
            "ghcr.io/linuxserver/qbittorrent:5.2.0",
            "new-qbit",
            "sha256:new-qbit",
        )

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn(
            "image: ghcr.io/linuxserver/qbittorrent:5.2.0",
            compose_file.read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertRegex(calls, r"compose -f docker-compose.yml pull qbittorrent")
        self.assertRegex(calls, r"compose -f docker-compose.yml stop qbittorrent")
        self.assertRegex(
            calls,
            r"compose -f docker-compose.yml up -d --remove-orphans gluetun qbittorrent",
        )
        self.assertNotRegex(calls, r"compose -f docker-compose.yml up -d .*--no-deps")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml pull gluetun")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml stop .*gluetun")

    def test_surgical_tag_rewrite_preserves_unrelated_compose_content(self) -> None:
        compose_file = self.root / "compose.yml"
        original = (
            "x-template:\n"
            "  image: repo/app:1.0\n"
            "services:\n"
            "  app:\n"
            "    image: \"repo/app:1.0\" # keep comment\n"
            "    labels:\n"
            "      image: repo/app:1.0\n"
            "  db:\n"
            "    image: repo/db:1.0\n"
        )
        compose_file.write_text(original, encoding="utf-8")

        applied = apply_compose_tag_updates(
            compose_file,
            (
                TagUpdate(
                    old_image="repo/app:1.0",
                    desired_tag="2.0",
                    new_image="repo/app:2.0",
                    services=("app",),
                ),
            ),
        )

        self.assertEqual(applied[0].replacements, 1)
        self.assertEqual(
            compose_file.read_text(encoding="utf-8"),
            original.replace(
                '    image: "repo/app:1.0" # keep comment',
                '    image: "repo/app:2.0" # keep comment',
            ),
        )

    def test_surgical_tag_rewrite_rejects_interpolated_image(self) -> None:
        compose_file = self.root / "compose.yml"
        original = "services:\n  app:\n    image: repo/app:${TAG}\n"
        compose_file.write_text(original, encoding="utf-8")

        with self.assertRaisesRegex(ComposeTagRewriteError, "interpolation"):
            apply_compose_tag_updates(
                compose_file,
                (
                    TagUpdate(
                        old_image="repo/app:${TAG}",
                        desired_tag="2.0",
                        new_image="repo/app:2.0",
                        services=("app",),
                    ),
                ),
            )

        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)

    def test_surgical_tag_rewrite_rejects_extension_only_image(self) -> None:
        compose_file = self.root / "compose.yml"
        original = (
            "x-template:\n"
            "  image: repo/app:1.0\n"
            "services:\n"
            "  app:\n"
            "    labels:\n"
            "      image: repo/app:1.0\n"
        )
        compose_file.write_text(original, encoding="utf-8")

        with self.assertRaisesRegex(ComposeTagRewriteError, "direct string"):
            apply_compose_tag_updates(
                compose_file,
                (
                    TagUpdate(
                        old_image="repo/app:1.0",
                        desired_tag="2.0",
                        new_image="repo/app:2.0",
                        services=("app",),
                    ),
                ),
            )

        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)

    def test_surgical_tag_rewrite_rejects_invalid_yaml(self) -> None:
        compose_file = self.root / "compose.yml"
        original = "services:\n  app:\n    image: [repo/app:1.0\n"
        compose_file.write_text(original, encoding="utf-8")

        with self.assertRaisesRegex(ComposeTagRewriteError, "could not be parsed"):
            apply_compose_tag_updates(
                compose_file,
                (
                    TagUpdate(
                        old_image="repo/app:1.0",
                        desired_tag="2.0",
                        new_image="repo/app:2.0",
                        services=("app",),
                    ),
                ),
            )

        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)

    def test_exact_tag_exclusion_regex_escapes_tags(self) -> None:
        self.assertEqual(exact_tags_regex(["2.0"]), r"^2\.0$")
        self.assertEqual(
            exact_tags_regex(["2.0", "3+hotfix"]),
            r"^(?:2\.0|3\+hotfix)$",
        )
        self.assertEqual(
            merge_wud_exclude_regex(
                r"^beta",
                previous_managed=r"^2\.0$",
                next_managed=r"^(?:2\.0|3\.0)$",
            ),
            r"(?:^beta)|(?:^(?:2\.0|3\.0)$)",
        )

    def test_compose_tag_exclusion_adds_missing_label(self) -> None:
        compose_file = self.root / "compose.yml"
        compose_file.write_text("services:\n  app:\n    image: repo/app:1.0\n", encoding="utf-8")
        stack = ComposeStack(
            index=1,
            directory=self.root,
            file="compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(ServiceImage("app", "repo/app:1.0"),),
        )

        applied = apply_compose_tag_exclusions(
            compose_file,
            (
                TagExclusionUpdate(
                    stack=stack,
                    service="app",
                    image="repo/app:1.0",
                    image_repo="repo/app",
                    tag="2.0",
                    source_line=1,
                    scope="image_repo",
                ),
            ),
            existing_exact_tags={},
        )

        self.assertEqual(applied[0].tags, ("2.0",))
        self.assertIn("wud.tag.exclude=^2\\.0$$", compose_file.read_text(encoding="utf-8"))

    def test_compose_tag_exclusion_merges_existing_label_and_db_tags(self) -> None:
        compose_file = self.root / "compose.yml"
        compose_file.write_text(
            "\n".join(
                [
                    "services:",
                    "  app:",
                    "    image: repo/app:1.0",
                    "    labels:",
                    "      wud.tag.exclude: ^beta",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stack = ComposeStack(
            index=1,
            directory=self.root,
            file="compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(ServiceImage("app", "repo/app:1.0"),),
        )

        apply_compose_tag_exclusions(
            compose_file,
            (
                TagExclusionUpdate(
                    stack=stack,
                    service="app",
                    image="repo/app:1.0",
                    image_repo="repo/app",
                    tag="3.0",
                    source_line=1,
                    scope="service",
                ),
            ),
            existing_exact_tags={"app": {"2.0"}},
        )

        content = compose_file.read_text(encoding="utf-8")
        self.assertIn("wud.tag.exclude: (?:^beta)|(?:^(?:2\\.0|3\\.0)$$)", content)

    def test_compose_tag_exclusion_materializes_service_merged_map_labels(self) -> None:
        compose_file = self.root / "compose.yml"
        compose_file.write_text(
            "\n".join(
                [
                    "x-base: &base",
                    "  labels:",
                    "    wud.tag.exclude: ^beta",
                    "    foo: bar",
                    "services:",
                    "  app:",
                    "    <<: *base",
                    "    image: repo/app:1.0",
                    "  worker:",
                    "    <<: *base",
                    "    image: repo/worker:1.0",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stack = ComposeStack(
            index=1,
            directory=self.root,
            file="compose.yml",
            name="app",
            images=("repo/app:1.0", "repo/worker:1.0"),
            service_images=(
                ServiceImage("app", "repo/app:1.0"),
                ServiceImage("worker", "repo/worker:1.0"),
            ),
        )

        apply_compose_tag_exclusions(
            compose_file,
            (
                TagExclusionUpdate(
                    stack=stack,
                    service="app",
                    image="repo/app:1.0",
                    image_repo="repo/app",
                    tag="2.0",
                    source_line=1,
                    scope="service",
                ),
            ),
            existing_exact_tags={},
        )

        content = compose_file.read_text(encoding="utf-8")
        self.assertEqual(content.count("wud.tag.exclude: ^beta"), 1)
        self.assertEqual(
            content.count("wud.tag.exclude: (?:^beta)|(?:^2\\.0$$)"),
            1,
        )
        self.assertIn(
            "  app:\n"
            "    <<: *base\n"
            "    image: repo/app:1.0\n"
            "    labels:\n"
            "      wud.tag.exclude: (?:^beta)|(?:^2\\.0$$)\n"
            "      foo: bar\n",
            content,
        )
        self.assertIn(
            "  worker:\n"
            "    <<: *base\n"
            "    image: repo/worker:1.0\n",
            content,
        )
        self.assertNotIn("repo/worker:1.0\n    labels:", content)

    def test_compose_tag_exclusion_materializes_service_merged_list_labels(self) -> None:
        compose_file = self.root / "compose.yml"
        compose_file.write_text(
            "\n".join(
                [
                    "x-base: &base",
                    "  labels:",
                    "    - wud.tag.exclude=^beta",
                    "    - foo=bar",
                    "services:",
                    "  app:",
                    "    <<: *base",
                    "    image: repo/app:1.0",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stack = ComposeStack(
            index=1,
            directory=self.root,
            file="compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(ServiceImage("app", "repo/app:1.0"),),
        )

        apply_compose_tag_exclusions(
            compose_file,
            (
                TagExclusionUpdate(
                    stack=stack,
                    service="app",
                    image="repo/app:1.0",
                    image_repo="repo/app",
                    tag="2.0",
                    source_line=1,
                    scope="service",
                ),
            ),
            existing_exact_tags={},
        )

        content = compose_file.read_text(encoding="utf-8")
        self.assertEqual(content.count("- wud.tag.exclude=^beta"), 1)
        self.assertEqual(
            content.count("- wud.tag.exclude=(?:^beta)|(?:^2\\.0$$)"),
            1,
        )
        self.assertIn(
            "  app:\n"
            "    <<: *base\n"
            "    image: repo/app:1.0\n"
            "    labels:\n"
            "    - wud.tag.exclude=(?:^beta)|(?:^2\\.0$$)\n"
            "    - foo=bar\n",
            content,
        )

    def test_compose_tag_exclusion_preserves_internal_label_merge(self) -> None:
        compose_file = self.root / "compose.yml"
        compose_file.write_text(
            "\n".join(
                [
                    "x-labels: &common",
                    "  wud.tag.exclude: ^beta",
                    "  foo: bar",
                    "services:",
                    "  app:",
                    "    image: repo/app:1.0",
                    "    labels:",
                    "      <<: *common",
                    "      baz: qux",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stack = ComposeStack(
            index=1,
            directory=self.root,
            file="compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(ServiceImage("app", "repo/app:1.0"),),
        )

        apply_compose_tag_exclusions(
            compose_file,
            (
                TagExclusionUpdate(
                    stack=stack,
                    service="app",
                    image="repo/app:1.0",
                    image_repo="repo/app",
                    tag="2.0",
                    source_line=1,
                    scope="service",
                ),
            ),
            existing_exact_tags={},
        )

        content = compose_file.read_text(encoding="utf-8")
        self.assertEqual(content.count("wud.tag.exclude: ^beta"), 1)
        self.assertEqual(
            content.count("wud.tag.exclude: (?:^beta)|(?:^2\\.0$$)"),
            1,
        )
        self.assertIn("      <<: *common\n", content)
        self.assertIn("      baz: qux\n", content)

    def test_exclude_tag_line_materializes_service_merged_labels(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        compose_file = stack_dir / "docker-compose.yml"
        compose_file.write_text(
            "\n".join(
                [
                    "x-base: &base",
                    "  labels:",
                    "    wud.tag.exclude: ^beta",
                    "    foo: bar",
                    "services:",
                    "  app:",
                    "    <<: *base",
                    "    image: repo/app:1.0",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_python("--yes", "--exclude-tag-lines", "1")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        content = compose_file.read_text(encoding="utf-8")
        self.assertEqual(content.count("wud.tag.exclude: ^beta"), 1)
        self.assertIn("wud.tag.exclude: (?:^beta)|(?:^2\\.0$$)", content)
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(pending[0]["status"], "resolved")
        self.assertEqual(pending[0]["status_reason"], "tag-excluded")

    def test_compose_tag_exclusion_rejects_interpolated_image(self) -> None:
        compose_file = self.root / "compose.yml"
        original = "services:\n  app:\n    image: repo/app:${TAG}\n"
        compose_file.write_text(original, encoding="utf-8")
        stack = ComposeStack(
            index=1,
            directory=self.root,
            file="compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(ServiceImage("app", "repo/app:${TAG}"),),
        )

        with self.assertRaisesRegex(ComposeTagRewriteError, "interpolation"):
            apply_compose_tag_exclusions(
                compose_file,
                (
                    TagExclusionUpdate(
                        stack=stack,
                        service="app",
                        image="repo/app:${TAG}",
                        image_repo="repo/app",
                        tag="2.0",
                        source_line=1,
                        scope="service",
                    ),
                ),
                existing_exact_tags={},
            )

        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)

    def test_compose_tag_exclusion_rejects_service_anchor(self) -> None:
        compose_file = self.root / "compose.yml"
        original = "\n".join(
            [
                "x-base: &base",
                "  image: repo/app:1.0",
                "services:",
                "  app: *base",
                "",
            ]
        )
        compose_file.write_text(original, encoding="utf-8")
        stack = ComposeStack(
            index=1,
            directory=self.root,
            file="compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(ServiceImage("app", "repo/app:1.0"),),
        )

        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            apply_compose_tag_exclusions(
                compose_file,
                (
                    TagExclusionUpdate(
                        stack=stack,
                        service="app",
                        image="repo/app:1.0",
                        image_repo="repo/app",
                        tag="2.0",
                        source_line=1,
                        scope="service",
                    ),
                ),
                existing_exact_tags={},
            )

        content = compose_file.read_text(encoding="utf-8")
        self.assertEqual(content, original)
        self.assertNotIn("wud.tag.exclude", content)

    def test_compose_tag_exclusion_rejects_shared_label_anchor(self) -> None:
        compose_file = self.root / "compose.yml"
        original = "\n".join(
            [
                "x-labels: &common",
                "  - foo=bar",
                "services:",
                "  app:",
                "    image: repo/app:1.0",
                "    labels: *common",
                "  worker:",
                "    image: repo/worker:1.0",
                "    labels: *common",
                "",
            ]
        )
        compose_file.write_text(original, encoding="utf-8")
        stack = ComposeStack(
            index=1,
            directory=self.root,
            file="compose.yml",
            name="app",
            images=("repo/app:1.0", "repo/worker:1.0"),
            service_images=(
                ServiceImage("app", "repo/app:1.0"),
                ServiceImage("worker", "repo/worker:1.0"),
            ),
        )

        with self.assertRaisesRegex(ComposeTagRewriteError, "YAML anchors or aliases"):
            apply_compose_tag_exclusions(
                compose_file,
                (
                    TagExclusionUpdate(
                        stack=stack,
                        service="app",
                        image="repo/app:1.0",
                        image_repo="repo/app",
                        tag="2.0",
                        source_line=1,
                        scope="service",
                    ),
                ),
                existing_exact_tags={},
            )

        content = compose_file.read_text(encoding="utf-8")
        self.assertEqual(content, original)
        self.assertNotIn("wud.tag.exclude", content)

    def test_conflicting_duplicate_tag_updates_fail_before_manifest(self) -> None:
        self.wud_file.write_text(
            "repo/app:1.0 tag=2.0\nrepo/app:1.0 tag=3.0\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\nrepo/app:1.0 tag=3.0\n",
        )
        self.assertIn("Conflicting tag updates", result.stderr)
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertNotIn("manifest inspect", calls)
        self.assertNotRegex(calls, r"compose -f .* pull")

    def test_tag_update_without_service_map_fails_before_manifest(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            allow_tag_updates=True,
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
            mock.patch.object(runner.compose, "try_service_image_pairs", return_value=()),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 1, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn("could not be mapped", stderr.getvalue())
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertNotIn("manifest inspect", calls)
        self.assertNotRegex(calls, r"compose -f .* pull")

    def test_tag_update_validation_failure_rolls_back_before_pull(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            allow_tag_updates=True,
            no_color=True,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        refreshed = ComposeStack(
            index=1,
            directory=stack_dir,
            file="docker-compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(ServiceImage(service="app", image="repo/app:1.0"),),
        )
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch.object(runner, "_refresh_stack_images", return_value=refreshed),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 1, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertIn("did not resolve to rewritten image", stderr.getvalue())
        self.assertNotRegex(self.calls(), r"compose -f .* pull")

    def test_tag_override_requires_allow_tag_updates(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])

        result = self.run_python("--yes", "--tag-override", "1=3.0")

        self.assertEqual(result.returncode, 1)
        self.assertIn("--tag-override requires --allow-tag-updates", result.stderr)
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertEqual(self.calls(), "")

    def test_tag_override_rejects_invalid_tag(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")

        result = self.run_python(
            "--yes",
            "--allow-tag-updates",
            "--tag-override",
            "1=bad:value",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("--tag-override line 1 has invalid tag", result.stderr)

    def test_tag_override_dry_run_validates_manifest_without_mutation(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")

        result = self.run_python(
            "--dry-run",
            "--allow-tag-updates",
            "--tag-override",
            "1=3.0",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn("Tag override: line 1 uses tag 3.0 instead of 2.0", result.stdout)
        self.assertIn(
            "Validated remote tag: repo/app:1.0 -> repo/app:3.0",
            result.stdout,
        )
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertIn("manifest inspect repo/app:3.0", calls)
        self.assertNotRegex(calls, r"compose -f .* pull")

    def test_manifest_validation_failure_leaves_line_and_compose(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_manifest_failure("repo/app:2.0", "manifest unknown\n")

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertIn("Invalid or unavailable remote tag", result.stderr)
        self.assertIn("manifest unknown", result.stderr)
        calls = self.calls()
        self.assertIn("manifest inspect repo/app:2.0", calls)
        self.assertNotRegex(calls, r"compose -f .* pull")

    def test_tag_override_live_success_rewrites_to_override(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=wrong\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:3.0", "new", "sha256:new")

        result = self.run_python(
            "--yes",
            "--allow-tag-updates",
            "--tag-override",
            "1=3.0",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn(
            "image: repo/app:3.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertIn("manifest inspect repo/app:3.0", calls)
        self.assertRegex(calls, r"compose -f docker-compose.yml pull app")

    def test_tag_update_pull_rollback_reports_pull_progress_failure(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        (self.fake_root / "stacks" / "app" / "pull_fail").write_text(
            "",
            encoding="utf-8",
        )
        progress = []
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            allow_tag_updates=True,
            no_color=True,
        )
        runner = UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
            progress_callback=progress.append,
        )
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = runner.run()

        self.assertEqual(status, 1, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        pull_failures = [
            event
            for event in progress
            if event.phase == "pull" and event.status == "failure"
        ]
        self.assertEqual(len(pull_failures), 1)
        self.assertEqual(pull_failures[0].stack, "app")
        self.assertEqual(pull_failures[0].services, ("app",))
        self.assertEqual(pull_failures[0].line_numbers, (1,))
        self.assertIn("Pull failed after tag rewrite", pull_failures[0].message)
        event_keys = [(event.phase, event.status) for event in progress]
        self.assertLess(
            event_keys.index(("pull", "failure")),
            event_keys.index(("completion", "failure")),
        )

    def test_tag_update_with_digest_checks_rewritten_tag(self) -> None:
        self.wud_file.write_text(
            "repo/app:1.0@sha256:good tag=2.0\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:good")

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn(
            "image: repo/app:2.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )

    def test_tag_backup_failure_restores_line_without_traceback(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")

        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            allow_tag_updates=True,
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
            mock.patch(
                "wud_updater.updater._backup_compose",
                side_effect=OSError("backup denied"),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 1, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn("Could not back up compose file", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_log_file_creation_does_not_follow_existing_symlink(self) -> None:
        target = self.root / "symlink-target.log"
        target.write_text("keep\n", encoding="utf-8")
        (self.log_dir / "update-from-wud-v2-fixed.log").symlink_to(target)
        owner = OwnerConfig.from_values(str(os.getuid()), str(os.getgid()))

        with mock.patch("wud_updater.updater.file_timestamp", return_value="fixed"):
            log_file = prepare_log_file(self.log_dir, owner)

        self.assertEqual(log_file.name, "update-from-wud-v2-fixed-1.log")
        self.assertEqual(target.read_text(encoding="utf-8"), "keep\n")
        self.assertFalse(log_file.is_symlink())
        self.assertEqual(log_file.read_text(encoding="utf-8"), "")
        after_stat = log_file.stat()
        self.assertEqual((after_stat.st_uid, after_stat.st_gid), (os.getuid(), os.getgid()))

    def test_tag_update_failure_rolls_back_and_writes_incident_log(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")
        (self.fake_root / "containers" / "cid-app.healthlog").write_text(
            "new tag failed health check\n",
            encoding="utf-8",
        )
        hook = self.fake_root / "post-up-hook"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            "set -Eeuo pipefail\n"
            "compose_file=\"${2:?compose file is required}\"\n"
            "if grep -q 'repo/app:2.0' \"$compose_file\"; then\n"
            "  printf '/cid-app|running|unhealthy|1|0\\n' > \"${FAKE_DOCKER_ROOT:?}/containers/cid-app.summary\"\n"
            "else\n"
            "  printf '/cid-app|running|healthy|0|0\\n' > \"${FAKE_DOCKER_ROOT:?}/containers/cid-app.summary\"\n"
            "fi\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.0 tag=2.0\n",
        )
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        incidents = sorted(stack_dir.glob("error-2.0-*.logs"))
        self.assertTrue(incidents)
        incident = incidents[-1].read_text(encoding="utf-8")
        self.assertIn("reason=health-failed", incident)
        self.assertIn("repo/app:1.0 -> repo/app:2.0", incident)
        self.assertIn("health=unhealthy", incident)
        self.assertIn("new tag failed health check", incident)
        self.assertIn("manual_review_required=no", incident)

    def test_tag_incident_creation_does_not_follow_existing_symlink(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")
        (self.fake_root / "containers" / "cid-app.healthlog").write_text(
            "new tag failed health check\n",
            encoding="utf-8",
        )
        hook = self.fake_root / "post-up-hook"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            "set -Eeuo pipefail\n"
            "compose_file=\"${2:?compose file is required}\"\n"
            "if grep -q 'repo/app:2.0' \"$compose_file\"; then\n"
            "  printf '/cid-app|running|unhealthy|1|0\\n' > \"${FAKE_DOCKER_ROOT:?}/containers/cid-app.summary\"\n"
            "else\n"
            "  printf '/cid-app|running|healthy|0|0\\n' > \"${FAKE_DOCKER_ROOT:?}/containers/cid-app.summary\"\n"
            "fi\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
        target = self.root / "incident-target.logs"
        target.write_text("keep\n", encoding="utf-8")
        (stack_dir / "error-2.0-fixed.logs").symlink_to(target)
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            allow_tag_updates=True,
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
            mock.patch("wud_updater.updater.file_timestamp", return_value="fixed"),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 1, stderr.getvalue() + stdout.getvalue())
        self.assertEqual(target.read_text(encoding="utf-8"), "keep\n")
        incident = stack_dir / "error-2.0-fixed-1.logs"
        self.assertFalse(incident.is_symlink())
        content = incident.read_text(encoding="utf-8")
        self.assertIn("reason=health-failed", content)
        self.assertIn("repo/app:1.0 -> repo/app:2.0", content)
        self.assertIn("manual_review_required=no", content)


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import sqlite3
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from wudup.command import CommandRunner
from wudup.compose import (
    ComposeStack,
)
from wudup import updater_audit
from wudup.file_ops import OwnerConfig
from wudup.updater import (
    UpdateFromWudRunner,
)
from wudup.updater_models import (
    AppliedDigestPinUpdate,
    AppliedTagUpdate,
    UpdaterError,
    UpdaterOptions,
)


from tests.update_from_wud_helpers import (
    UpdateFromWudRunnerTestCase,
)

class UpdateFromWudAuditErrorTests(UpdateFromWudRunnerTestCase):
    def test_audit_owner_failure_marks_started_run_failed(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        runner = self.make_runner(db_path=self.db_path)
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch(
                "wudup.updater_audit.apply_sqlite_owner",
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
        runner = self.make_runner(db_path=self.db_path)
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch(
                "wudup.db.insert_update_event",
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
        runner = self.make_runner(db_path=self.db_path)
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch(
                "wudup.wud_file.remove_lines_before_run",
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
        runner = self.make_runner(db_path=self.db_path)
        stdout = StringIO()
        stderr = StringIO()

        with (
            mock.patch("wudup.updater_audit.apply_sqlite_owner") as apply_owner,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = runner.run()

        self.assertEqual(status, 0, stderr.getvalue() + stdout.getvalue())
        apply_owner.assert_any_call(
            self.db_path,
            runner.owner,
            chown_parent=True,
        )
    def test_apply_sqlite_owner_leaves_existing_db_directory_alone(self) -> None:
        db_path = self.root / "state" / "wudup.sqlite"
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

        apply_owner = mock.Mock()
        updater_audit.apply_sqlite_owner(db_path, owner, apply_owner=apply_owner)

        called_paths = [Path(call.args[0]) for call in apply_owner.call_args_list]
        self.assertEqual(called_paths, sidecars)
    def test_apply_sqlite_owner_updates_created_db_directory_and_sidecars(self) -> None:
        db_path = self.root / "created-state" / "wudup.sqlite"
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

        apply_owner = mock.Mock()
        updater_audit.apply_sqlite_owner(
            db_path,
            owner,
            chown_parent=True,
            apply_owner=apply_owner,
        )

        called_paths = [Path(call.args[0]) for call in apply_owner.call_args_list]
        self.assertEqual(called_paths, [db_path.parent, *sidecars])

    def test_apply_sqlite_owner_no_state_files_updates_created_parent_only(
        self,
    ) -> None:
        db_path = self.root / "empty-state" / "wudup.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        owner = OwnerConfig.from_values(str(os.getuid()), str(os.getgid()))

        apply_owner = mock.Mock()
        updater_audit.apply_sqlite_owner(
            db_path,
            owner,
            chown_parent=True,
            apply_owner=apply_owner,
        )

        called_paths = [Path(call.args[0]) for call in apply_owner.call_args_list]
        self.assertEqual(called_paths, [db_path.parent])

    def test_apply_sqlite_owner_no_state_files_without_parent_chown_is_noop(
        self,
    ) -> None:
        db_path = self.root / "empty-state" / "wudup.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        owner = OwnerConfig.from_values(str(os.getuid()), str(os.getgid()))

        apply_owner = mock.Mock()
        updater_audit.apply_sqlite_owner(
            db_path,
            owner,
            chown_parent=False,
            apply_owner=apply_owner,
        )

        apply_owner.assert_not_called()
    def test_applied_rewrite_validators_accept_stack_level_records(self) -> None:
        runner = UpdateFromWudRunner(
            UpdaterOptions(
                docker_base=self.base,
                wud_file=self.wud_file,
                log_dir=self.log_dir,
                max_wait=0,
                no_color=True,
            ),
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )
        stack = ComposeStack(
            index=1,
            directory=self.root,
            file="docker-compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(),
        )
        applied_tag = AppliedTagUpdate(
            old_image="repo/app:1.0",
            desired_tag="2.0",
            new_image="repo/app:2.0",
            services=(),
            replacements=1,
        )
        applied_pin = AppliedDigestPinUpdate(
            old_image="repo/app:1.0",
            resolved_tag="2.0",
            resolved_image="repo/app:2.0",
            planned_digest="sha256:index",
            final_image="repo/app@sha256:index",
            watch_tag="2.0",
            marker="wudup.resolved-tag=2.0",
            label_key="wud.tag.include",
            label_value="^2\\.0$$",
            services=(),
            replacements=1,
        )

        self.assertTrue(runner._validate_applied_tag_updates(stack, (applied_tag,), ()))
        self.assertTrue(runner._validate_applied_digest_pins(stack, (applied_pin,), ()))
    def test_tag_update_incident_log_uses_configured_owner(self) -> None:
        self.env["OUT_UID"] = str(os.getuid())
        self.env["OUT_GID"] = str(os.getgid())
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        runner = self.make_runner(allow_tag_updates=True)
        stack = ComposeStack(
            index=1,
            directory=stack_dir,
            file="docker-compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(),
        )
        applied = AppliedTagUpdate(
            old_image="repo/app:1.0",
            desired_tag="2.0",
            new_image="repo/app:2.0",
            services=("app",),
            replacements=1,
        )

        def fake_create(path: Path, content: str, **_: object) -> Path:
            self.assertIn("reason=health-failed", content)
            return path

        with mock.patch(
            "wudup.updater_logging._create_unique_text_file_exclusive",
            side_effect=fake_create,
        ) as create_file:
            runner._write_tag_incident_log(
                stack,
                ("app",),
                (applied,),
                "health-failed",
                "restored-and-healthy",
                "health=unhealthy\n",
            )

        self.assertEqual(create_file.call_args.kwargs["owner"], runner.owner)
    def test_tag_incident_log_creation_failure_warns_without_raising(self) -> None:
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        runner = self.make_runner(allow_tag_updates=True)
        stack = ComposeStack(
            index=1,
            directory=stack_dir,
            file="docker-compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(),
        )
        applied = AppliedTagUpdate(
            old_image="repo/app:1.0",
            desired_tag="2.0",
            new_image="repo/app:2.0",
            services=("app",),
            replacements=1,
        )
        with (
            mock.patch(
                "wudup.updater_logging._create_unique_text_file_exclusive",
                side_effect=OSError("permission denied"),
            ),
            mock.patch.object(runner.log, "warn") as warn,
        ):
            runner._write_tag_incident_log(
                stack,
                ("app",),
                (applied,),
                "health-failed",
                "restored-and-healthy",
                "health=unhealthy\n",
            )

        warning = warn.call_args.args[0]
        self.assertIn("Could not create tag update incident log", warning)
        self.assertIn("permission denied", warning)
    def test_tag_incident_creation_does_not_follow_existing_symlink(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")
        (self.fake_root / "containers" / "cid-app.healthlog").write_text(
            "new tag failed health check\n",
            encoding="utf-8",
        )
        self.write_tag_update_health_flip_hook()
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
            mock.patch("wudup.updater_logging.file_timestamp", return_value="fixed"),
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

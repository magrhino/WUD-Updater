from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from tests.update_from_wud_helpers import (
    UpdateFromWudRunnerTestCase,
    manifest_image,
    manifest_index,
    manifest_index_digest,
)

from wudup.command import CommandRunner
from wudup.compose import (
    ComposeStack,
    ServiceImage,
)
from wudup.updater import (
    UpdateFromWudRunner,
)
from wudup.updater_models import (
    TagStreamUpdate,
    UpdaterOptions,
)


class UpdateFromWudTagUpdateTests(UpdateFromWudRunnerTestCase):
    def make_tag_stream_runner(
        self,
        stack_directory: Path,
        *,
        compose_file: str = "docker-compose.yml",
        reported_tag: str = "1.3.0",
        selected_tag: str = "1.3.0-distroless",
    ) -> UpdateFromWudRunner:
        options = UpdaterOptions(
            docker_base=self.base,
            wud_file=self.wud_file,
            log_dir=self.log_dir,
            max_wait=0,
            assume_yes=True,
            allow_tag_updates=True,
            no_color=True,
            tag_stream_updates=(
                TagStreamUpdate(
                    line_no=1,
                    stack="app",
                    stack_directory=str(stack_directory.resolve(strict=False)),
                    compose_file=compose_file,
                    service="app",
                    current_tag="1.2.3-distroless",
                    reported_tag=reported_tag,
                    selected_tag=selected_tag,
                    decision="preserve",
                    label_key="wud.tag.include",
                    current_label_value="",
                    proposed_label_value=r"^\d+\.\d+\.\d+-distroless$$",
                    proposed_label_regex=r"^\d+\.\d+\.\d+-distroless$",
                    approved=True,
                    reason="label-added",
                ),
            ),
        )
        return UpdateFromWudRunner(
            options,
            environ=self.env,
            command_runner=CommandRunner(env=self.env),
        )

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
        runner = self.make_runner(allow_tag_updates=True)
        stdout = StringIO()
        stderr = StringIO()
        unmapped = ComposeStack(
            index=1,
            directory=stack_dir,
            file="docker-compose.yml",
            name="app",
            images=("repo/app:1.0",),
            service_images=(),
        )

        with (
            mock.patch.object(
                runner.compose,
                "discover_stacks",
                return_value=[unmapped],
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
        runner = self.make_runner(allow_tag_updates=True)
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

    def test_tag_stream_pull_failure_restores_image_and_label_together(self) -> None:
        self.wud_file.write_text(
            "repo/app:1.2.3-distroless tag=1.3.0\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack(
            "app",
            [("app", "repo/app:1.2.3-distroless", "cid-app")],
        )
        compose_file = stack_dir / "docker-compose.yml"
        original = compose_file.read_text(encoding="utf-8")
        self.set_image_state("repo/app:1.2.3-distroless", "old", "sha256:old")
        (self.fake_root / "stacks" / "app" / "pull_fail").write_text(
            "",
            encoding="utf-8",
        )
        runner = self.make_tag_stream_runner(stack_dir)

        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            status = runner.run()

        self.assertEqual(status, 1)
        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.2.3-distroless tag=1.3.0\n",
        )

    def test_tag_stream_plan_for_missing_compose_file_fails_before_mutation(
        self,
    ) -> None:
        self.wud_file.write_text(
            "repo/app:1.2.3-distroless tag=1.3.0\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack(
            "app",
            [("app", "repo/app:1.2.3-distroless", "cid-app")],
        )
        compose_file = stack_dir / "docker-compose.yml"
        original = compose_file.read_text(encoding="utf-8")
        runner = self.make_tag_stream_runner(
            stack_dir,
            compose_file="compose.yml",
        )
        stderr = StringIO()

        with redirect_stdout(StringIO()), redirect_stderr(stderr):
            status = runner.run()

        self.assertEqual(status, 1)
        self.assertIn("Tag stream plan for compose.yml", stderr.getvalue())
        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.2.3-distroless tag=1.3.0\n",
        )
        self.assertNotRegex(self.calls(), r"compose -f .* pull")

    def test_all_stale_tag_stream_plan_fails_before_no_match_success(self) -> None:
        self.wud_file.write_text(
            "repo/app:1.2.3-distroless tag=1.3.0\n",
            encoding="utf-8",
        )
        self.make_stack("other", [("other", "repo/other:1.0", "cid-other")])
        planned_directory = self.base / "app"
        runner = self.make_tag_stream_runner(planned_directory)
        stderr = StringIO()

        with redirect_stdout(StringIO()), redirect_stderr(stderr):
            status = runner.run()

        self.assertEqual(status, 1)
        self.assertIn("Tag stream plan for docker-compose.yml", stderr.getvalue())
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:1.2.3-distroless tag=1.3.0\n",
        )
        self.assertNotRegex(self.calls(), r"compose -f .* pull")

    def test_tag_stream_plan_fails_when_pending_input_becomes_empty(self) -> None:
        self.wud_file.write_text("", encoding="utf-8")
        planned_directory = self.base / "app"
        runner = self.make_tag_stream_runner(planned_directory)
        stderr = StringIO()

        with redirect_stdout(StringIO()), redirect_stderr(stderr):
            status = runner.run()

        self.assertEqual(status, 1)
        self.assertIn("Tag stream plan for docker-compose.yml", stderr.getvalue())
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertNotIn("compose", self.calls())

    def test_tag_stream_plan_with_stale_reported_tag_fails_closed(self) -> None:
        self.wud_file.write_text(
            "repo/app:1.2.3-distroless tag=1.3.0\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack(
            "app",
            [("app", "repo/app:1.2.3-distroless", "cid-app")],
        )
        compose_file = stack_dir / "docker-compose.yml"
        original = compose_file.read_text(encoding="utf-8")
        runner = self.make_tag_stream_runner(
            stack_dir,
            reported_tag="1.3.1",
            selected_tag="1.3.0",
        )
        stderr = StringIO()

        with redirect_stdout(StringIO()), redirect_stderr(stderr):
            status = runner.run()

        self.assertEqual(status, 1)
        self.assertIn("Tag stream plan for docker-compose.yml", stderr.getvalue())
        self.assertEqual(compose_file.read_text(encoding="utf-8"), original)
        self.assertNotRegex(self.calls(), r"compose -f .* pull")

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
    def test_ghcr_tag_update_with_digest_checks_rewritten_tag(self) -> None:
        self.wud_file.write_text(
            "acme/app:1.0@sha256:child tag=2.0\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "ghcr.io/acme/app:1.0", "cid-app")])
        self.set_image_state("ghcr.io/acme/app:1.0", "sha256:old", "sha256:old-index")
        self.set_image_after_pull(
            "ghcr.io/acme/app:2.0",
            "sha256:config",
            "sha256:index",
        )
        self.set_manifest_stdout(
            "ghcr.io/acme/app:2.0",
            manifest_index("sha256:child"),
        )
        self.set_manifest_stdout(
            "ghcr.io/acme/app@sha256:child",
            manifest_image("sha256:config"),
        )

        status, stdout, stderr = self.run_direct(allow_tag_updates=True)

        self.assertEqual(status, 0, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn(
            "image: ghcr.io/acme/app:2.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertIn("manifest inspect ghcr.io/acme/app:2.0", calls)
        self.assertIn("manifest inspect ghcr.io/acme/app@sha256:child", calls)
    def test_stale_digest_blocks_tag_rewrite_before_mutation(self) -> None:
        self.wud_file.write_text(
            "acme/app:1.0@sha256:stale tag=2.0\n",
            encoding="utf-8",
        )
        stack_dir = self.make_stack("app", [("app", "ghcr.io/acme/app:1.0", "cid-app")])
        self.set_image_state("ghcr.io/acme/app:1.0", "sha256:old", "sha256:old")
        self.set_image_after_pull(
            "ghcr.io/acme/app:2.0",
            "sha256:config",
            "sha256:index",
        )
        self.set_manifest_stdout(
            "ghcr.io/acme/app:2.0",
            manifest_index_digest("sha256:current", "sha256:child"),
        )
        self.set_manifest_stdout(
            "ghcr.io/acme/app@sha256:stale",
            manifest_image("sha256:config"),
        )

        status, stdout, stderr = self.run_direct(allow_tag_updates=True)

        self.assertEqual(status, 1, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertIn(
            "image: ghcr.io/acme/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertNotRegex(calls, r"compose -f docker-compose.yml pull app")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml up -d .* app")
        log_text = max(self.log_dir.glob("update-from-wud-v2-*.log")).read_text(
            encoding="utf-8"
        )
        self.assertNotIn("Rolled back to previous tag", log_text)
        self.assertIn("Pending WUD entry for line 1 is stale", log_text)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("reason=stale-pending-digest", report)
        self.assertIn("wud_entries_restored=no", report)
        self.assertIn("Stale pending digest entry was removed", report)
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(pending[0]["status_reason"], "stale-pending-digest")
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
                "wudup.compose_rewrite._backup_compose",
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
    def test_tag_update_failure_rolls_back_and_writes_incident_log(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")
        (self.fake_root / "containers" / "cid-app.healthlog").write_text(
            "new tag failed health check\n",
            encoding="utf-8",
        )
        self.write_tag_update_health_flip_hook()

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

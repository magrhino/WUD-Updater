from __future__ import annotations

import json
from unittest import mock

from tests.update_from_wud_helpers import (
    UpdateFromWudRunnerTestCase,
)

from wudup.updater import (
    UpdateFromWudRunner,
)
from wudup.updater_models import (
    UpdaterError,
    UpdaterOptions,
)


class UpdateFromWudRecreateTests(UpdateFromWudRunnerTestCase):
    def test_up_wait_failure_writes_error_report_with_command_output(self) -> None:
        self.env["FAKE_COMPOSE_UP_WAIT"] = "1"
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
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
        self.assertIn("health: container=cid-app status=running health=healthy", report)

    def test_stopped_service_is_recreated_without_being_started(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", None)])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        calls = self.calls()
        self.assertIn(
            "compose -f docker-compose.yml up -d --remove-orphans --no-deps --no-start app",
            calls,
        )
        self.assertNotIn("compose -f docker-compose.yml stop app", calls)
        self.assertNotIn("--wait", calls)
        event = self.db_rows(
            "SELECT metadata_json FROM update_events ORDER BY id DESC LIMIT 1"
        )[0]
        self.assertEqual(
            json.loads(str(event["metadata_json"])),
            {
                "reason": "updated",
                "runtime_state_after": "not-running",
                "runtime_state_before": "not-running",
                "stopped_services_after": ["app"],
                "stopped_services_before": ["app"],
            },
        )

    def test_update_fails_closed_when_runtime_state_cannot_be_verified(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        (self.fake_root / "ps_fail").write_text(
            "",
            encoding="utf-8",
        )

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:latest\n",
        )
        calls = self.calls()
        self.assertNotIn("compose -f docker-compose.yml pull", calls)
        self.assertNotIn("compose -f docker-compose.yml up", calls)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("reason=runtime-state-unavailable", report)

    def test_update_fails_closed_for_mixed_scaled_service_runtime(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        stack_dir = self.make_stack(
            "app",
            [("app", "repo/app:latest", "cid-running")],
        )
        runtime_prefix = (
            f"{stack_dir}\t{stack_dir / 'docker-compose.yml'}\tapp\tapp\tFalse\t"
        )
        (self.fake_root / "compose-runtime-all.tsv").write_text(
            f"{runtime_prefix}running\n{runtime_prefix}exited\n",
            encoding="utf-8",
        )
        self.set_image_state("repo/app:latest", "old", "sha256:old")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:latest\n",
        )
        calls = self.calls()
        self.assertIn("ps --all --format", calls)
        self.assertNotIn("compose -f docker-compose.yml pull", calls)
        self.assertNotIn("compose -f docker-compose.yml up", calls)
        self.assertNotIn("compose -f docker-compose.yml stop", calls)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("runtime states: exited, running", report)

    def test_stopped_oneoff_container_does_not_make_service_mixed(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        stack_dir = self.make_stack(
            "app",
            [("app", "repo/app:latest", "cid-running")],
        )
        runtime_prefix = (
            f"{stack_dir}\t{stack_dir / 'docker-compose.yml'}\tapp\tapp\t"
        )
        (self.fake_root / "compose-runtime-all.tsv").write_text(
            f"{runtime_prefix}False\trunning\n"
            f"{runtime_prefix}True\texited\n",
            encoding="utf-8",
        )
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")

    def test_stack_update_fails_closed_when_service_list_is_unavailable(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        (self.fake_root / "containers" / "cid-app.labels").write_text(
            "WUD-UPDATER-RECREATE-STACK=true\n",
            encoding="utf-8",
        )
        (self.fake_root / "stacks" / "app" / "config_services_fail").write_text(
            "",
            encoding="utf-8",
        )

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertEqual(
            self.wud_file.read_text(encoding="utf-8"),
            "repo/app:latest\n",
        )
        calls = self.calls()
        self.assertIn("compose -f docker-compose.yml config --services", calls)
        self.assertNotIn("compose -f docker-compose.yml pull", calls)
        self.assertNotIn("compose -f docker-compose.yml up", calls)
        self.assertNotIn("compose -f docker-compose.yml stop", calls)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("reason=runtime-state-unavailable", report)

    def test_stopped_service_tag_update_preserves_stopped_state(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", None)])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "image: repo/app:2.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        self.assertIn("--no-start app", self.calls())
        self.assertNotIn("compose -f docker-compose.yml stop app", self.calls())

    def test_stopped_recreate_failure_does_not_touch_running_sibling(self) -> None:
        self.wud_file.write_text(
            "repo/app:latest\nrepo/worker:latest\n",
            encoding="utf-8",
        )
        self.make_stack(
            "app",
            [
                ("app", "repo/app:latest", "cid-app"),
                ("worker", "repo/worker:latest", None),
            ],
        )
        (self.fake_root / "containers" / "cid-app.labels").write_text(
            "WUD-UPDATER-RECREATE-STACK=true\n",
            encoding="utf-8",
        )
        for image in ("repo/app:latest", "repo/worker:latest"):
            self.set_image_state(image, f"old-{image}", "sha256:old")
            self.set_image_after_pull(image, f"new-{image}", "sha256:new")
        (self.fake_root / "stacks" / "app" / "up_no_start_fail").write_text(
            "",
            encoding="utf-8",
        )

        result = self.run_python("--yes", "--mode", "pause")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        calls = self.calls()
        self.assertIn("--no-start worker", calls)
        self.assertNotIn("compose -f docker-compose.yml stop app", calls)
        self.assertNotIn("compose -f docker-compose.yml pause app", calls)
        self.assertNotIn("compose -f docker-compose.yml unpause app", calls)
        worker_event = self.db_rows(
            "SELECT metadata_json FROM update_events "
            "WHERE service_name = 'worker' ORDER BY id DESC LIMIT 1"
        )[0]
        metadata = json.loads(str(worker_event["metadata_json"]))
        self.assertEqual(metadata["runtime_state_before"], "not-running")
        self.assertEqual(metadata["runtime_state_after"], "unknown")
        self.assertEqual(metadata["stopped_services_before"], ["worker"])
        self.assertNotIn("stopped_services_after", metadata)

    def test_tag_rollback_recovers_running_sibling_when_no_start_fails(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack(
            "app",
            [
                ("app", "repo/app:1.0", "cid-app"),
                ("worker", "repo/worker:latest", None),
            ],
        )
        (self.fake_root / "containers" / "cid-app.labels").write_text(
            "WUD-UPDATER-RECREATE-STACK=true\n",
            encoding="utf-8",
        )
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")
        (self.fake_root / "stacks" / "app" / "up_no_start_fail").write_text(
            "",
            encoding="utf-8",
        )

        result = self.run_python("--yes", "--allow-tag-updates")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        calls = self.calls()
        self.assertNotIn("compose -f docker-compose.yml stop app", calls)
        self.assertIn(
            "compose -f docker-compose.yml up -d --remove-orphans --no-deps app",
            calls,
        )

    def test_verified_tag_rollback_records_stopped_sibling_after_state(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        self.make_stack(
            "app",
            [
                ("app", "repo/app:1.0", "cid-app"),
                ("worker", "repo/worker:latest", None),
            ],
        )
        (self.fake_root / "containers" / "cid-app.labels").write_text(
            "WUD-UPDATER-RECREATE-STACK=true\n",
            encoding="utf-8",
        )
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")
        (self.fake_root / "stacks" / "app" / "unpause_fail").write_text(
            "",
            encoding="utf-8",
        )

        result = self.run_python(
            "--yes",
            "--allow-tag-updates",
            "--mode",
            "pause",
        )

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        event = self.db_rows(
            "SELECT metadata_json FROM update_events ORDER BY id DESC LIMIT 1"
        )[0]
        metadata = json.loads(str(event["metadata_json"]))
        self.assertEqual(metadata["stopped_services_before"], ["worker"])
        self.assertEqual(metadata["stopped_services_after"], ["worker"])

    def test_failed_pre_recreate_rollback_keeps_after_state_unknown(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:1.0", None)])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        (self.fake_root / "stacks" / "app" / "up_no_start_fail").write_text(
            "",
            encoding="utf-8",
        )
        runner = self.make_runner(allow_tag_updates=True)

        with mock.patch.object(runner, "_refresh_stack_images", return_value=None):
            status = runner.run()

        self.assertEqual(status, 1)
        event = self.db_rows(
            "SELECT metadata_json FROM update_events ORDER BY id DESC LIMIT 1"
        )[0]
        metadata = json.loads(str(event["metadata_json"]))
        self.assertEqual(metadata["runtime_state_before"], "not-running")
        self.assertEqual(metadata["runtime_state_after"], "unknown")
        self.assertEqual(metadata["stopped_services_before"], ["app"])
        self.assertNotIn("stopped_services_after", metadata)

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

    def test_stopped_service_pull_failure_records_known_after_state(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", None)])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        (self.fake_root / "stacks" / "app" / "pull_fail").write_text(
            "",
            encoding="utf-8",
        )

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        event = self.db_rows(
            "SELECT metadata_json FROM update_events ORDER BY id DESC LIMIT 1"
        )[0]
        self.assertEqual(
            json.loads(str(event["metadata_json"])),
            {
                "failure_phase": "pull",
                "health_evidence": "service_disappeared",
                "reason": "pull-failed",
                "runtime_state_after": "not-running",
                "runtime_state_before": "not-running",
                "stopped_services_after": ["app"],
                "stopped_services_before": ["app"],
            },
        )
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
    def test_tag_update_compose_up_failure_unpauses_before_rollback(self) -> None:
        self.wud_file.write_text("repo/app:1.0 tag=2.0\n", encoding="utf-8")
        stack_dir = self.make_stack("app", [("app", "repo/app:1.0", "cid-app")])
        self.set_image_state("repo/app:1.0", "old", "sha256:old")
        self.set_image_after_pull("repo/app:2.0", "new", "sha256:new")
        stack_state = self.fake_root / "stacks" / "app"
        (stack_state / "up_fail").write_text("", encoding="utf-8")

        result = self.run_python("--yes", "--allow-tag-updates", "--mode", "pause")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn(
            "image: repo/app:1.0",
            (stack_dir / "docker-compose.yml").read_text(encoding="utf-8"),
        )
        calls = self.calls()
        failed_up = calls.index("compose -f docker-compose.yml up")
        unpause = calls.index("compose -f docker-compose.yml unpause app")
        rollback_up = calls.rindex("compose -f docker-compose.yml up")
        self.assertLess(failed_up, unpause)
        self.assertLess(unpause, rollback_up)
    def test_run_rejects_invalid_mode(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        options = UpdaterOptions(mode="invalid", docker_base=self.base, wud_file=self.wud_file, log_dir=self.log_dir)
        runner = UpdateFromWudRunner(options)
        with self.assertRaisesRegex(UpdaterError, "--mode must be pause\\|stop\\|live"):
            runner.run()
    def test_run_rejects_negative_max_wait(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        options = UpdaterOptions(max_wait=-1, docker_base=self.base, wud_file=self.wud_file, log_dir=self.log_dir)
        runner = UpdateFromWudRunner(options)
        with self.assertRaisesRegex(UpdaterError, "--max-wait must be an integer number of seconds"):
            runner.run()
    def test_run_rejects_tag_overrides_without_allow_tag_updates(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        from wudup.updater_models import TagOverride
        options = UpdaterOptions(tag_overrides=(TagOverride(1, "tag"),), allow_tag_updates=False, docker_base=self.base, wud_file=self.wud_file, log_dir=self.log_dir)
        runner = UpdateFromWudRunner(options)
        with self.assertRaisesRegex(UpdaterError, "--tag-override requires --allow-tag-updates"):
            runner.run()
    def test_run_rejects_missing_wud_file(self) -> None:
        options = UpdaterOptions(docker_base=self.base, wud_file=self.base / "missing.todo", log_dir=self.log_dir)
        runner = UpdateFromWudRunner(options)
        with self.assertRaisesRegex(UpdaterError, "List file not found"):
            runner.run()
    def test_run_acquires_lock_if_parent_held(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        self.env["WUD_LOCK_HELD_BY_PARENT"] = "1"
        from wudup.locks import lock_dir_for
        lock_dir_for(self.wud_file).mkdir(parents=True)
        result = self.run_python("--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(lock_dir_for(self.wud_file).exists())
    def test_recreate_compose_unpause_failure_aborts_without_rewrite(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        stack_state = self.fake_root / "stacks" / "app"
        (stack_state / "unpause_fail").write_text("", encoding="utf-8")

        result = self.run_python("--yes", "--mode", "pause")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("reason=unpause-failed", report)
        self.assertIn("phase=unpause", report)
        self.assertIn("compose -f docker-compose.yml unpause app", report)
    def test_recreate_compose_up_failure_and_unpause_failure_aborts_without_rewrite(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        stack_state = self.fake_root / "stacks" / "app"
        (stack_state / "up_fail").write_text("", encoding="utf-8")
        (stack_state / "unpause_fail").write_text("", encoding="utf-8")

        result = self.run_python("--yes", "--mode", "pause")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("reason=unpause-failed", report)
        self.assertIn("phase=unpause", report)
    def test_recreate_health_wait_failure_aborts_without_rewrite(self) -> None:
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        (self.fake_root / "containers" / "cid-app.summary").write_text("/cid-app|running|unhealthy|1|0\n", encoding="utf-8")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("reason=health-failed", report)
        self.assertIn("phase=health", report)
        self.assertIn("health: container=cid-app status=running health=unhealthy", report)
    def test_recreate_stop_failure_and_up_failure_without_rewrite(self) -> None:
        self.env["FAKE_COMPOSE_UP_WAIT"] = "1"
        self.wud_file.write_text("repo/app:latest\n", encoding="utf-8")
        self.make_stack("app", [("app", "repo/app:latest", "cid-app")])
        self.set_image_state("repo/app:latest", "old", "sha256:old")
        self.set_image_after_pull("repo/app:latest", "new", "sha256:new")
        stack_state = self.fake_root / "stacks" / "app"
        (self.fake_root / "containers" / "cid-app.labels").write_text(
            "WUD-UPDATER-RECREATE-STACK=true\n",
            encoding="utf-8",
        )
        (stack_state / "stop_fail").write_text("", encoding="utf-8")
        (stack_state / "stop_stderr").write_text("container stop failed\n", encoding="utf-8")
        (stack_state / "up_fail").write_text("", encoding="utf-8")
        (stack_state / "up_stderr").write_text("recovery up failed\n", encoding="utf-8")

        result = self.run_python("--yes")

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("phase=up", report)
        self.assertIn("reason=up-or-health-failed", report)
        self.assertIn("recovery up failed", report)
    def test_network_mode_consumer_tag_update_stays_service_scoped(self) -> None:
        compose_file = self.prepare_network_mode_media_stack(
            include_provider_cid=True,
            include_extra_consumer=True,
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
    def test_network_mode_consumer_preserves_stopped_provider(self) -> None:
        compose_file = self.prepare_network_mode_media_stack(
            include_provider_cid=False,
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
            r"compose -f docker-compose.yml up -d --remove-orphans --no-deps --no-start gluetun",
        )
        self.assertRegex(
            calls,
            r"compose -f docker-compose.yml up -d --remove-orphans --no-deps qbittorrent",
        )
        self.assertNotRegex(calls, r"compose -f docker-compose.yml pull gluetun")
        self.assertNotRegex(calls, r"compose -f docker-compose.yml stop .*gluetun")
        event = self.db_rows(
            "SELECT metadata_json FROM update_events ORDER BY id DESC LIMIT 1"
        )[0]
        metadata = json.loads(str(event["metadata_json"]))
        self.assertEqual(metadata["stopped_services_before"], ["gluetun"])
        self.assertEqual(metadata["stopped_services_after"], ["gluetun"])

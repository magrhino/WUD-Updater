from __future__ import annotations

import json
import unittest

from wudup.compose import (
    ComposeStack,
    ServiceImage,
)
from wudup.updater_lifecycle_health import _updated_images
from wudup.updater_models import (
    ImageState,
    Match,
    STALE_PENDING_DIGEST_REASON,
)
from wudup.wud_file import parse_wud_text


from tests.update_from_wud_helpers import (
    UpdateFromWudRunnerTestCase,
    manifest_index,
    manifest_image,
)

class UpdateFromWudCoreTests(UpdateFromWudRunnerTestCase):
    def test_expected_digest_failure_reason_requires_all_matches_stale(self) -> None:
        stack_dir = self.make_stack(
            "app",
            [
                ("stale", "repo/stale:latest", "cid-stale"),
                ("fresh", "repo/fresh:latest", "cid-fresh"),
            ],
        )
        stack = ComposeStack(
            index=2,
            directory=stack_dir,
            file="docker-compose.yml",
            name="app",
            images=("repo/stale:latest", "repo/fresh:latest"),
            service_images=(
                ServiceImage("stale", "repo/stale:latest"),
                ServiceImage("fresh", "repo/fresh:latest"),
            ),
        )
        targets = parse_wud_text(
            "repo/stale:latest@sha256:stale\n"
            "repo/fresh:latest@sha256:fresh\n"
        ).targets
        matches = (
            Match(
                stack=stack,
                target=targets[0],
                resolved="repo/stale:latest",
                compose_image="repo/stale:latest",
                service="stale",
            ),
            Match(
                stack=stack,
                target=targets[1],
                resolved="repo/fresh:latest",
                compose_image="repo/fresh:latest",
                service="fresh",
            ),
        )
        runner = self.make_runner()

        runner.stale_pending_digest_lines.add((stack.index, targets[0].line_no))
        self.assertEqual(
            runner.lifecycle._expected_digest_failure_reason(stack, matches),
            "expected-digest-not-reached",
        )

        runner.stale_pending_digest_lines.add((stack.index, targets[1].line_no))
        self.assertEqual(
            runner.lifecycle._expected_digest_failure_reason(stack, matches),
            STALE_PENDING_DIGEST_REASON,
        )
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
        self.assertEqual(events[0]["old_image_id"], "old-app")
        self.assertEqual(events[0]["new_image_id"], "new-app")
        self.assertTrue(events[0]["old_digest"].endswith("@sha256:old-app"))
        self.assertTrue(events[0]["new_digest"].endswith("@sha256:new-app"))
        self.assertEqual(json.loads(events[0]["metadata_json"]), {"reason": "updated"})
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
    def test_non_ghcr_manifest_unavailable_warns_and_allows_update(self) -> None:
        self.wud_file.write_text("quay.io/acme/app:latest@sha256:good\n", encoding="utf-8")
        self.make_stack("app", [("app", "quay.io/acme/app:latest", "cid-app")])
        self.set_image_state("quay.io/acme/app:latest", "old", "sha256:old")
        self.set_image_after_pull("quay.io/acme/app:latest", "new", "sha256:bad")
        self.set_manifest_failure("quay.io/acme/app:latest", "manifest unavailable")

        status, stdout, stderr = self.run_direct()

        self.assertEqual(status, 0, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        self.assertRegex(self.calls(), r"compose -f docker-compose.yml up -d .* app")
        pending = self.db_rows("SELECT * FROM pending_updates")
        runs = self.db_rows("SELECT * FROM update_runs")
        self.assertEqual(runs[0]["status"], "success")
        self.assertEqual(pending[0]["status"], "resolved")
        self.assertEqual(pending[0]["status_reason"], "updated")
        log_text = max(self.log_dir.glob("update-from-wud-v2-*.log")).read_text(
            encoding="utf-8"
        )
        self.assertIn("Digest verification was inconclusive", log_text)
        self.assertIn("Digest verification reason: manifest-unavailable-untrusted", log_text)
    def test_non_ghcr_platform_digest_allows_registry_verification(self) -> None:
        self.wud_file.write_text("acme/app:latest@sha256:child\n", encoding="utf-8")
        self.make_stack("app", [("app", "quay.io/acme/app:latest", "cid-app")])
        self.set_image_state("quay.io/acme/app:latest", "sha256:old", "sha256:old-index")
        self.set_image_after_pull(
            "quay.io/acme/app:latest",
            "sha256:config",
            "sha256:index",
        )
        self.set_manifest_stdout(
            "quay.io/acme/app:latest",
            manifest_index("sha256:child"),
        )
        self.set_manifest_stdout(
            "quay.io/acme/app@sha256:child",
            manifest_image("sha256:config"),
        )

        status, stdout, stderr = self.run_direct()

        self.assertEqual(status, 0, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        calls = self.calls()
        self.assertIn("manifest inspect quay.io/acme/app:latest", calls)
        self.assertIn("manifest inspect quay.io/acme/app@sha256:child", calls)
        self.assertRegex(calls, r"compose -f docker-compose.yml up -d .* app")
    def test_non_ghcr_stale_digest_removes_line_and_reports_stale_input(self) -> None:
        self.wud_file.write_text("quay.io/acme/app:latest@sha256:stale\n", encoding="utf-8")
        self.make_stack("app", [("app", "quay.io/acme/app:latest", "cid-app")])
        self.set_image_state("quay.io/acme/app:latest", "sha256:old", "sha256:old-index")
        self.set_image_after_pull(
            "quay.io/acme/app:latest",
            "sha256:config",
            "sha256:index",
        )
        self.set_manifest_stdout(
            "quay.io/acme/app:latest",
            manifest_index("sha256:child"),
        )
        self.set_manifest_stdout(
            "quay.io/acme/app@sha256:stale",
            manifest_image("sha256:config"),
        )

        status, stdout, stderr = self.run_direct()

        self.assertEqual(status, 1, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        calls = self.calls()
        self.assertIn("manifest inspect quay.io/acme/app:latest", calls)
        self.assertIn("manifest inspect quay.io/acme/app@sha256:stale", calls)
        self.assertNotRegex(calls, r"compose -f .* up -d")
        log_text = max(self.log_dir.glob("update-from-wud-v2-*.log")).read_text(
            encoding="utf-8"
        )
        self.assertIn("Pending WUD entry for line 1 is stale", log_text)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("reason=stale-pending-digest", report)
        self.assertIn("wud_entries_restored=no", report)
        pending = self.db_rows("SELECT * FROM pending_updates")
        runs = self.db_rows("SELECT * FROM update_runs")
        self.assertEqual(runs[0]["status"], "failure")
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(pending[0]["status_reason"], "stale-pending-digest")
    def test_ghcr_platform_digest_allows_registryless_wud_line(self) -> None:
        self.wud_file.write_text("acme/app:latest@sha256:child\n", encoding="utf-8")
        self.make_stack("app", [("app", "ghcr.io/acme/app:latest", "cid-app")])
        self.set_image_state("ghcr.io/acme/app:latest", "sha256:old", "sha256:old-index")
        self.set_image_after_pull(
            "ghcr.io/acme/app:latest",
            "sha256:config",
            "sha256:index",
        )
        self.set_manifest_stdout(
            "ghcr.io/acme/app:latest",
            manifest_index("sha256:child"),
        )
        self.set_manifest_stdout(
            "ghcr.io/acme/app@sha256:child",
            manifest_image("sha256:config"),
        )

        status, stdout, stderr = self.run_direct()

        self.assertEqual(status, 0, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        calls = self.calls()
        self.assertIn("manifest inspect ghcr.io/acme/app:latest", calls)
        self.assertIn("manifest inspect ghcr.io/acme/app@sha256:child", calls)
        self.assertRegex(calls, r"compose -f docker-compose.yml up -d .* app")
    def test_ghcr_stale_digest_removes_line_and_reports_stale_input(self) -> None:
        self.wud_file.write_text("acme/app:latest@sha256:stale\n", encoding="utf-8")
        self.make_stack("app", [("app", "ghcr.io/acme/app:latest", "cid-app")])
        self.set_image_state("ghcr.io/acme/app:latest", "sha256:old", "sha256:old-index")
        self.set_image_after_pull(
            "ghcr.io/acme/app:latest",
            "sha256:config",
            "sha256:index",
        )
        self.set_manifest_stdout(
            "ghcr.io/acme/app:latest",
            manifest_index("sha256:child"),
        )
        self.set_manifest_stdout(
            "ghcr.io/acme/app@sha256:stale",
            manifest_image("sha256:config"),
        )

        status, stdout, stderr = self.run_direct()

        self.assertEqual(status, 1, stderr + stdout)
        self.assertEqual(self.wud_file.read_text(encoding="utf-8"), "")
        calls = self.calls()
        self.assertIn("manifest inspect ghcr.io/acme/app:latest", calls)
        self.assertIn("manifest inspect ghcr.io/acme/app@sha256:stale", calls)
        self.assertNotRegex(calls, r"compose -f .* up -d")
        log_text = max(self.log_dir.glob("update-from-wud-v2-*.log")).read_text(
            encoding="utf-8"
        )
        self.assertIn("Pending WUD entry for line 1 is stale", log_text)
        self.assertIn("Digest verification reason: stale-digest", log_text)
        report = self.latest_error_report().read_text(encoding="utf-8")
        self.assertIn("reason=stale-pending-digest", report)
        self.assertIn("wud_entries_restored=no", report)
        pending = self.db_rows("SELECT * FROM pending_updates")
        self.assertEqual(pending[0]["status"], "failed")
        self.assertEqual(pending[0]["status_reason"], "stale-pending-digest")
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



class UpdatedImagesTests(unittest.TestCase):
    def test_matches_rewritten_image_reference_by_repository_identity(self) -> None:
        before = {
            "repo/app:1.0": ImageState(
                image_id="sha256:old",
                digest="repo/app:1.0@sha256:old",
            ),
        }
        after = {
            "repo/app:2.0": ImageState(
                image_id="sha256:new",
                digest="repo/app:2.0@sha256:new",
            ),
        }

        self.assertEqual(
            _updated_images(before, after),
            [("repo/app:1.0", after["repo/app:2.0"])],
        )

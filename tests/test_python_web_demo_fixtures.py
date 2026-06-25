from __future__ import annotations

import json
import itertools
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wudup import web_demo_fixtures, web_wud_api
from wudup.web_retag_identity import retag_target_id
from wudup.web_models import (
    ApplyJobLogResponse,
    ApplyJobResponse,
    AuthSessionResponse,
    DiagnosticsSupportBundleResponse,
    DoctorResponse,
    OnboardingChecklistResponse,
    PendingRemovalPlanResponse,
    PendingResponse,
    PlanResponse,
    ReleaseNotesResponse,
    RetagPreviewJobResponse,
    RetagPlanResponse,
    RetagTargetsResponse,
    RunDetail,
    RunLogResponse,
    RunSummary,
    SelfUpdatePlanResponse,
    SelfUpdateResponse,
    ServicePolicyRecord,
    SettingsResponse,
    SetupStatusResponse,
    SnoozeRecord,
    StatusResponse,
    TagExclusionRuleRecord,
    UpdateTargetsResponse,
)


class WebDemoFixtureGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("fixture generation must not use network"),
        ):
            cls.fixtures = web_demo_fixtures.generate_static_demo_fixtures()

    def test_generated_responses_validate_against_web_models(self) -> None:
        data = self.fixtures

        self._validate_core_responses(data)
        self._validate_plan_fixtures(data)
        self._validate_state_records(data)
        self._validate_run_records(data)

    def test_demo_retag_target_id_treats_none_project_directory_as_empty(
        self,
    ) -> None:
        item = {
            "directory": "/docker/media",
            "compose_file": "docker-compose.yml",
            "project_directory": None,
            "stack": "media",
            "service": "app",
        }

        self.assertEqual(
            web_demo_fixtures._demo_retag_target_id(item),
            retag_target_id(
                "/docker/media",
                "docker-compose.yml",
                "",
                "media",
                "app",
            ),
        )

    def test_retag_target_id_canonicalizes_empty_values(self) -> None:
        self.assertEqual(
            retag_target_id(
                "/docker/media",
                "docker-compose.yml",
                None,
                "media",
                "app",
            ),
            retag_target_id(
                "/docker/media",
                "docker-compose.yml",
                "",
                "media",
                "app",
            ),
        )

    def _validate_core_responses(self, data: dict[str, object]) -> None:
        AuthSessionResponse.model_validate(data["auth"]["session"])
        SetupStatusResponse.model_validate(data["auth"]["setupStatus"])
        StatusResponse.model_validate(data["status"])
        SettingsResponse.model_validate(data["settings"])
        DoctorResponse.model_validate(data["doctor"])
        OnboardingChecklistResponse.model_validate(data["onboarding"])
        PendingResponse.model_validate(data["pending"])
        UpdateTargetsResponse.model_validate(data["updateTargets"])
        RetagTargetsResponse.model_validate(data["retagTargets"])
        ReleaseNotesResponse.model_validate(data["releaseNotes"])
        SelfUpdateResponse.model_validate(data["selfUpdate"])
        SelfUpdatePlanResponse.model_validate(data["selfUpdatePlan"])
        DiagnosticsSupportBundleResponse.model_validate(data["diagnostics"])

    def _validate_plan_fixtures(self, data: dict[str, object]) -> None:
        for case in data["planCases"]:
            PlanResponse.model_validate(case["response"])
            for fixture in [case.get("jobTemplate")]:
                if fixture is not None:
                    self._validate_job_fixture(fixture)
        for case in data["removalCases"]:
            PendingRemovalPlanResponse.model_validate(case["response"])
        for case in data["retagCases"]:
            RetagPlanResponse.model_validate(case["response"])
            RetagPreviewJobResponse.model_validate(case["preview"]["queued"])
            RetagPreviewJobResponse.model_validate(case["preview"]["complete"])
            if case.get("jobTemplate") is not None:
                self._validate_job_fixture(case["jobTemplate"])

    def _validate_state_records(self, data: dict[str, object]) -> None:
        for record in data["servicePolicies"]:
            ServicePolicyRecord.model_validate(record)
        for records in data["snoozes"].values():
            for record in records:
                SnoozeRecord.model_validate(record)
        for records in data["tagExclusions"].values():
            for record in records:
                TagExclusionRuleRecord.model_validate(record)

    def _validate_run_records(self, data: dict[str, object]) -> None:
        for summary in data["runs"]["summaries"]:
            RunSummary.model_validate(summary)
        for detail in data["runs"]["details"].values():
            RunDetail.model_validate(detail)
        for log in data["runs"]["logs"].values():
            RunLogResponse.model_validate(log)

    def _validate_job_fixture(self, fixture: dict[str, object]) -> None:
        ApplyJobResponse.model_validate(fixture["queued"])
        ApplyJobResponse.model_validate(fixture["terminal"])
        ApplyJobLogResponse.model_validate(fixture["log"])
        if fixture["run"] is not None:
            RunSummary.model_validate(fixture["run"]["summary"])
            RunDetail.model_validate(fixture["run"]["detail"])
            RunLogResponse.model_validate(fixture["run"]["log"])

    def test_generated_output_is_sanitized(self) -> None:
        rendered = json.dumps(self.fixtures, sort_keys=True)
        forbidden = [
            str(Path.home()),
            str(web_demo_fixtures.REPO_ROOT),
            "/private/",
            "/var/folders/",
            "wud-static-demo",
            "wud-webui-demo",
            "compose-config-private",
        ]
        for marker in forbidden:
            self.assertNotIn(marker, rendered)
        self.assertIn("demo/out/images.todo", rendered)
        self.assertIn("demo/docker", rendered)

    def test_python_runtime_fixture_detail_is_stable(self) -> None:
        details: list[str] = []

        def collect_python_runtime_details(value: object) -> None:
            if isinstance(value, dict):
                if value.get("code") == "python-runtime":
                    details.append(str(value.get("detail")))
                for item in value.values():
                    collect_python_runtime_details(item)
            elif isinstance(value, list):
                for item in value:
                    collect_python_runtime_details(item)

        collect_python_runtime_details(self.fixtures)

        self.assertTrue(details)
        self.assertEqual(
            set(details),
            {web_demo_fixtures.DEMO_PYTHON_RUNTIME_DETAIL},
        )

    def test_typescript_fixture_render_is_sanitized(self) -> None:
        rendered = web_demo_fixtures.render_static_demo_fixtures_ts(self.fixtures)
        types_path = web_demo_fixtures.REPO_ROOT / "webui/src/api/demo/types.ts"
        self.assertIn("export const generatedFixtures", rendered)
        self.assertIn(
            'import type { DemoGeneratedFixtures } from "./types"',
            rendered,
        )
        self.assertIn(
            "export type DemoGeneratedFixtures",
            types_path.read_text(encoding="utf-8"),
        )
        self.assertNotIn(str(Path.home()), rendered)

    def test_typescript_fixture_render_omits_release_versions(self) -> None:
        payload = web_demo_fixtures._static_demo_fixture_render_payload(self.fixtures)

        self.assertIn("version", self.fixtures["status"])
        self.assertIn("wudup_version", self.fixtures["diagnostics"])
        self.assertNotIn("version", payload["status"])
        self.assertNotIn("wudup_version", payload["diagnostics"])

    def test_demo_environment_is_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = web_demo_fixtures.seed_demo_state(Path(tmpdir) / "state")
            static_dir = paths["root"] / "static"
            static_dir.mkdir(parents=True, exist_ok=True)

            with mock.patch.dict(
                os.environ,
                {
                    "GITHUB_TOKEN": "host-secret",
                    "PATH": "/private/host/bin",
                    "WUD_WEB_TOKEN": "host-web-token",
                },
            ):
                env = web_demo_fixtures._demo_environ(paths, static_dir)

        self.assertEqual(
            set(env),
            {
                "HOME",
                "DOCKER_BASE",
                "HOST_DOCKER_BASE",
                "WUD_OUT_FILE",
                "WUD_LOG_DIR",
                "WUD_DB_PATH",
                "WUD_WEB_STATIC_DIR",
                "WUD_WEB_DEV_NO_AUTH",
                "WUD_WEB_MUTATIONS_ENABLED",
                "WUD_WEB_RESTART_CONTAINER",
                "WUD_WEB_DEMO_SELF_UPDATE",
                "WUD_WEB_ALLOWED_HOSTS",
                "WUD_WEB_ALLOWED_ORIGINS",
                "WUD_WEB_UPSTREAM_MAP",
                "WUD_SCRIPTS_DIR",
                "WUD_SYNC_SCRIPTS",
                "WUDUP_USE_SUDO",
                "DOCKER_HOST",
                "PATH",
                "FAKE_DOCKER_ROOT",
            },
        )
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("WUD_WEB_TOKEN", env)
        self.assertNotIn("/private/host/bin", env["PATH"])
        self.assertEqual(env["WUD_WEB_DEV_NO_AUTH"], "true")
        self.assertEqual(env["WUD_SYNC_SCRIPTS"], "false")
        self.assertEqual(env["WUDUP_USE_SUDO"], "false")

    def test_fixture_generation_restores_wud_api_snapshot_cache(self) -> None:
        sentinel = web_wud_api.WudApiSnapshot(
            status=web_wud_api.WudApiStatus(
                state="unavailable",
                available=False,
                metadata_available=False,
                last_checked_at="2026-05-30T00:00:00+00:00",
                detail="sentinel",
            ),
            checked_monotonic=123.0,
        )
        diagnostics_sentinel = web_wud_api.WudApiConfigurationSnapshot(
            diagnostics=web_wud_api.WudApiConfigurationDiagnostics(
                health=web_wud_api.WudApiDiagnosticEndpointStatus(
                    state="unavailable",
                    available=False,
                    last_checked_at="2026-05-30T00:00:00+00:00",
                    detail="diagnostics sentinel",
                )
            ),
            checked_monotonic=456.0,
        )
        with web_wud_api._cache_lock:
            original_cache = dict(web_wud_api._snapshot_cache)
            original_diagnostics_cache = dict(
                web_wud_api._configuration_diagnostics_cache
            )
            web_wud_api._snapshot_cache.clear()
            web_wud_api._configuration_diagnostics_cache.clear()
            web_wud_api._snapshot_cache["https://sentinel.example"] = sentinel
            web_wud_api._configuration_diagnostics_cache[
                "https://sentinel.example"
            ] = diagnostics_sentinel
        try:
            with mock.patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("fixture generation must not use network"),
            ):
                web_demo_fixtures.generate_static_demo_fixtures()
            with web_wud_api._cache_lock:
                self.assertEqual(
                    web_wud_api._snapshot_cache,
                    {"https://sentinel.example": sentinel},
                )
                self.assertEqual(
                    web_wud_api._configuration_diagnostics_cache,
                    {"https://sentinel.example": diagnostics_sentinel},
                )
        finally:
            with web_wud_api._cache_lock:
                web_wud_api._snapshot_cache.clear()
                web_wud_api._snapshot_cache.update(original_cache)
                web_wud_api._configuration_diagnostics_cache.clear()
                web_wud_api._configuration_diagnostics_cache.update(
                    original_diagnostics_cache
                )

    def test_static_spa_available_default_is_fixture_controlled(self) -> None:
        entry = next(
            item
            for item in self.fixtures["settings"]["webui"]
            if item["name"] == "WUD_WEB_STATIC_SPA_AVAILABLE"
        )

        self.assertEqual(entry["value"], "true")
        self.assertEqual(entry["default_value"], "true")

    def test_fixture_writer_rejects_paths_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "generatedFixtures.ts"
            with self.assertRaisesRegex(ValueError, "inside the repository"):
                web_demo_fixtures.write_static_demo_fixtures(out_path)

    def test_checked_in_typescript_fixture_is_current(self) -> None:
        expected = web_demo_fixtures.render_static_demo_fixtures_ts(self.fixtures)
        actual = web_demo_fixtures.GENERATED_FIXTURE_PATH.read_text(encoding="utf-8")
        self.assertEqual(actual, expected)

    def test_release_notes_are_generated_from_backend_cache(self) -> None:
        release_notes = ReleaseNotesResponse.model_validate(
            self.fixtures["releaseNotes"]
        )
        ready_titles = {
            item.line_no: item.title
            for item in release_notes.items
            if item.status == "ready"
        }
        self.assertEqual(
            ready_titles[2],
            "Home Assistant Core 2026.5.3",
        )
        self.assertEqual(ready_titles[3], "Radarr v5.22.4")
        self.assertEqual(ready_titles[5], "WUDup v0.16.1")

    def test_plan_and_removal_catalogs_cover_pending_line_subsets(self) -> None:
        line_numbers = sorted(
            item["line_no"] for item in self.fixtures["pending"]["items"]
        )
        expected_subsets = {
            tuple(subset)
            for size in range(1, len(line_numbers) + 1)
            for subset in itertools.combinations(line_numbers, size)
        }

        plan_requests = {
            (
                tuple(case["request"]["line_numbers"]),
                bool(case["request"]["allow_tag_updates"]),
            )
            for case in self.fixtures["planCases"]
        }
        for subset in expected_subsets:
            self.assertIn((subset, False), plan_requests)
            self.assertIn((subset, True), plan_requests)

        removal_requests = {
            tuple(case["request"]["line_numbers"])
            for case in self.fixtures["removalCases"]
        }
        self.assertEqual(removal_requests, expected_subsets)

    def test_retag_catalog_covers_choice_combinations(self) -> None:
        targets = [
            (item["service_key"], item["target_id"])
            for item in self.fixtures["retagTargets"]["items"]
        ]
        expected = {
            tuple(
                (service_key, target_id, choice)
                for (service_key, target_id), choice in zip(
                    targets,
                    choices,
                    strict=True,
                )
            )
            for choices in itertools.product(
                ("keep-current", "switch-to-concrete"),
                repeat=len(targets),
            )
        }
        actual = {
            tuple(
                (
                    choice["service_key"],
                    choice.get("target_id"),
                    choice["choice"],
                )
                for choice in case["request"]["choices"]
            )
            for case in self.fixtures["retagCases"]
        }
        self.assertEqual(actual, expected)
        for case in self.fixtures["retagCases"]:
            if case["response"]["can_apply"]:
                self.assertIn("jobTemplate", case)

    def test_retag_choice_signature_ignores_request_order(self) -> None:
        choices = [
            web_demo_fixtures.RetagChoiceRequest(
                service_key="media/wudup",
                choice="switch-to-concrete",
            ),
            web_demo_fixtures.RetagChoiceRequest(
                service_key="home/home-assistant",
                choice="switch-to-concrete",
                target_tag="2026.5.3",
            ),
        ]

        self.assertEqual(
            web_demo_fixtures._retag_choices_signature(choices),
            web_demo_fixtures._retag_choices_signature(list(reversed(choices))),
        )
        self.assertNotEqual(
            web_demo_fixtures._retag_choices_signature(
                [
                    web_demo_fixtures.RetagChoiceRequest(
                        service_key="media/app",
                        target_id="target-a",
                        choice="switch-to-concrete",
                    )
                ]
            ),
            web_demo_fixtures._retag_choices_signature(
                [
                    web_demo_fixtures.RetagChoiceRequest(
                        service_key="media/app",
                        target_id="target-b",
                        choice="switch-to-concrete",
                    )
                ]
            ),
        )

    def test_demo_retag_digest_verifier_uses_instance_map(self) -> None:
        web_demo_fixtures._ensure_web_fixture_imports()
        original_digest_map = web_demo_fixtures.DEMO_RETAG_DIGESTS_BY_IMAGE
        try:
            web_demo_fixtures.DEMO_RETAG_DIGESTS_BY_IMAGE = {
                "repo/app:1.0": "sha256:" + "1" * 64,
            }
            with web_demo_fixtures._demo_retag_digest_resolution():
                verifier = web_demo_fixtures.web_retags.DigestVerifier()
                web_demo_fixtures.DEMO_RETAG_DIGESTS_BY_IMAGE = {}

                result = verifier.resolve_tag_digest("repo/app:1.0")

            self.assertTrue(result.ok)
            self.assertEqual(result.digest, "sha256:" + "1" * 64)
        finally:
            web_demo_fixtures.DEMO_RETAG_DIGESTS_BY_IMAGE = original_digest_map

    def test_applyable_retag_fixtures_have_readable_logs(self) -> None:
        for case in self.fixtures["retagCases"]:
            if not case["response"]["can_apply"]:
                continue
            fixture = case["jobTemplate"]
            self.assertTrue(fixture["log"]["exists"])
            self.assertIn("Retag changes applied.", fixture["log"]["content"])
            self.assertIsNotNone(fixture["run"])
            self.assertTrue(fixture["run"]["log"]["exists"])
            self.assertIn("Retag changes applied.", fixture["run"]["log"]["content"])


if __name__ == "__main__":
    unittest.main()

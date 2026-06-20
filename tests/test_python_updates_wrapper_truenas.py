from __future__ import annotations

import json
import sys


from tests.updates_wrapper_helpers import UpdatesWrapperTestCase

class UpdatesWrapperTruenasTests(UpdatesWrapperTestCase):
    def test_truenas_checks_skip_when_not_enabled(self) -> None:
        result = self.run_updates("--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("TrueNAS System Update", result.stdout)
        self.assertNotIn("TrueNAS Alerts", result.stdout)
    def test_truenas_check_runs_helper_container_and_prints_status(self) -> None:
        docker_log = self.root / "docker.log"

        result = self.run_updates(
            "--dry-run",
            env_overrides={
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "wudup-1",
                "FAKE_DOCKER_LOG": str(docker_log),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("⚠️  System update available!", result.stdout)
        self.assertIn("25.10.1", result.stdout)
        self.assertIn("Pool needs attention", result.stdout)
        docker_calls = docker_log.read_text(encoding="utf-8")
        self.assertIn("container inspect wudup-1", docker_calls)
        self.assertIn(
            "run --rm --pull never --network none --read-only --cap-drop ALL "
            "--security-opt no-new-privileges",
            docker_calls,
        )
        self.assertNotIn("-v wud-out:", docker_calls)
        self.assertNotIn("WUD_OUT_FILE=", docker_calls)
        self.assertIn(
            "--mount type=bind,src=/var/run/middleware,"
            "dst=/var/run/middleware,readonly",
            docker_calls,
        )
        self.assertNotIn("-v /var/run/middleware:/var/run/middleware:ro", docker_calls)
        self.assertIn("wudup:test truenas-status-export", docker_calls)
        self.assertNotIn("--volumes-from", docker_calls)
        self.assertNotIn("--uri", docker_calls)
        self.assertNotIn("-K", docker_calls)
    def test_truenas_helper_failure_reports_unreachable_without_failing(self) -> None:
        result = self.run_updates(
            "--dry-run",
            env_overrides={
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "wudup-1",
                "FAKE_DOCKER_RUN_RETURN": "2",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "TrueNAS not reachable; skipping system update check.",
            result.stdout,
        )
        self.assertIn("docker run exited 2", result.stdout)
        self.assertIn("TrueNAS not reachable; skipping alert check.", result.stdout)
    def test_truenas_inspect_failure_reports_unreachable_without_failing(self) -> None:
        result = self.run_updates(
            "--dry-run",
            env_overrides={
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "wudup-1",
                "FAKE_DOCKER_INSPECT_RETURN": "2",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "TrueNAS not reachable; skipping system update check.",
            result.stdout,
        )
        self.assertIn("docker inspect exited 2", result.stdout)
        self.assertIn("TrueNAS not reachable; skipping alert check.", result.stdout)
    def test_truenas_malformed_helper_status_reports_unreachable(self) -> None:
        result = self.run_updates(
            "--dry-run",
            env_overrides={
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "wudup-1",
                "FAKE_DOCKER_STATUS_RESPONSE": "invalid",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "TrueNAS not reachable; skipping system update check.",
            result.stdout,
        )
        self.assertIn("invalid JSON response", result.stdout)
    def test_truenas_status_export_uses_local_midclt_without_api_flags(self) -> None:
        key_file = self.root / "truenas-api-key"
        key_file.write_text("super-secret-api-key\n", encoding="utf-8")
        midclt_log = self.root / "midclt.log"

        result = self.run_updates(
            command=[sys.executable, "-m", "wudup.cli", "truenas-status-export"],
            include_file=False,
            env_overrides={
                "WUD_OUT_FILE": str(self.wud_file),
                "FAKE_MIDCLT_LOG": str(midclt_log),
                "TRUENAS_API_URI": "wss://truenas.example.local/api/current",
                "TRUENAS_API_KEY_FILE": str(key_file),
                "TRUENAS_API_USERNAME": "admin",
                "TRUENAS_API_INSECURE": "1",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        midclt_calls = midclt_log.read_text(encoding="utf-8")
        self.assertIn("call update.status", midclt_calls)
        self.assertIn("call alert.list", midclt_calls)
        self.assertNotIn("--uri", midclt_calls)
        self.assertNotIn("-K", midclt_calls)
        self.assertNotIn(str(key_file), midclt_calls)
        self.assertNotIn("super-secret-api-key", result.stdout)
        self.assertNotIn("super-secret-api-key", result.stderr)
        self.assertNotIn("super-secret-api-key", midclt_calls)
        self.assertFalse((self.root / "truenas-status.json").exists())
        status_payload = json.loads(result.stdout)
        self.assertTrue(status_payload["update"]["ok"])
        self.assertTrue(status_payload["alerts"]["ok"])
        self.assertEqual(
            status_payload["update"]["data"],
            {"status": "AVAILABLE", "version": "25.10.1"},
        )
        self.assertEqual(status_payload["alerts"]["data"], ["Pool needs attention"])
        self.assertNotIn("private-update-detail", result.stdout)
        self.assertNotIn("private-alert-arg", result.stdout)
    def test_truenas_update_status_up_to_date(self) -> None:
        result = self.run_updates(
            "--dry-run",
            env_overrides={
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "wudup-1",
                "FAKE_TRUENAS_UPDATE_STATUS": "unavailable",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("✅ System up to date", result.stdout)
    def test_truenas_update_status_error_is_reported_without_failing(self) -> None:
        result = self.run_updates(
            "--dry-run",
            env_overrides={
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "wudup-1",
                "FAKE_TRUENAS_UPDATE_STATUS": "error",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("TrueNAS update status error: update train failed", result.stdout)
    def test_truenas_alert_status_no_active_alerts(self) -> None:
        result = self.run_updates(
            "--dry-run",
            env_overrides={
                "TRUENAS_STATUS_CHECK": "true",
                "HOSTNAME": "wudup-1",
                "FAKE_TRUENAS_ALERT_STATUS": "none",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("✅ No active alerts", result.stdout)
    def test_truenas_status_export_records_midclt_failure(self) -> None:
        result = self.run_updates(
            command=[sys.executable, "-m", "wudup.cli", "truenas-status-export"],
            include_file=False,
            env_overrides={
                "WUD_OUT_FILE": str(self.wud_file),
                "FAKE_MIDCLT_RETURN": "2",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse((self.root / "truenas-status.json").exists())
        status_payload = json.loads(result.stdout)
        self.assertFalse(status_payload["update"]["ok"])
        self.assertEqual(status_payload["update"]["reason"], "midclt exited 2")

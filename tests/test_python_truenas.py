from __future__ import annotations

import json
import subprocess
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

from wudup.truenas import (
    DEFAULT_TRUENAS_STATUS_TIMEOUT,
    TrueNasCallResult,
    _first_inspected_container,
    _has_command,
    _inspected_container_image,
    _midclt_json,
    _refresh_truenas_status,
    _run_truenas_status_helper,
    _subprocess_failure_reason,
    _truenas_active_alerts,
    _truenas_alerts_result_to_payload,
    _truenas_helper_timeout_seconds,
    _truenas_result_from_payload,
    _truenas_snapshot_from_payload,
    _truenas_status_payload,
    _truenas_status_payload_json,
    _truenas_status_result_from_stdout,
    _truenas_unavailable_snapshot,
    _truenas_unreachable_message,
    _truenas_update_error_reason,
    _truenas_update_result_to_payload,
    _truenas_update_status,
    _truenas_update_summary,
    _truenas_update_version,
    run_truenas_status_export_from_namespace,
)


class TrueNasCommandLookupTests(unittest.TestCase):
    def test_has_command_uses_supplied_path(self) -> None:
        with mock.patch("shutil.which", return_value="/custom/bin/docker") as which:
            self.assertTrue(_has_command("docker", {"PATH": "/custom/bin"}))

        which.assert_called_once_with("docker", path="/custom/bin")

    def test_has_command_returns_false_when_missing(self) -> None:
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(_has_command("midclt", {"PATH": "/usr/bin"}))


class TrueNasSubprocessReasonTests(unittest.TestCase):
    def _result(
        self,
        returncode: int,
        *,
        stderr: str = "",
        stdout: str = "",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["cmd"],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def test_includes_exit_code_without_detail(self) -> None:
        self.assertEqual(
            _subprocess_failure_reason("docker inspect", self._result(1)),
            "docker inspect exited 1",
        )

    def test_prefers_first_stderr_line(self) -> None:
        reason = _subprocess_failure_reason(
            "docker inspect",
            self._result(2, stderr="no such container\nextra", stdout="ignored"),
        )

        self.assertEqual(reason, "docker inspect exited 2: no such container")

    def test_uses_stdout_when_stderr_is_empty(self) -> None:
        reason = _subprocess_failure_reason(
            "docker run",
            self._result(3, stdout="helper failed\nextra"),
        )

        self.assertEqual(reason, "docker run exited 3: helper failed")

    def test_truncates_detail(self) -> None:
        reason = _subprocess_failure_reason(
            "docker run",
            self._result(1, stderr="x" * 300),
        )

        self.assertEqual(len(reason.split(": ", 1)[1]), 200)


class TrueNasDockerInspectPayloadTests(unittest.TestCase):
    def test_first_inspected_container_requires_non_empty_list_of_dicts(self) -> None:
        container = {"Id": "abc123", "Image": "repo/app:latest"}

        self.assertEqual(_first_inspected_container([container]), container)
        self.assertIsNone(_first_inspected_container([]))
        self.assertIsNone(_first_inspected_container({}))
        self.assertIsNone(_first_inspected_container(["not-a-dict"]))

    def test_inspected_container_image_prefers_top_level_image(self) -> None:
        self.assertEqual(
            _inspected_container_image(
                {"Image": "sha256:abc", "Config": {"Image": "repo/app:latest"}}
            ),
            "sha256:abc",
        )

    def test_inspected_container_image_falls_back_to_config_image(self) -> None:
        self.assertEqual(
            _inspected_container_image({"Config": {"Image": "repo/app:latest"}}),
            "repo/app:latest",
        )

    def test_inspected_container_image_returns_empty_when_missing(self) -> None:
        self.assertEqual(_inspected_container_image({}), "")
        self.assertEqual(_inspected_container_image({"Image": 42}), "")
        self.assertEqual(_inspected_container_image({"Config": "invalid"}), "")


class TrueNasPayloadParsingTests(unittest.TestCase):
    def test_status_result_from_stdout_parses_dict(self) -> None:
        payload = {"update": {"ok": True}, "alerts": {"ok": True}}

        result = _truenas_status_result_from_stdout(f"\n{json.dumps(payload)}\n")

        self.assertTrue(result.ok)
        self.assertEqual(result.data, payload)

    def test_status_result_from_stdout_rejects_empty_or_invalid_payload(self) -> None:
        self.assertEqual(
            _truenas_status_result_from_stdout("").reason,
            "empty helper response",
        )
        self.assertEqual(
            _truenas_status_result_from_stdout("not json").reason,
            "invalid JSON response",
        )
        self.assertEqual(
            _truenas_status_result_from_stdout("[1, 2]").reason,
            "invalid status response",
        )

    def test_snapshot_from_payload_preserves_update_and_alert_results(self) -> None:
        payload = {
            "update": {"ok": True, "data": {"status": "AVAILABLE"}, "reason": ""},
            "alerts": {"ok": False, "reason": "midclt timed out"},
        }

        snapshot = _truenas_snapshot_from_payload(payload)

        self.assertTrue(snapshot.update.ok)
        self.assertEqual(snapshot.update.data, {"status": "AVAILABLE"})
        self.assertFalse(snapshot.alerts.ok)
        self.assertEqual(snapshot.alerts.reason, "midclt timed out")

    def test_snapshot_from_payload_rejects_non_dict(self) -> None:
        snapshot = _truenas_snapshot_from_payload(["invalid"])

        self.assertFalse(snapshot.update.ok)
        self.assertFalse(snapshot.alerts.ok)
        self.assertEqual(snapshot.update.reason, "invalid status response")

    def test_result_from_payload_requires_boolean_ok(self) -> None:
        self.assertTrue(_truenas_result_from_payload({"ok": True, "data": []}).ok)
        self.assertEqual(
            _truenas_result_from_payload({"ok": False, "reason": ""}).reason,
            "unknown error",
        )
        self.assertEqual(
            _truenas_result_from_payload({"ok": None}).reason,
            "invalid status response",
        )
        self.assertEqual(
            _truenas_result_from_payload(None).reason,
            "invalid status response",
        )

    def test_status_payload_json_is_compact_and_sanitized(self) -> None:
        snapshot = _truenas_unavailable_snapshot("docker not available")

        output = _truenas_status_payload_json(snapshot)
        payload = json.loads(output)

        self.assertNotIn(": ", output)
        self.assertFalse(payload["update"]["ok"])
        self.assertEqual(payload["alerts"]["reason"], "docker not available")

    def test_status_payload_summarizes_successful_results(self) -> None:
        payload = _truenas_status_payload(
            _truenas_snapshot_from_payload(
                {
                    "update": {
                        "ok": True,
                        "data": {"status": "AVAILABLE", "version": "25.10.1"},
                    },
                    "alerts": {
                        "ok": True,
                        "data": [{"dismissed": False, "formatted": "Pool degraded"}],
                    },
                }
            )
        )

        self.assertEqual(
            payload["update"]["data"],  # type: ignore[index]
            {"status": "AVAILABLE", "version": "25.10.1"},
        )
        self.assertEqual(payload["alerts"]["data"], ["Pool degraded"])  # type: ignore[index]


class TrueNasUpdateSummaryTests(unittest.TestCase):
    def test_update_status_supports_legacy_and_new_payloads(self) -> None:
        self.assertEqual(_truenas_update_status({"status": "AVAILABLE"}), "AVAILABLE")
        self.assertEqual(
            _truenas_update_status(
                {"code": "NORMAL", "status": {"new_version": {"version": "25.10.1"}}}
            ),
            "AVAILABLE",
        )
        self.assertEqual(
            _truenas_update_status({"code": "NORMAL", "status": {"new_version": None}}),
            "UNAVAILABLE",
        )
        self.assertEqual(_truenas_update_status({"code": "ERROR"}), "ERROR")
        self.assertEqual(_truenas_update_status(None), "")

    def test_update_version_supports_legacy_and_new_payloads(self) -> None:
        self.assertEqual(_truenas_update_version({"version": "24.10.2"}), "24.10.2")
        self.assertEqual(
            _truenas_update_version(
                {"status": {"new_version": {"version": "25.10.1"}}}
            ),
            "25.10.1",
        )
        self.assertEqual(_truenas_update_version({"version": 25}), "")
        self.assertEqual(_truenas_update_version({"status": "AVAILABLE"}), "")

    def test_update_error_reason_supports_top_level_and_nested_error(self) -> None:
        self.assertEqual(_truenas_update_error_reason({"reason": "failed"}), "failed")
        self.assertEqual(
            _truenas_update_error_reason({"error": {"reason": "train failed"}}),
            "train failed",
        )
        self.assertEqual(_truenas_update_error_reason({"error": "failed"}), "")
        self.assertEqual(_truenas_update_error_reason({"error": {"reason": 42}}), "")

    def test_update_summary_omits_empty_and_private_fields(self) -> None:
        summary = _truenas_update_summary(
            {
                "code": "NORMAL",
                "status": {"new_version": {"version": "25.10.1"}},
                "private": "do not leak",
            }
        )

        self.assertEqual(summary, {"status": "AVAILABLE", "version": "25.10.1"})

    def test_update_result_payload_uses_summary_only(self) -> None:
        payload = _truenas_update_result_to_payload(
            TrueNasCallResult(
                ok=True,
                data={"status": "AVAILABLE", "private": "do not leak"},
            )
        )

        self.assertEqual(payload["data"], {"status": "AVAILABLE"})

    def test_unreachable_message_includes_optional_reason(self) -> None:
        self.assertIn(
            "TrueNAS not reachable; skipping system update check.",
            _truenas_unreachable_message("system update check"),
        )
        self.assertIn(
            "(midclt not available)",
            _truenas_unreachable_message("alert check", "midclt not available"),
        )


class TrueNasAlertPayloadTests(unittest.TestCase):
    def test_active_alerts_filters_dismissed_and_private_fields(self) -> None:
        alerts = _truenas_active_alerts(
            [
                "String alert",
                {"dismissed": True, "formatted": "Dismissed alert"},
                {
                    "dismissed": False,
                    "formatted": "Pool degraded",
                    "mail": {"to": "private@example.test"},
                },
                {"dismissed": False, "formatted": ""},
                42,
            ]
        )

        self.assertEqual(alerts, ["String alert", "Pool degraded"])

    def test_active_alerts_returns_none_for_non_list(self) -> None:
        self.assertIsNone(_truenas_active_alerts(None))
        self.assertIsNone(_truenas_active_alerts({}))

    def test_alert_result_payload_uses_active_alerts_only(self) -> None:
        payload = _truenas_alerts_result_to_payload(
            TrueNasCallResult(
                ok=True,
                data=[
                    {"dismissed": False, "formatted": "Pool degraded"},
                    {"dismissed": True, "formatted": "Dismissed"},
                ],
            )
        )

        self.assertEqual(payload["data"], ["Pool degraded"])


class TrueNasMidcltJsonTests(unittest.TestCase):
    def _completed(
        self,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["midclt"],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def test_returns_failure_when_midclt_is_missing(self) -> None:
        with mock.patch("wudup.truenas._has_command", return_value=False):
            result = _midclt_json("update.status", "5", {"PATH": ""})

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "midclt not available")

    def test_returns_failure_on_invalid_timeout(self) -> None:
        with mock.patch("wudup.truenas._has_command", return_value=True):
            result = _midclt_json("update.status", "invalid", {"PATH": "/usr/bin"})

        self.assertFalse(result.ok)
        self.assertEqual(
            result.reason,
            "TRUENAS_STATUS_TIMEOUT must be an integer number of seconds",
        )

    def test_parses_update_status_dict_and_alert_list(self) -> None:
        calls = [
            self._completed(stdout='{"code":"NORMAL","status":{"new_version":null}}\n'),
            self._completed(stdout='[{"dismissed":false,"formatted":"Pool degraded"}]\n'),
        ]

        with (
            mock.patch("wudup.truenas._has_command", return_value=True),
            mock.patch("subprocess.run", side_effect=calls),
        ):
            update = _midclt_json("update.status", "5", {"PATH": "/usr/bin"})
            alerts = _midclt_json("alert.list", "5", {"PATH": "/usr/bin"})

        self.assertTrue(update.ok)
        self.assertEqual(update.data, {"code": "NORMAL", "status": {"new_version": None}})
        self.assertTrue(alerts.ok)
        self.assertEqual(alerts.data, [{"dismissed": False, "formatted": "Pool degraded"}])

    def test_rejects_schema_mismatched_payloads(self) -> None:
        calls = [
            self._completed(stdout='["not a status dict"]\n'),
            self._completed(stdout='{"not":"an alert list"}\n'),
        ]

        with (
            mock.patch("wudup.truenas._has_command", return_value=True),
            mock.patch("subprocess.run", side_effect=calls),
        ):
            update = _midclt_json("update.status", "5", {"PATH": "/usr/bin"})
            alerts = _midclt_json("alert.list", "5", {"PATH": "/usr/bin"})

        self.assertFalse(update.ok)
        self.assertEqual(
            update.reason,
            "unexpected midclt payload for update.status: list",
        )
        self.assertFalse(alerts.ok)
        self.assertEqual(
            alerts.reason,
            "unexpected midclt payload for alert.list: dict",
        )

    def test_handles_midclt_subprocess_failures(self) -> None:
        with (
            mock.patch("wudup.truenas._has_command", return_value=True),
            mock.patch(
                "subprocess.run",
                return_value=self._completed(returncode=2, stderr="failed"),
            ),
        ):
            result = _midclt_json("update.status", "5", {"PATH": "/usr/bin"})

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "midclt exited 2")

    def test_handles_empty_and_invalid_json_stdout(self) -> None:
        calls = [
            self._completed(stdout=""),
            self._completed(stdout="not json"),
        ]

        with (
            mock.patch("wudup.truenas._has_command", return_value=True),
            mock.patch("subprocess.run", side_effect=calls),
        ):
            empty = _midclt_json("update.status", "5", {"PATH": "/usr/bin"})
            invalid = _midclt_json("update.status", "5", {"PATH": "/usr/bin"})

        self.assertEqual(empty.reason, "empty midclt response")
        self.assertEqual(invalid.reason, "invalid JSON response")

    def test_handles_timeout_and_os_error(self) -> None:
        with (
            mock.patch("wudup.truenas._has_command", return_value=True),
            mock.patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["midclt"], timeout=5),
            ),
        ):
            timed_out = _midclt_json("update.status", "5", {"PATH": "/usr/bin"})

        with (
            mock.patch("wudup.truenas._has_command", return_value=True),
            mock.patch("subprocess.run", side_effect=OSError("permission denied")),
        ):
            failed = _midclt_json("update.status", "5", {"PATH": "/usr/bin"})

        self.assertEqual(timed_out.reason, "midclt timed out")
        self.assertIn("midclt failed:", failed.reason)


class TrueNasStatusExportTests(unittest.TestCase):
    def test_status_export_prints_update_and_alert_payloads(self) -> None:
        calls = [
            TrueNasCallResult(ok=True, data={"status": "UNAVAILABLE"}),
            TrueNasCallResult(ok=True, data=[]),
        ]
        stdout = StringIO()

        with (
            mock.patch("wudup.truenas._midclt_json", side_effect=calls),
            redirect_stdout(stdout),
        ):
            status = run_truenas_status_export_from_namespace(
                Namespace(),
                environ={"TRUENAS_STATUS_TIMEOUT": "42"},
            )

        self.assertEqual(status, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["update"]["data"], {"status": "UNAVAILABLE"})
        self.assertEqual(payload["alerts"]["data"], [])

    def test_status_export_passes_timeout_to_both_midclt_calls(self) -> None:
        with (
            mock.patch(
                "wudup.truenas._midclt_json",
                return_value=TrueNasCallResult(ok=False, reason="test"),
            ) as midclt_json,
            redirect_stdout(StringIO()),
        ):
            run_truenas_status_export_from_namespace(
                Namespace(),
                environ={"TRUENAS_STATUS_TIMEOUT": "42"},
            )

        self.assertEqual(
            [call.args[:2] for call in midclt_json.call_args_list],
            [("update.status", "42"), ("alert.list", "42")],
        )

    def test_status_export_uses_default_timeout(self) -> None:
        with (
            mock.patch(
                "wudup.truenas._midclt_json",
                return_value=TrueNasCallResult(ok=False, reason="test"),
            ) as midclt_json,
            redirect_stdout(StringIO()),
        ):
            run_truenas_status_export_from_namespace(Namespace(), environ={})

        self.assertEqual(midclt_json.call_args.args[1], DEFAULT_TRUENAS_STATUS_TIMEOUT)


class TrueNasStatusHelperTests(unittest.TestCase):
    def _options(self, timeout: str = "5") -> Namespace:
        return Namespace(truenas_status_timeout=timeout)

    def _completed(
        self,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["docker"],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def test_helper_timeout_scales_with_midclt_timeout(self) -> None:
        self.assertEqual(_truenas_helper_timeout_seconds("0"), 5)
        self.assertEqual(_truenas_helper_timeout_seconds("5"), 15)
        self.assertEqual(_truenas_helper_timeout_seconds("30"), 65)

    def test_run_helper_requires_docker_and_hostname(self) -> None:
        self.assertEqual(
            _run_truenas_status_helper(self._options(), {"PATH": ""}).reason,
            "docker not available",
        )

        with (
            mock.patch("wudup.truenas._has_command", return_value=True),
            mock.patch(
                "wudup.truenas.container_identity_candidates",
                return_value=[],
            ),
        ):
            result = _run_truenas_status_helper(self._options(), {"PATH": ""})

        self.assertEqual(result.reason, "HOSTNAME not available")

    def test_run_helper_reports_docker_inspect_failures(self) -> None:
        cases = [
            (
                subprocess.TimeoutExpired(cmd=["docker"], timeout=5),
                "docker inspect timed out",
            ),
            (
                self._completed(returncode=1, stderr="container not found"),
                "docker inspect exited 1: container not found",
            ),
            (self._completed(stdout="not json"), "docker inspect returned invalid JSON"),
            (self._completed(stdout="[]"), "docker inspect returned no container"),
            (self._completed(stdout='[{"Config":{}}]'), "docker inspect returned no image"),
        ]

        for run_result, reason in cases:
            with self.subTest(reason=reason):
                with (
                    mock.patch("wudup.truenas._has_command", return_value=True),
                    mock.patch("subprocess.run", side_effect=[run_result]),
                ):
                    result = _run_truenas_status_helper(
                        self._options(),
                        {"PATH": "/usr/bin", "HOSTNAME": "wudup-1"},
                    )

                self.assertFalse(result.ok)
                self.assertEqual(result.reason, reason)

    def test_run_helper_reports_docker_run_failures(self) -> None:
        inspect_result = self._completed(stdout='[{"Image":"wudup:test"}]')

        with (
            mock.patch("wudup.truenas._has_command", return_value=True),
            mock.patch(
                "subprocess.run",
                side_effect=[
                    inspect_result,
                    self._completed(returncode=2, stderr="helper failed"),
                ],
            ),
        ):
            result = _run_truenas_status_helper(
                self._options(),
                {"PATH": "/usr/bin", "HOSTNAME": "wudup-1"},
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "docker run exited 2: helper failed")

    def test_run_helper_tries_next_container_identity_after_missing_name(self) -> None:
        inspect_failure = self._completed(returncode=1, stderr="container not found")
        inspect_success = self._completed(stdout='[{"Image":"wudup:test"}]')
        helper_payload = {
            "update": {"ok": True, "data": {"status": "AVAILABLE"}, "reason": ""},
            "alerts": {"ok": True, "data": [], "reason": ""},
        }
        run_mock = mock.Mock(
            side_effect=[
                inspect_failure,
                inspect_success,
                self._completed(stdout=json.dumps(helper_payload)),
            ]
        )

        with (
            mock.patch("wudup.truenas._has_command", return_value=True),
            mock.patch(
                "wudup.truenas.container_identity_candidates",
                return_value=["custom-hostname", "actual-container-id"],
            ),
            mock.patch("subprocess.run", run_mock),
        ):
            result = _run_truenas_status_helper(
                self._options(),
                {"PATH": "/usr/bin", "HOSTNAME": "custom-hostname"},
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.data, helper_payload)
        self.assertEqual(
            run_mock.call_args_list[1].args[0],
            ["docker", "container", "inspect", "actual-container-id"],
        )

    def test_run_helper_parses_successful_helper_stdout(self) -> None:
        inspect_result = self._completed(stdout='[{"Config":{"Image":"wudup:test"}}]')
        helper_payload = {
            "update": {"ok": True, "data": {"status": "AVAILABLE"}, "reason": ""},
            "alerts": {"ok": True, "data": [], "reason": ""},
        }
        run_mock = mock.Mock(
            side_effect=[
                inspect_result,
                self._completed(stdout=json.dumps(helper_payload)),
            ]
        )

        with (
            mock.patch("wudup.truenas._has_command", return_value=True),
            mock.patch("subprocess.run", run_mock),
        ):
            result = _run_truenas_status_helper(
                self._options("7"),
                {"PATH": "/usr/bin", "HOSTNAME": "wudup-1"},
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.data, helper_payload)
        docker_run_command = run_mock.call_args_list[1].args[0]
        self.assertIn("--pull", docker_run_command)
        self.assertIn("never", docker_run_command)
        self.assertIn("TRUENAS_STATUS_TIMEOUT=7", docker_run_command)
        self.assertIn("truenas-status-export", docker_run_command)

    def test_refresh_status_returns_unavailable_snapshot_on_helper_failure(self) -> None:
        with mock.patch(
            "wudup.truenas._run_truenas_status_helper",
            return_value=TrueNasCallResult(ok=False, reason="docker not available"),
        ):
            snapshot = _refresh_truenas_status(self._options(), {"PATH": ""})

        self.assertFalse(snapshot.update.ok)
        self.assertFalse(snapshot.alerts.ok)
        self.assertEqual(snapshot.update.reason, "docker not available")

    def test_refresh_status_parses_helper_payload(self) -> None:
        payload = {
            "update": {"ok": True, "data": {"status": "AVAILABLE"}, "reason": ""},
            "alerts": {"ok": True, "data": [], "reason": ""},
        }

        with mock.patch(
            "wudup.truenas._run_truenas_status_helper",
            return_value=TrueNasCallResult(ok=True, data=payload),
        ):
            snapshot = _refresh_truenas_status(self._options(), {"PATH": ""})

        self.assertTrue(snapshot.update.ok)
        self.assertTrue(snapshot.alerts.ok)
        self.assertEqual(snapshot.update.data, {"status": "AVAILABLE"})


if __name__ == "__main__":
    unittest.main()

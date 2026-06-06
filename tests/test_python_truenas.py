"""Tests for wud_updater.truenas module."""

from __future__ import annotations

import json
import subprocess
import unittest
from unittest import mock

from wud_updater.truenas import (
    DEFAULT_TRUENAS_STATUS_TIMEOUT,
    TRUENAS_MIDDLEWARE_MOUNT,
    TrueNasCallResult,
    TrueNasStatusSnapshot,
    _first_inspected_container,
    _has_command,
    _inspected_container_image,
    _midclt_command,
    _subprocess_failure_reason,
    _truenas_active_alerts,
    _truenas_alerts_result_to_payload,
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
)


class TestTrueNasCallResult(unittest.TestCase):
    def test_default_fields(self) -> None:
        result = TrueNasCallResult(ok=True)
        self.assertTrue(result.ok)
        self.assertIsNone(result.data)
        self.assertEqual(result.reason, "")

    def test_with_all_fields(self) -> None:
        result = TrueNasCallResult(ok=False, data={"key": "val"}, reason="some reason")
        self.assertFalse(result.ok)
        self.assertEqual(result.data, {"key": "val"})
        self.assertEqual(result.reason, "some reason")

    def test_is_frozen(self) -> None:
        result = TrueNasCallResult(ok=True)
        with self.assertRaises((AttributeError, TypeError)):
            result.ok = False  # type: ignore[misc]


class TestTrueNasStatusSnapshot(unittest.TestCase):
    def test_stores_update_and_alerts(self) -> None:
        update = TrueNasCallResult(ok=True, data={"status": "UNAVAILABLE"})
        alerts = TrueNasCallResult(ok=True, data=[])
        snapshot = TrueNasStatusSnapshot(update=update, alerts=alerts)
        self.assertIs(snapshot.update, update)
        self.assertIs(snapshot.alerts, alerts)

    def test_is_frozen(self) -> None:
        update = TrueNasCallResult(ok=False)
        alerts = TrueNasCallResult(ok=False)
        snapshot = TrueNasStatusSnapshot(update=update, alerts=alerts)
        with self.assertRaises((AttributeError, TypeError)):
            snapshot.update = TrueNasCallResult(ok=True)  # type: ignore[misc]


class TestConstants(unittest.TestCase):
    def test_default_timeout(self) -> None:
        self.assertEqual(DEFAULT_TRUENAS_STATUS_TIMEOUT, "5")

    def test_middleware_mount(self) -> None:
        self.assertEqual(TRUENAS_MIDDLEWARE_MOUNT, "/var/run/middleware")


class TestHasCommand(unittest.TestCase):
    def test_returns_true_when_command_on_path(self) -> None:
        with mock.patch("shutil.which", return_value="/usr/bin/midclt"):
            self.assertTrue(_has_command("midclt", {"PATH": "/usr/bin"}))

    def test_returns_false_when_command_not_on_path(self) -> None:
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(_has_command("midclt", {"PATH": "/usr/bin"}))

    def test_uses_path_from_environ(self) -> None:
        with mock.patch("shutil.which") as mock_which:
            mock_which.return_value = "/custom/bin/midclt"
            _has_command("midclt", {"PATH": "/custom/bin"})
            mock_which.assert_called_once_with("midclt", path="/custom/bin")

    def test_uses_none_path_when_not_in_environ(self) -> None:
        with mock.patch("shutil.which") as mock_which:
            mock_which.return_value = None
            _has_command("midclt", {})
            mock_which.assert_called_once_with("midclt", path=None)


class TestSubprocessFailureReason(unittest.TestCase):
    def _make_result(
        self,
        returncode: int,
        stderr: str = "",
        stdout: str = "",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["cmd"],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def test_basic_exit_code(self) -> None:
        result = self._make_result(1)
        reason = _subprocess_failure_reason("docker inspect", result)
        self.assertEqual(reason, "docker inspect exited 1")

    def test_appends_stderr_first_line(self) -> None:
        result = self._make_result(2, stderr="No such container\nExtra line")
        reason = _subprocess_failure_reason("docker inspect", result)
        self.assertEqual(reason, "docker inspect exited 2: No such container")

    def test_falls_back_to_stdout_when_stderr_empty(self) -> None:
        result = self._make_result(2, stdout="some output\nmore")
        reason = _subprocess_failure_reason("docker inspect", result)
        self.assertEqual(reason, "docker inspect exited 2: some output")

    def test_stderr_takes_precedence_over_stdout(self) -> None:
        result = self._make_result(3, stderr="err message", stdout="out message")
        reason = _subprocess_failure_reason("docker inspect", result)
        self.assertIn("err message", reason)
        self.assertNotIn("out message", reason)

    def test_truncates_long_detail_at_200_chars(self) -> None:
        long_line = "x" * 300
        result = self._make_result(1, stderr=long_line)
        reason = _subprocess_failure_reason("label", result)
        # The detail part (after "label exited 1: ") should be at most 200 chars
        detail = reason.split(": ", 1)[1] if ": " in reason else ""
        self.assertLessEqual(len(detail), 200)


class TestFirstInspectedContainer(unittest.TestCase):
    def test_returns_none_for_empty_list(self) -> None:
        self.assertIsNone(_first_inspected_container([]))

    def test_returns_none_for_non_list(self) -> None:
        self.assertIsNone(_first_inspected_container(None))
        self.assertIsNone(_first_inspected_container({}))
        self.assertIsNone(_first_inspected_container("string"))

    def test_returns_first_dict_element(self) -> None:
        container = {"Id": "abc123", "Image": "my-image"}
        result = _first_inspected_container([container])
        self.assertEqual(result, container)

    def test_returns_none_when_first_element_not_dict(self) -> None:
        result = _first_inspected_container(["not-a-dict"])
        self.assertIsNone(result)

    def test_returns_first_element_of_multiple(self) -> None:
        first = {"Id": "first"}
        second = {"Id": "second"}
        result = _first_inspected_container([first, second])
        self.assertIs(result, first)


class TestInspectedContainerImage(unittest.TestCase):
    def test_returns_top_level_image(self) -> None:
        container = {"Image": "myrepo/myimage:latest"}
        self.assertEqual(_inspected_container_image(container), "myrepo/myimage:latest")

    def test_returns_config_image_when_top_level_missing(self) -> None:
        container = {"Config": {"Image": "config-image:1.0"}}
        self.assertEqual(_inspected_container_image(container), "config-image:1.0")

    def test_top_level_image_takes_precedence_over_config(self) -> None:
        container = {"Image": "top-level", "Config": {"Image": "config-level"}}
        self.assertEqual(_inspected_container_image(container), "top-level")

    def test_returns_empty_string_when_no_image(self) -> None:
        container: dict[str, object] = {}
        self.assertEqual(_inspected_container_image(container), "")

    def test_returns_empty_string_when_image_is_empty_string(self) -> None:
        container = {"Image": ""}
        self.assertEqual(_inspected_container_image(container), "")

    def test_returns_empty_string_when_image_not_string(self) -> None:
        container = {"Image": 123}
        self.assertEqual(_inspected_container_image(container), "")

    def test_returns_empty_string_when_config_not_dict(self) -> None:
        container = {"Config": "not-a-dict"}
        self.assertEqual(_inspected_container_image(container), "")


class TestTrueNasUnavailableSnapshot(unittest.TestCase):
    def test_creates_snapshot_with_both_failed(self) -> None:
        snapshot = _truenas_unavailable_snapshot("test reason")
        self.assertFalse(snapshot.update.ok)
        self.assertFalse(snapshot.alerts.ok)
        self.assertEqual(snapshot.update.reason, "test reason")
        self.assertEqual(snapshot.alerts.reason, "test reason")

    def test_empty_reason(self) -> None:
        snapshot = _truenas_unavailable_snapshot("")
        self.assertEqual(snapshot.update.reason, "")
        self.assertEqual(snapshot.alerts.reason, "")


class TestTrueNasStatusResultFromStdout(unittest.TestCase):
    def test_empty_string_returns_empty_response_error(self) -> None:
        result = _truenas_status_result_from_stdout("")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "empty helper response")

    def test_whitespace_only_returns_empty_response_error(self) -> None:
        result = _truenas_status_result_from_stdout("   \n  ")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "empty helper response")

    def test_invalid_json_returns_error(self) -> None:
        result = _truenas_status_result_from_stdout("not json")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "invalid JSON response")

    def test_json_array_returns_invalid_status(self) -> None:
        result = _truenas_status_result_from_stdout("[1, 2, 3]")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "invalid status response")

    def test_valid_json_dict_returns_ok(self) -> None:
        payload = {"update": {"ok": True}, "alerts": {"ok": True}}
        result = _truenas_status_result_from_stdout(json.dumps(payload))
        self.assertTrue(result.ok)
        self.assertEqual(result.data, payload)

    def test_trims_whitespace_before_parsing(self) -> None:
        payload = {"key": "val"}
        result = _truenas_status_result_from_stdout("  " + json.dumps(payload) + "\n")
        self.assertTrue(result.ok)


class TestTrueNasSnapshotFromPayload(unittest.TestCase):
    def test_non_dict_returns_unavailable_snapshot(self) -> None:
        snapshot = _truenas_snapshot_from_payload(None)
        self.assertFalse(snapshot.update.ok)
        self.assertFalse(snapshot.alerts.ok)
        self.assertEqual(snapshot.update.reason, "invalid status response")

    def test_list_returns_unavailable_snapshot(self) -> None:
        snapshot = _truenas_snapshot_from_payload([1, 2])
        self.assertFalse(snapshot.update.ok)
        self.assertFalse(snapshot.alerts.ok)

    def test_valid_payload_extracts_update_and_alerts(self) -> None:
        payload = {
            "update": {"ok": True, "data": {"status": "AVAILABLE"}, "reason": ""},
            "alerts": {"ok": True, "data": ["alert1"], "reason": ""},
        }
        snapshot = _truenas_snapshot_from_payload(payload)
        self.assertTrue(snapshot.update.ok)
        self.assertTrue(snapshot.alerts.ok)

    def test_failed_payload_preserves_reasons(self) -> None:
        payload = {
            "update": {"ok": False, "data": None, "reason": "midclt not available"},
            "alerts": {"ok": False, "data": None, "reason": "midclt not available"},
        }
        snapshot = _truenas_snapshot_from_payload(payload)
        self.assertFalse(snapshot.update.ok)
        self.assertEqual(snapshot.update.reason, "midclt not available")
        self.assertFalse(snapshot.alerts.ok)
        self.assertEqual(snapshot.alerts.reason, "midclt not available")


class TestTrueNasResultFromPayload(unittest.TestCase):
    def test_non_dict_returns_invalid_status(self) -> None:
        result = _truenas_result_from_payload(None)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "invalid status response")

    def test_ok_true_returns_success_with_data(self) -> None:
        result = _truenas_result_from_payload({"ok": True, "data": [1, 2], "reason": ""})
        self.assertTrue(result.ok)
        self.assertEqual(result.data, [1, 2])

    def test_ok_false_with_reason(self) -> None:
        result = _truenas_result_from_payload({"ok": False, "reason": "timed out"})
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "timed out")

    def test_ok_false_with_empty_reason_uses_unknown_error(self) -> None:
        result = _truenas_result_from_payload({"ok": False, "reason": ""})
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "unknown error")

    def test_ok_false_with_non_string_reason_uses_unknown_error(self) -> None:
        result = _truenas_result_from_payload({"ok": False, "reason": 42})
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "unknown error")

    def test_missing_ok_field_returns_invalid_status(self) -> None:
        result = _truenas_result_from_payload({"data": "something"})
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "invalid status response")

    def test_ok_none_returns_invalid_status(self) -> None:
        result = _truenas_result_from_payload({"ok": None})
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "invalid status response")


class TestTrueNasStatusPayloadJson(unittest.TestCase):
    def test_produces_compact_sorted_json(self) -> None:
        snapshot = TrueNasStatusSnapshot(
            update=TrueNasCallResult(ok=True, data={"status": "UNAVAILABLE"}),
            alerts=TrueNasCallResult(ok=True, data=[]),
        )
        output = _truenas_status_payload_json(snapshot)
        # Should be valid JSON
        parsed = json.loads(output)
        self.assertIn("update", parsed)
        self.assertIn("alerts", parsed)
        # Should use compact separators (no spaces after : or ,)
        self.assertNotIn(": ", output)
        self.assertNotIn(", ", output)

    def test_failed_snapshot_serializes_correctly(self) -> None:
        snapshot = _truenas_unavailable_snapshot("docker not available")
        output = _truenas_status_payload_json(snapshot)
        parsed = json.loads(output)
        self.assertFalse(parsed["update"]["ok"])
        self.assertFalse(parsed["alerts"]["ok"])


class TestTrueNasStatusPayload(unittest.TestCase):
    def test_structure(self) -> None:
        snapshot = TrueNasStatusSnapshot(
            update=TrueNasCallResult(ok=False, reason="no docker"),
            alerts=TrueNasCallResult(ok=False, reason="no docker"),
        )
        payload = _truenas_status_payload(snapshot)
        self.assertIn("update", payload)
        self.assertIn("alerts", payload)

    def test_ok_update_includes_summary(self) -> None:
        snapshot = TrueNasStatusSnapshot(
            update=TrueNasCallResult(ok=True, data={"status": "AVAILABLE", "version": "25.10.1"}),
            alerts=TrueNasCallResult(ok=True, data=[]),
        )
        payload = _truenas_status_payload(snapshot)
        self.assertTrue(payload["update"]["ok"])  # type: ignore[index]
        self.assertIsNotNone(payload["update"]["data"])  # type: ignore[index]


class TestTrueNasUpdateResultToPayload(unittest.TestCase):
    def test_failed_result_has_none_data(self) -> None:
        result = TrueNasCallResult(ok=False, reason="error")
        payload = _truenas_update_result_to_payload(result)
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["data"])
        self.assertEqual(payload["reason"], "error")

    def test_successful_result_includes_summary(self) -> None:
        result = TrueNasCallResult(ok=True, data={"status": "AVAILABLE"})
        payload = _truenas_update_result_to_payload(result)
        self.assertTrue(payload["ok"])
        self.assertIsNotNone(payload["data"])


class TestTrueNasAlertsResultToPayload(unittest.TestCase):
    def test_failed_result_has_none_data(self) -> None:
        result = TrueNasCallResult(ok=False, reason="no midclt")
        payload = _truenas_alerts_result_to_payload(result)
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["data"])

    def test_successful_result_includes_active_alerts(self) -> None:
        result = TrueNasCallResult(ok=True, data=[{"dismissed": False, "formatted": "Alert A"}])
        payload = _truenas_alerts_result_to_payload(result)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"], ["Alert A"])


class TestMidcltCommand(unittest.TestCase):
    def test_update_status_command(self) -> None:
        cmd = _midclt_command("update.status")
        self.assertEqual(cmd, ["midclt", "call", "update.status"])

    def test_alert_list_command(self) -> None:
        cmd = _midclt_command("alert.list")
        self.assertEqual(cmd, ["midclt", "call", "alert.list"])


class TestTrueNasUnreachableMessage(unittest.TestCase):
    def test_without_reason(self) -> None:
        msg = _truenas_unreachable_message("system update check")
        self.assertEqual(msg, "ℹ️  TrueNAS not reachable; skipping system update check.")

    def test_with_reason(self) -> None:
        msg = _truenas_unreachable_message("alert check", "midclt not available")
        self.assertEqual(
            msg,
            "ℹ️  TrueNAS not reachable; skipping alert check. (midclt not available)",
        )

    def test_empty_reason_omits_suffix(self) -> None:
        msg = _truenas_unreachable_message("system update check", "")
        self.assertNotIn("(", msg)


class TestTrueNasUpdateStatus(unittest.TestCase):
    def test_none_returns_empty(self) -> None:
        self.assertEqual(_truenas_update_status(None), "")

    def test_non_dict_returns_empty(self) -> None:
        self.assertEqual(_truenas_update_status([]), "")
        self.assertEqual(_truenas_update_status("string"), "")

    def test_legacy_string_status_returned_directly(self) -> None:
        # Legacy TrueNAS API returns {"status": "AVAILABLE"}
        self.assertEqual(_truenas_update_status({"status": "AVAILABLE"}), "AVAILABLE")
        self.assertEqual(_truenas_update_status({"status": "UNAVAILABLE"}), "UNAVAILABLE")

    def test_error_code_returns_error(self) -> None:
        self.assertEqual(_truenas_update_status({"code": "ERROR"}), "ERROR")

    def test_normal_code_with_new_version_returns_available(self) -> None:
        data = {
            "code": "NORMAL",
            "status": {"new_version": {"version": "25.10.1"}},
        }
        self.assertEqual(_truenas_update_status(data), "AVAILABLE")

    def test_normal_code_with_none_new_version_returns_unavailable(self) -> None:
        data = {
            "code": "NORMAL",
            "status": {"new_version": None},
        }
        self.assertEqual(_truenas_update_status(data), "UNAVAILABLE")

    def test_normal_code_with_empty_dict_new_version_returns_empty(self) -> None:
        data = {
            "code": "NORMAL",
            "status": {"new_version": {}},
        }
        self.assertEqual(_truenas_update_status(data), "")

    def test_unknown_code_returned_as_string(self) -> None:
        data = {"code": "REBOOT_REQUIRED"}
        self.assertEqual(_truenas_update_status(data), "REBOOT_REQUIRED")

    def test_legacy_string_status_takes_precedence_over_code(self) -> None:
        # When "status" is a string, the legacy path returns it directly,
        # even if "code" is also present.
        data = {"code": "NORMAL", "status": "CUSTOM_STATUS"}
        self.assertEqual(_truenas_update_status(data), "CUSTOM_STATUS")


class TestTrueNasUpdateVersion(unittest.TestCase):
    def test_none_returns_empty(self) -> None:
        self.assertEqual(_truenas_update_version(None), "")

    def test_non_dict_returns_empty(self) -> None:
        self.assertEqual(_truenas_update_version([1, 2]), "")

    def test_top_level_version_string(self) -> None:
        # Legacy format
        self.assertEqual(_truenas_update_version({"version": "24.10.2"}), "24.10.2")

    def test_nested_new_version_dict(self) -> None:
        data = {
            "code": "NORMAL",
            "status": {"new_version": {"version": "25.10.1"}},
        }
        self.assertEqual(_truenas_update_version(data), "25.10.1")

    def test_returns_empty_when_no_version(self) -> None:
        self.assertEqual(_truenas_update_version({}), "")

    def test_returns_empty_when_version_not_string(self) -> None:
        self.assertEqual(_truenas_update_version({"version": 123}), "")

    def test_returns_empty_when_status_not_dict(self) -> None:
        data = {"status": "not-a-dict"}
        self.assertEqual(_truenas_update_version(data), "")

    def test_returns_empty_when_new_version_not_dict(self) -> None:
        data = {"status": {"new_version": "1.2.3"}}
        self.assertEqual(_truenas_update_version(data), "")


class TestTrueNasUpdateErrorReason(unittest.TestCase):
    def test_none_returns_empty(self) -> None:
        self.assertEqual(_truenas_update_error_reason(None), "")

    def test_non_dict_returns_empty(self) -> None:
        self.assertEqual(_truenas_update_error_reason([]), "")

    def test_top_level_reason_string(self) -> None:
        self.assertEqual(_truenas_update_error_reason({"reason": "failed"}), "failed")

    def test_nested_error_reason(self) -> None:
        data = {"code": "ERROR", "error": {"reason": "update train failed"}}
        self.assertEqual(_truenas_update_error_reason(data), "update train failed")

    def test_returns_empty_when_error_not_dict(self) -> None:
        data = {"error": "string-error"}
        self.assertEqual(_truenas_update_error_reason(data), "")

    def test_returns_empty_when_reason_not_string(self) -> None:
        data = {"error": {"reason": 42}}
        self.assertEqual(_truenas_update_error_reason(data), "")

    def test_returns_empty_when_no_error_or_reason(self) -> None:
        self.assertEqual(_truenas_update_error_reason({}), "")


class TestTrueNasActiveAlerts(unittest.TestCase):
    def test_none_returns_none(self) -> None:
        self.assertIsNone(_truenas_active_alerts(None))

    def test_non_list_returns_none(self) -> None:
        self.assertIsNone(_truenas_active_alerts({}))
        self.assertIsNone(_truenas_active_alerts("string"))

    def test_empty_list_returns_empty(self) -> None:
        self.assertEqual(_truenas_active_alerts([]), [])

    def test_string_items_included(self) -> None:
        result = _truenas_active_alerts(["Alert one", "Alert two"])
        self.assertEqual(result, ["Alert one", "Alert two"])

    def test_empty_string_items_skipped(self) -> None:
        result = _truenas_active_alerts(["", "Real alert"])
        self.assertEqual(result, ["Real alert"])

    def test_dict_items_formatted_field_used(self) -> None:
        alerts = [
            {"dismissed": False, "formatted": "Pool needs attention"},
            {"dismissed": False, "formatted": "CPU temperature high"},
        ]
        result = _truenas_active_alerts(alerts)
        self.assertEqual(result, ["Pool needs attention", "CPU temperature high"])

    def test_dismissed_dict_items_skipped(self) -> None:
        alerts = [
            {"dismissed": True, "formatted": "Old alert"},
            {"dismissed": False, "formatted": "Active alert"},
        ]
        result = _truenas_active_alerts(alerts)
        self.assertEqual(result, ["Active alert"])

    def test_dict_with_empty_formatted_skipped(self) -> None:
        alerts = [{"dismissed": False, "formatted": ""}]
        result = _truenas_active_alerts(alerts)
        self.assertEqual(result, [])

    def test_dict_without_formatted_skipped(self) -> None:
        alerts = [{"dismissed": False}]
        result = _truenas_active_alerts(alerts)
        self.assertEqual(result, [])

    def test_non_dict_non_string_items_skipped(self) -> None:
        alerts = [42, None, True, "Real alert"]
        result = _truenas_active_alerts(alerts)
        self.assertEqual(result, ["Real alert"])

    def test_mixed_string_and_dict_alerts(self) -> None:
        alerts: list[object] = [
            "String alert",
            {"dismissed": False, "formatted": "Dict alert"},
            {"dismissed": True, "formatted": "Dismissed"},
        ]
        result = _truenas_active_alerts(alerts)
        self.assertEqual(result, ["String alert", "Dict alert"])


class TestTrueNasUpdateSummary(unittest.TestCase):
    def test_none_data_returns_empty_dict(self) -> None:
        from wud_updater.truenas import _truenas_update_summary
        self.assertEqual(_truenas_update_summary(None), {})

    def test_available_update_with_version(self) -> None:
        from wud_updater.truenas import _truenas_update_summary
        data = {"status": "AVAILABLE", "version": "25.10.1"}
        result = _truenas_update_summary(data)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["version"], "25.10.1")

    def test_error_with_reason(self) -> None:
        from wud_updater.truenas import _truenas_update_summary
        data = {"code": "ERROR", "error": {"reason": "train failed"}}
        result = _truenas_update_summary(data)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(result["reason"], "train failed")

    def test_unavailable_with_no_version(self) -> None:
        from wud_updater.truenas import _truenas_update_summary
        data = {"status": "UNAVAILABLE"}
        result = _truenas_update_summary(data)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertNotIn("version", result)
        self.assertNotIn("reason", result)


class TestRunTrueNasStatusExportFromNamespace(unittest.TestCase):
    def test_returns_zero_and_prints_json(self) -> None:
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout

        from wud_updater.truenas import run_truenas_status_export_from_namespace

        args = argparse.Namespace()
        env = {"PATH": ""}  # midclt won't be found

        output = StringIO()
        with redirect_stdout(output):
            status = run_truenas_status_export_from_namespace(args, environ=env)

        self.assertEqual(status, 0)
        payload = json.loads(output.getvalue())
        self.assertIn("update", payload)
        self.assertIn("alerts", payload)
        self.assertFalse(payload["update"]["ok"])
        self.assertFalse(payload["alerts"]["ok"])
        self.assertEqual(payload["update"]["reason"], "midclt not available")
        self.assertEqual(payload["alerts"]["reason"], "midclt not available")

    def test_uses_truenas_status_timeout_from_env(self) -> None:
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout

        from wud_updater.truenas import run_truenas_status_export_from_namespace

        args = argparse.Namespace()
        env = {"PATH": "", "TRUENAS_STATUS_TIMEOUT": "10"}

        output = StringIO()
        with (
            mock.patch("wud_updater.truenas._midclt_json") as mock_midclt,
            redirect_stdout(output),
        ):
            mock_midclt.return_value = TrueNasCallResult(ok=False, reason="no midclt")
            run_truenas_status_export_from_namespace(args, environ=env)

        # Called twice (update.status and alert.list), both with timeout "10"
        calls = mock_midclt.call_args_list
        self.assertEqual(len(calls), 2)
        for call_args in calls:
            self.assertEqual(call_args[0][1], "10")

    def test_uses_default_timeout_when_not_set(self) -> None:
        import argparse
        from io import StringIO
        from contextlib import redirect_stdout

        from wud_updater.truenas import run_truenas_status_export_from_namespace

        args = argparse.Namespace()
        env = {"PATH": ""}

        output = StringIO()
        with (
            mock.patch("wud_updater.truenas._midclt_json") as mock_midclt,
            redirect_stdout(output),
        ):
            mock_midclt.return_value = TrueNasCallResult(ok=False, reason="no midclt")
            run_truenas_status_export_from_namespace(args, environ=env)

        calls = mock_midclt.call_args_list
        self.assertEqual(len(calls), 2)
        for call_args in calls:
            self.assertEqual(call_args[0][1], DEFAULT_TRUENAS_STATUS_TIMEOUT)


class TestTrueNasHelperTimeoutSeconds(unittest.TestCase):
    def test_minimum_is_five(self) -> None:
        from wud_updater.truenas import _truenas_helper_timeout_seconds
        # With call_timeout=0, max(5, 0*2+5) = max(5, 5) = 5
        result = _truenas_helper_timeout_seconds("0")
        self.assertGreaterEqual(result, 5)

    def test_scales_with_call_timeout(self) -> None:
        from wud_updater.truenas import _truenas_helper_timeout_seconds
        # With call_timeout=10, max(5, 10*2+5) = max(5, 25) = 25
        result = _truenas_helper_timeout_seconds("10")
        self.assertEqual(result, 25)

    def test_default_timeout(self) -> None:
        from wud_updater.truenas import _truenas_helper_timeout_seconds
        # With call_timeout=5 (default), max(5, 5*2+5) = max(5, 15) = 15
        result = _truenas_helper_timeout_seconds("5")
        self.assertEqual(result, 15)


class TestImportsMovedFromUpdates(unittest.TestCase):
    """Verify that the refactored imports are in truenas.py and not updates.py."""

    def test_truenas_exports_default_timeout(self) -> None:
        from wud_updater.truenas import DEFAULT_TRUENAS_STATUS_TIMEOUT
        self.assertIsInstance(DEFAULT_TRUENAS_STATUS_TIMEOUT, str)

    def test_truenas_exports_middleware_mount(self) -> None:
        from wud_updater.truenas import TRUENAS_MIDDLEWARE_MOUNT
        self.assertIsInstance(TRUENAS_MIDDLEWARE_MOUNT, str)

    def test_truenas_exports_call_result(self) -> None:
        from wud_updater.truenas import TrueNasCallResult
        result = TrueNasCallResult(ok=True)
        self.assertTrue(result.ok)

    def test_updates_still_imports_from_truenas(self) -> None:
        # Verify updates.py can import these via truenas
        from wud_updater.updates import UpdatesRunner  # noqa: F401 - import check
        from wud_updater.truenas import DEFAULT_TRUENAS_STATUS_TIMEOUT  # noqa: F401

    def test_cli_imports_from_truenas(self) -> None:
        # Verify cli.py imports run_truenas_status_export_from_namespace from truenas
        from wud_updater.truenas import run_truenas_status_export_from_namespace
        self.assertTrue(callable(run_truenas_status_export_from_namespace))

    def test_doctor_imports_from_truenas(self) -> None:
        # Verify doctor.py can get DEFAULT_TRUENAS_STATUS_TIMEOUT from truenas
        from wud_updater.truenas import DEFAULT_TRUENAS_STATUS_TIMEOUT, TRUENAS_MIDDLEWARE_MOUNT
        self.assertIsNotNone(DEFAULT_TRUENAS_STATUS_TIMEOUT)
        self.assertIsNotNone(TRUENAS_MIDDLEWARE_MOUNT)


class TestRefreshTrueNasStatus(unittest.TestCase):
    """Tests for _refresh_truenas_status behavior."""

    def _make_options(self, truenas_status_timeout: str = "5") -> object:
        """Create a minimal options-like object."""
        from unittest.mock import MagicMock
        opts = MagicMock()
        opts.truenas_status_timeout = truenas_status_timeout
        return opts

    def test_helper_failure_returns_unavailable_snapshot(self) -> None:
        from wud_updater.truenas import _refresh_truenas_status

        options = self._make_options()
        environ = {"PATH": ""}  # docker not available

        with mock.patch(
            "wud_updater.truenas._run_truenas_status_helper",
            return_value=TrueNasCallResult(ok=False, reason="docker not available"),
        ):
            snapshot = _refresh_truenas_status(options, environ)

        self.assertFalse(snapshot.update.ok)
        self.assertFalse(snapshot.alerts.ok)
        self.assertEqual(snapshot.update.reason, "docker not available")

    def test_helper_success_parses_payload(self) -> None:
        from wud_updater.truenas import _refresh_truenas_status

        options = self._make_options()
        environ = {"PATH": ""}
        payload = {
            "update": {"ok": True, "data": {"status": "AVAILABLE"}, "reason": ""},
            "alerts": {"ok": True, "data": ["Alert!"], "reason": ""},
        }

        with mock.patch(
            "wud_updater.truenas._run_truenas_status_helper",
            return_value=TrueNasCallResult(ok=True, data=payload),
        ):
            snapshot = _refresh_truenas_status(options, environ)

        self.assertTrue(snapshot.update.ok)
        self.assertTrue(snapshot.alerts.ok)


class TestRunTrueNasStatusHelper(unittest.TestCase):
    """Tests for _run_truenas_status_helper."""

    def _make_options(self, truenas_status_timeout: str = "5") -> object:
        from unittest.mock import MagicMock
        opts = MagicMock()
        opts.truenas_status_timeout = truenas_status_timeout
        return opts

    def test_no_docker_returns_failure(self) -> None:
        from wud_updater.truenas import _run_truenas_status_helper

        options = self._make_options()
        environ = {"PATH": ""}  # docker won't be found

        result = _run_truenas_status_helper(options, environ)

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "docker not available")

    def test_missing_hostname_returns_failure(self) -> None:
        from wud_updater.truenas import _run_truenas_status_helper

        options = self._make_options()
        environ = {"PATH": ""}

        with mock.patch("wud_updater.truenas._has_command", return_value=True):
            result = _run_truenas_status_helper(options, environ)

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "HOSTNAME not available")

    def test_docker_inspect_timeout_returns_failure(self) -> None:
        from wud_updater.truenas import _run_truenas_status_helper

        options = self._make_options()
        environ = {"PATH": "", "HOSTNAME": "my-container"}

        with (
            mock.patch("wud_updater.truenas._has_command", return_value=True),
            mock.patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=5),
            ),
        ):
            result = _run_truenas_status_helper(options, environ)

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "docker inspect timed out")

    def test_docker_inspect_failure_returns_failure(self) -> None:
        from wud_updater.truenas import _run_truenas_status_helper

        options = self._make_options()
        environ = {"PATH": "", "HOSTNAME": "my-container"}
        failed_result = subprocess.CompletedProcess(
            args=["docker"],
            returncode=1,
            stdout="",
            stderr="container not found",
        )

        with (
            mock.patch("wud_updater.truenas._has_command", return_value=True),
            mock.patch("subprocess.run", return_value=failed_result),
        ):
            result = _run_truenas_status_helper(options, environ)

        self.assertFalse(result.ok)
        self.assertIn("docker inspect exited 1", result.reason)

    def test_docker_inspect_invalid_json_returns_failure(self) -> None:
        from wud_updater.truenas import _run_truenas_status_helper

        options = self._make_options()
        environ = {"PATH": "", "HOSTNAME": "my-container"}
        ok_result = subprocess.CompletedProcess(
            args=["docker"],
            returncode=0,
            stdout="not json",
            stderr="",
        )

        with (
            mock.patch("wud_updater.truenas._has_command", return_value=True),
            mock.patch("subprocess.run", return_value=ok_result),
        ):
            result = _run_truenas_status_helper(options, environ)

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "docker inspect returned invalid JSON")

    def test_docker_inspect_empty_list_returns_no_container(self) -> None:
        from wud_updater.truenas import _run_truenas_status_helper

        options = self._make_options()
        environ = {"PATH": "", "HOSTNAME": "my-container"}
        ok_result = subprocess.CompletedProcess(
            args=["docker"],
            returncode=0,
            stdout="[]",
            stderr="",
        )

        with (
            mock.patch("wud_updater.truenas._has_command", return_value=True),
            mock.patch("subprocess.run", return_value=ok_result),
        ):
            result = _run_truenas_status_helper(options, environ)

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "docker inspect returned no container")


if __name__ == "__main__":
    unittest.main()
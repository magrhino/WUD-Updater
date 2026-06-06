"""Unit tests for wud_updater.truenas (extracted from updates.py in this PR)."""

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
    _inspected_container_image,
    _midclt_command,
    _midclt_json,
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


class TrueNasCallResultTests(unittest.TestCase):
    def test_ok_result_defaults(self) -> None:
        r = TrueNasCallResult(ok=True)
        self.assertTrue(r.ok)
        self.assertIsNone(r.data)
        self.assertEqual(r.reason, "")

    def test_failed_result_with_reason(self) -> None:
        r = TrueNasCallResult(ok=False, reason="midclt not available")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "midclt not available")

    def test_ok_result_with_data(self) -> None:
        data = {"status": "AVAILABLE"}
        r = TrueNasCallResult(ok=True, data=data)
        self.assertEqual(r.data, data)

    def test_frozen(self) -> None:
        r = TrueNasCallResult(ok=True)
        with self.assertRaises(Exception):
            r.ok = False  # type: ignore[misc]


class TrueNasStatusSnapshotTests(unittest.TestCase):
    def test_snapshot_holds_update_and_alerts(self) -> None:
        update = TrueNasCallResult(ok=True, data={"status": "UNAVAILABLE"})
        alerts = TrueNasCallResult(ok=True, data=[])
        snap = TrueNasStatusSnapshot(update=update, alerts=alerts)
        self.assertIs(snap.update, update)
        self.assertIs(snap.alerts, alerts)

    def test_frozen(self) -> None:
        update = TrueNasCallResult(ok=False)
        alerts = TrueNasCallResult(ok=False)
        snap = TrueNasStatusSnapshot(update=update, alerts=alerts)
        with self.assertRaises(Exception):
            snap.update = TrueNasCallResult(ok=True)  # type: ignore[misc]


class TrueNasConstantsTests(unittest.TestCase):
    def test_default_timeout(self) -> None:
        self.assertEqual(DEFAULT_TRUENAS_STATUS_TIMEOUT, "5")

    def test_middleware_mount(self) -> None:
        self.assertEqual(TRUENAS_MIDDLEWARE_MOUNT, "/var/run/middleware")


class SubprocessFailureReasonTests(unittest.TestCase):
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

    def test_includes_label_and_exit_code(self) -> None:
        result = self._make_result(1)
        reason = _subprocess_failure_reason("docker inspect", result)
        self.assertIn("docker inspect", reason)
        self.assertIn("1", reason)

    def test_includes_stderr_detail(self) -> None:
        result = self._make_result(1, stderr="permission denied")
        reason = _subprocess_failure_reason("docker inspect", result)
        self.assertIn("permission denied", reason)

    def test_falls_back_to_stdout_when_stderr_empty(self) -> None:
        result = self._make_result(1, stderr="", stdout="no such container")
        reason = _subprocess_failure_reason("docker run", result)
        self.assertIn("no such container", reason)

    def test_prefers_stderr_over_stdout(self) -> None:
        result = self._make_result(1, stderr="err detail", stdout="out detail")
        reason = _subprocess_failure_reason("docker run", result)
        self.assertIn("err detail", reason)
        self.assertNotIn("out detail", reason)

    def test_truncates_long_detail(self) -> None:
        long_line = "x" * 300
        result = self._make_result(1, stderr=long_line)
        reason = _subprocess_failure_reason("cmd", result)
        # Detail is capped at 200 chars
        self.assertLessEqual(len(reason), 250)

    def test_multiline_detail_uses_first_line(self) -> None:
        result = self._make_result(1, stderr="line one\nline two\nline three")
        reason = _subprocess_failure_reason("cmd", result)
        self.assertIn("line one", reason)
        self.assertNotIn("line two", reason)


class FirstInspectedContainerTests(unittest.TestCase):
    def test_returns_first_dict(self) -> None:
        data = [{"Id": "abc123", "Image": "repo/img"}]
        result = _first_inspected_container(data)
        self.assertIsNotNone(result)
        self.assertEqual(result["Id"], "abc123")  # type: ignore[index]

    def test_returns_none_for_empty_list(self) -> None:
        self.assertIsNone(_first_inspected_container([]))

    def test_returns_none_for_non_list(self) -> None:
        self.assertIsNone(_first_inspected_container({"Id": "abc"}))
        self.assertIsNone(_first_inspected_container(None))
        self.assertIsNone(_first_inspected_container("string"))

    def test_returns_none_when_first_item_not_dict(self) -> None:
        self.assertIsNone(_first_inspected_container(["not_a_dict"]))

    def test_returns_first_item_ignoring_rest(self) -> None:
        data = [{"Id": "first"}, {"Id": "second"}]
        result = _first_inspected_container(data)
        self.assertEqual(result["Id"], "first")  # type: ignore[index]


class InspectedContainerImageTests(unittest.TestCase):
    def test_returns_image_field(self) -> None:
        container = {"Image": "sha256:abc123def456"}
        self.assertEqual(_inspected_container_image(container), "sha256:abc123def456")

    def test_falls_back_to_config_image(self) -> None:
        container = {"Config": {"Image": "repo/img:tag"}}
        self.assertEqual(_inspected_container_image(container), "repo/img:tag")

    def test_prefers_top_level_image_over_config(self) -> None:
        container = {"Image": "sha256:abc", "Config": {"Image": "repo/img:tag"}}
        self.assertEqual(_inspected_container_image(container), "sha256:abc")

    def test_returns_empty_when_no_image(self) -> None:
        self.assertEqual(_inspected_container_image({}), "")

    def test_returns_empty_when_image_not_string(self) -> None:
        self.assertEqual(_inspected_container_image({"Image": None}), "")
        self.assertEqual(_inspected_container_image({"Image": 123}), "")

    def test_returns_empty_when_image_is_empty_string(self) -> None:
        self.assertEqual(_inspected_container_image({"Image": ""}), "")

    def test_returns_empty_when_config_image_not_string(self) -> None:
        self.assertEqual(_inspected_container_image({"Config": {"Image": None}}), "")

    def test_returns_empty_when_config_not_dict(self) -> None:
        self.assertEqual(_inspected_container_image({"Config": "not-a-dict"}), "")


class TrueNasUnavailableSnapshotTests(unittest.TestCase):
    def test_sets_both_results_to_not_ok(self) -> None:
        snap = _truenas_unavailable_snapshot("docker not available")
        self.assertFalse(snap.update.ok)
        self.assertFalse(snap.alerts.ok)

    def test_copies_reason_to_both(self) -> None:
        snap = _truenas_unavailable_snapshot("HOSTNAME not available")
        self.assertEqual(snap.update.reason, "HOSTNAME not available")
        self.assertEqual(snap.alerts.reason, "HOSTNAME not available")

    def test_data_is_none(self) -> None:
        snap = _truenas_unavailable_snapshot("reason")
        self.assertIsNone(snap.update.data)
        self.assertIsNone(snap.alerts.data)


class TrueNasStatusResultFromStdoutTests(unittest.TestCase):
    def test_parses_valid_json_dict(self) -> None:
        payload = {"update": {"ok": True}, "alerts": {"ok": True}}
        result = _truenas_status_result_from_stdout(json.dumps(payload))
        self.assertTrue(result.ok)
        self.assertEqual(result.data, payload)

    def test_empty_stdout_returns_failure(self) -> None:
        result = _truenas_status_result_from_stdout("")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "empty helper response")

    def test_whitespace_only_stdout_returns_failure(self) -> None:
        result = _truenas_status_result_from_stdout("   \n  ")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "empty helper response")

    def test_invalid_json_returns_failure(self) -> None:
        result = _truenas_status_result_from_stdout("not json")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "invalid JSON response")

    def test_json_non_dict_returns_failure(self) -> None:
        result = _truenas_status_result_from_stdout('["list"]')
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "invalid status response")

    def test_strips_surrounding_whitespace(self) -> None:
        payload = {"status": "ok"}
        result = _truenas_status_result_from_stdout(f"\n{json.dumps(payload)}\n")
        self.assertTrue(result.ok)


class TrueNasSnapshotFromPayloadTests(unittest.TestCase):
    def test_parses_valid_payload(self) -> None:
        payload = {
            "update": {"ok": True, "data": {"status": "UNAVAILABLE"}, "reason": ""},
            "alerts": {"ok": True, "data": [], "reason": ""},
        }
        snap = _truenas_snapshot_from_payload(payload)
        self.assertTrue(snap.update.ok)
        self.assertTrue(snap.alerts.ok)

    def test_invalid_payload_type_returns_unavailable(self) -> None:
        snap = _truenas_snapshot_from_payload(None)
        self.assertFalse(snap.update.ok)
        self.assertFalse(snap.alerts.ok)
        self.assertEqual(snap.update.reason, "invalid status response")

    def test_non_dict_payload_returns_unavailable(self) -> None:
        snap = _truenas_snapshot_from_payload(["list"])
        self.assertFalse(snap.update.ok)

    def test_propagates_failed_results(self) -> None:
        payload = {
            "update": {"ok": False, "reason": "midclt timed out"},
            "alerts": {"ok": False, "reason": "midclt timed out"},
        }
        snap = _truenas_snapshot_from_payload(payload)
        self.assertFalse(snap.update.ok)
        self.assertEqual(snap.update.reason, "midclt timed out")
        self.assertFalse(snap.alerts.ok)


class TrueNasResultFromPayloadTests(unittest.TestCase):
    def test_ok_true_with_data(self) -> None:
        value = {"ok": True, "data": {"status": "AVAILABLE"}, "reason": ""}
        result = _truenas_result_from_payload(value)
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"status": "AVAILABLE"})

    def test_ok_false_with_reason(self) -> None:
        value = {"ok": False, "reason": "midclt not available"}
        result = _truenas_result_from_payload(value)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "midclt not available")

    def test_ok_false_with_empty_reason_defaults_to_unknown_error(self) -> None:
        value = {"ok": False, "reason": ""}
        result = _truenas_result_from_payload(value)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "unknown error")

    def test_ok_false_with_non_string_reason_defaults_to_unknown_error(self) -> None:
        value = {"ok": False, "reason": 42}
        result = _truenas_result_from_payload(value)
        self.assertEqual(result.reason, "unknown error")

    def test_missing_ok_key_returns_invalid_status(self) -> None:
        result = _truenas_result_from_payload({"data": "something"})
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "invalid status response")

    def test_non_dict_value_returns_invalid_status(self) -> None:
        result = _truenas_result_from_payload("not a dict")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "invalid status response")

    def test_none_value_returns_invalid_status(self) -> None:
        result = _truenas_result_from_payload(None)
        self.assertFalse(result.ok)


class TrueNasStatusPayloadTests(unittest.TestCase):
    def test_structure_has_update_and_alerts_keys(self) -> None:
        update = TrueNasCallResult(ok=True, data={"status": "UNAVAILABLE"})
        alerts = TrueNasCallResult(ok=True, data=[])
        snap = TrueNasStatusSnapshot(update=update, alerts=alerts)
        payload = _truenas_status_payload(snap)
        self.assertIn("update", payload)
        self.assertIn("alerts", payload)

    def test_failed_update_has_no_data(self) -> None:
        update = TrueNasCallResult(ok=False, reason="no midclt")
        alerts = TrueNasCallResult(ok=False, reason="no midclt")
        snap = TrueNasStatusSnapshot(update=update, alerts=alerts)
        payload = _truenas_status_payload(snap)
        self.assertFalse(payload["update"]["ok"])  # type: ignore[index]
        self.assertIsNone(payload["update"]["data"])  # type: ignore[index]

    def test_json_serialization_is_compact_sorted(self) -> None:
        update = TrueNasCallResult(ok=False, reason="n/a")
        alerts = TrueNasCallResult(ok=False, reason="n/a")
        snap = TrueNasStatusSnapshot(update=update, alerts=alerts)
        result_str = _truenas_status_payload_json(snap)
        # Compact: no spaces after separators
        self.assertNotIn(": ", result_str)
        # Valid JSON
        parsed = json.loads(result_str)
        self.assertIn("alerts", parsed)
        self.assertIn("update", parsed)
        # Keys are sorted
        keys = list(json.loads(result_str).keys())
        self.assertEqual(keys, sorted(keys))


class TrueNasUpdateResultToPayloadTests(unittest.TestCase):
    def test_ok_result_includes_summary(self) -> None:
        data = {"code": "NORMAL", "status": {"new_version": {"version": "25.10"}}}
        result = TrueNasCallResult(ok=True, data=data)
        payload = _truenas_update_result_to_payload(result)
        self.assertTrue(payload["ok"])
        self.assertIsNotNone(payload["data"])

    def test_failed_result_has_none_data(self) -> None:
        result = TrueNasCallResult(ok=False, reason="midclt timed out")
        payload = _truenas_update_result_to_payload(result)
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["data"])
        self.assertEqual(payload["reason"], "midclt timed out")


class TrueNasAlertsResultToPayloadTests(unittest.TestCase):
    def test_ok_result_with_list_data(self) -> None:
        data = [{"dismissed": False, "formatted": "Pool degraded"}]
        result = TrueNasCallResult(ok=True, data=data)
        payload = _truenas_alerts_result_to_payload(result)
        self.assertTrue(payload["ok"])
        self.assertIsNotNone(payload["data"])

    def test_failed_result_has_none_data(self) -> None:
        result = TrueNasCallResult(ok=False, reason="docker not available")
        payload = _truenas_alerts_result_to_payload(result)
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["data"])


class TrueNasUpdateSummaryTests(unittest.TestCase):
    def test_status_included_when_present(self) -> None:
        data = {"status": "AVAILABLE"}
        summary = _truenas_update_summary(data)
        self.assertEqual(summary.get("status"), "AVAILABLE")

    def test_version_included_when_present(self) -> None:
        data = {"version": "25.10.1", "status": "AVAILABLE"}
        summary = _truenas_update_summary(data)
        self.assertEqual(summary.get("version"), "25.10.1")

    def test_reason_included_when_present(self) -> None:
        data = {"code": "ERROR", "reason": "train failed"}
        summary = _truenas_update_summary(data)
        self.assertEqual(summary.get("reason"), "train failed")

    def test_empty_dict_for_none_data(self) -> None:
        summary = _truenas_update_summary(None)
        self.assertEqual(summary, {})

    def test_does_not_include_empty_strings(self) -> None:
        data = {}
        summary = _truenas_update_summary(data)
        self.assertNotIn("status", summary)
        self.assertNotIn("version", summary)
        self.assertNotIn("reason", summary)


class TrueNasUnreachableMessageTests(unittest.TestCase):
    def test_message_without_reason(self) -> None:
        msg = _truenas_unreachable_message("system update check")
        self.assertIn("TrueNAS not reachable", msg)
        self.assertIn("system update check", msg)
        self.assertNotIn("(", msg)

    def test_message_with_reason(self) -> None:
        msg = _truenas_unreachable_message("alert check", "midclt not available")
        self.assertIn("alert check", msg)
        self.assertIn("midclt not available", msg)
        self.assertIn("(", msg)
        self.assertIn(")", msg)


class TrueNasUpdateStatusTests(unittest.TestCase):
    """Tests for _truenas_update_status covering legacy and new TrueNAS API formats."""

    def test_legacy_string_status_available(self) -> None:
        # Old TrueNAS format: status is a plain string
        data = {"status": "AVAILABLE"}
        self.assertEqual(_truenas_update_status(data), "AVAILABLE")

    def test_legacy_string_status_unavailable(self) -> None:
        data = {"status": "UNAVAILABLE"}
        self.assertEqual(_truenas_update_status(data), "UNAVAILABLE")

    def test_new_format_normal_with_new_version(self) -> None:
        # New TrueNAS format: code=NORMAL, status dict with new_version
        data = {
            "code": "NORMAL",
            "status": {"new_version": {"version": "25.10.1"}},
            "error": None,
        }
        self.assertEqual(_truenas_update_status(data), "AVAILABLE")

    def test_new_format_normal_without_new_version(self) -> None:
        data = {
            "code": "NORMAL",
            "status": {"new_version": None},
            "error": None,
        }
        self.assertEqual(_truenas_update_status(data), "UNAVAILABLE")

    def test_new_format_error_code(self) -> None:
        data = {"code": "ERROR", "status": None, "error": {"reason": "train failed"}}
        self.assertEqual(_truenas_update_status(data), "ERROR")

    def test_new_format_unknown_code(self) -> None:
        data = {"code": "PENDING", "status": None}
        self.assertEqual(_truenas_update_status(data), "PENDING")

    def test_none_data_returns_empty(self) -> None:
        self.assertEqual(_truenas_update_status(None), "")

    def test_non_dict_data_returns_empty(self) -> None:
        self.assertEqual(_truenas_update_status("AVAILABLE"), "")
        self.assertEqual(_truenas_update_status([]), "")

    def test_empty_dict_returns_empty(self) -> None:
        self.assertEqual(_truenas_update_status({}), "")

    def test_new_format_empty_new_version_dict_returns_empty(self) -> None:
        # new_version is an empty dict - not considered "available"
        data = {"code": "NORMAL", "status": {"new_version": {}}}
        self.assertEqual(_truenas_update_status(data), "")


class TrueNasUpdateVersionTests(unittest.TestCase):
    def test_legacy_version_field(self) -> None:
        data = {"version": "24.04.2", "status": "AVAILABLE"}
        self.assertEqual(_truenas_update_version(data), "24.04.2")

    def test_new_format_nested_version(self) -> None:
        data = {
            "code": "NORMAL",
            "status": {"new_version": {"version": "25.10.1"}},
        }
        self.assertEqual(_truenas_update_version(data), "25.10.1")

    def test_returns_empty_when_no_version(self) -> None:
        data = {"code": "NORMAL", "status": {"new_version": None}}
        self.assertEqual(_truenas_update_version(data), "")

    def test_returns_empty_for_none_data(self) -> None:
        self.assertEqual(_truenas_update_version(None), "")

    def test_returns_empty_for_non_dict(self) -> None:
        self.assertEqual(_truenas_update_version("not a dict"), "")

    def test_returns_empty_when_version_not_string(self) -> None:
        data = {"version": 25}
        self.assertEqual(_truenas_update_version(data), "")


class TrueNasUpdateErrorReasonTests(unittest.TestCase):
    def test_legacy_reason_field(self) -> None:
        data = {"reason": "train not accessible"}
        self.assertEqual(_truenas_update_error_reason(data), "train not accessible")

    def test_new_format_nested_error_reason(self) -> None:
        data = {"code": "ERROR", "error": {"reason": "update train failed"}}
        self.assertEqual(_truenas_update_error_reason(data), "update train failed")

    def test_returns_empty_for_none_data(self) -> None:
        self.assertEqual(_truenas_update_error_reason(None), "")

    def test_returns_empty_for_non_dict(self) -> None:
        self.assertEqual(_truenas_update_error_reason("string"), "")

    def test_returns_empty_when_no_reason_fields(self) -> None:
        self.assertEqual(_truenas_update_error_reason({}), "")

    def test_returns_empty_when_error_not_dict(self) -> None:
        data = {"error": "not a dict"}
        self.assertEqual(_truenas_update_error_reason(data), "")

    def test_returns_empty_when_error_reason_not_string(self) -> None:
        data = {"error": {"reason": 42}}
        self.assertEqual(_truenas_update_error_reason(data), "")


class TrueNasActiveAlertsTests(unittest.TestCase):
    def test_returns_none_for_non_list(self) -> None:
        self.assertIsNone(_truenas_active_alerts(None))
        self.assertIsNone(_truenas_active_alerts({}))
        self.assertIsNone(_truenas_active_alerts("not a list"))

    def test_empty_list_returns_empty_list(self) -> None:
        self.assertEqual(_truenas_active_alerts([]), [])

    def test_extracts_formatted_from_dict_items(self) -> None:
        data = [
            {"dismissed": False, "formatted": "Pool needs attention"},
            {"dismissed": False, "formatted": "SMART test failed"},
        ]
        alerts = _truenas_active_alerts(data)
        self.assertIsNotNone(alerts)
        self.assertIn("Pool needs attention", alerts)  # type: ignore[operator]
        self.assertIn("SMART test failed", alerts)  # type: ignore[operator]

    def test_skips_dismissed_alerts(self) -> None:
        data = [
            {"dismissed": True, "formatted": "Dismissed alert"},
            {"dismissed": False, "formatted": "Active alert"},
        ]
        alerts = _truenas_active_alerts(data)
        self.assertIsNotNone(alerts)
        self.assertNotIn("Dismissed alert", alerts)  # type: ignore[operator]
        self.assertIn("Active alert", alerts)  # type: ignore[operator]

    def test_accepts_plain_string_items(self) -> None:
        data = ["Alert one", "Alert two"]
        alerts = _truenas_active_alerts(data)
        self.assertEqual(alerts, ["Alert one", "Alert two"])

    def test_skips_empty_string_items(self) -> None:
        data = ["Real alert", ""]
        alerts = _truenas_active_alerts(data)
        self.assertIsNotNone(alerts)
        self.assertEqual(alerts, ["Real alert"])

    def test_skips_non_dict_non_string_items(self) -> None:
        data = [42, None, {"dismissed": False, "formatted": "valid"}]
        alerts = _truenas_active_alerts(data)
        self.assertEqual(alerts, ["valid"])

    def test_skips_dict_items_with_no_formatted(self) -> None:
        data = [{"dismissed": False}]
        alerts = _truenas_active_alerts(data)
        self.assertEqual(alerts, [])

    def test_skips_dict_items_with_empty_formatted(self) -> None:
        data = [{"dismissed": False, "formatted": ""}]
        alerts = _truenas_active_alerts(data)
        self.assertEqual(alerts, [])


class TrueNasHelperTimeoutTests(unittest.TestCase):
    def test_minimum_is_five_seconds(self) -> None:
        # call_timeout=1 -> max(5, 1*2+5) = max(5, 7) = 7
        result = _truenas_helper_timeout_seconds("1")
        self.assertEqual(result, 7)

    def test_small_timeout_formula(self) -> None:
        # call_timeout=5 -> max(5, 5*2+5) = max(5, 15) = 15
        result = _truenas_helper_timeout_seconds("5")
        self.assertEqual(result, 15)

    def test_larger_timeout(self) -> None:
        # call_timeout=30 -> max(5, 30*2+5) = 65
        result = _truenas_helper_timeout_seconds("30")
        self.assertEqual(result, 65)


class MidcltCommandTests(unittest.TestCase):
    def test_returns_correct_command(self) -> None:
        cmd = _midclt_command("update.status")
        self.assertEqual(cmd, ["midclt", "call", "update.status"])

    def test_returns_list(self) -> None:
        cmd = _midclt_command("alert.list")
        self.assertIsInstance(cmd, list)
        self.assertEqual(len(cmd), 3)


class MidcltJsonTests(unittest.TestCase):
    def _env_with_midclt(self, path: str) -> dict[str, str]:
        import os
        env = dict(os.environ)
        env["PATH"] = f"{path}:{env.get('PATH', '')}"
        return env

    def test_returns_failure_when_midclt_not_in_path(self) -> None:
        result = _midclt_json("update.status", "5", {"PATH": "/nonexistent"})
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "midclt not available")

    def test_returns_failure_on_invalid_timeout(self) -> None:
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            midclt_path = os.path.join(tmpdir, "midclt")
            with open(midclt_path, "w") as f:
                f.write("#!/bin/sh\nexit 0\n")
            os.chmod(midclt_path, 0o755)
            env = {"PATH": tmpdir}
            result = _midclt_json("update.status", "not_a_number", env)
            self.assertFalse(result.ok)

    def test_returns_parsed_json_on_success(self) -> None:
        data = {"code": "NORMAL", "status": {"new_version": None}}
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(data) + "\n"
        mock_result.stderr = ""

        with mock.patch("shutil.which", return_value="/usr/bin/midclt"), \
             mock.patch("subprocess.run", return_value=mock_result):
            result = _midclt_json("update.status", "5", {"PATH": "/usr/bin"})

        self.assertTrue(result.ok)
        self.assertEqual(result.data, data)

    def test_returns_failure_on_non_zero_exit(self) -> None:
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error"

        with mock.patch("shutil.which", return_value="/usr/bin/midclt"), \
             mock.patch("subprocess.run", return_value=mock_result):
            result = _midclt_json("update.status", "5", {"PATH": "/usr/bin"})

        self.assertFalse(result.ok)
        self.assertIn("1", result.reason)

    def test_returns_failure_on_empty_stdout(self) -> None:
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with mock.patch("shutil.which", return_value="/usr/bin/midclt"), \
             mock.patch("subprocess.run", return_value=mock_result):
            result = _midclt_json("update.status", "5", {"PATH": "/usr/bin"})

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "empty midclt response")

    def test_returns_failure_on_invalid_json(self) -> None:
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not json"
        mock_result.stderr = ""

        with mock.patch("shutil.which", return_value="/usr/bin/midclt"), \
             mock.patch("subprocess.run", return_value=mock_result):
            result = _midclt_json("update.status", "5", {"PATH": "/usr/bin"})

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "invalid JSON response")

    def test_returns_failure_on_timeout(self) -> None:
        with mock.patch("shutil.which", return_value="/usr/bin/midclt"), \
             mock.patch(
                 "subprocess.run",
                 side_effect=subprocess.TimeoutExpired(cmd=["midclt"], timeout=5),
             ):
            result = _midclt_json("update.status", "5", {"PATH": "/usr/bin"})

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "midclt timed out")

    def test_returns_failure_on_os_error(self) -> None:
        with mock.patch("shutil.which", return_value="/usr/bin/midclt"), \
             mock.patch(
                 "subprocess.run",
                 side_effect=OSError("Permission denied"),
             ):
            result = _midclt_json("update.status", "5", {"PATH": "/usr/bin"})

        self.assertFalse(result.ok)
        self.assertIn("midclt failed", result.reason)


class RunTrueNasStatusExportTests(unittest.TestCase):
    """Tests for run_truenas_status_export_from_namespace."""

    def _make_args(self) -> object:
        import argparse
        return argparse.Namespace()

    def test_returns_zero_and_prints_json(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        mock_update = TrueNasCallResult(ok=False, reason="midclt not available")
        mock_alerts = TrueNasCallResult(ok=False, reason="midclt not available")
        mock_snapshot = TrueNasStatusSnapshot(update=mock_update, alerts=mock_alerts)

        with mock.patch(
            "wud_updater.truenas._midclt_json",
            return_value=TrueNasCallResult(ok=False, reason="midclt not available"),
        ):
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = run_truenas_status_export_from_namespace(
                    self._make_args(),
                    environ={"PATH": "/nonexistent"},
                )

        self.assertEqual(status, 0)
        output = stdout.getvalue().strip()
        parsed = json.loads(output)
        self.assertIn("update", parsed)
        self.assertIn("alerts", parsed)

    def test_uses_custom_timeout_from_environ(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        calls: list[tuple[str, str]] = []

        def fake_midclt_json(
            method: str,
            timeout: str,
            environ: object,
        ) -> TrueNasCallResult:
            calls.append((method, timeout))
            return TrueNasCallResult(ok=False, reason="test")

        with mock.patch("wud_updater.truenas._midclt_json", fake_midclt_json):
            stdout = StringIO()
            with redirect_stdout(stdout):
                run_truenas_status_export_from_namespace(
                    self._make_args(),
                    environ={"TRUENAS_STATUS_TIMEOUT": "42"},
                )

        # Verify the timeout was passed through
        self.assertTrue(all(t == "42" for _, t in calls))

    def test_uses_default_timeout_when_not_set(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        calls: list[str] = []

        def fake_midclt_json(
            method: str,
            timeout: str,
            environ: object,
        ) -> TrueNasCallResult:
            calls.append(timeout)
            return TrueNasCallResult(ok=False, reason="test")

        with mock.patch("wud_updater.truenas._midclt_json", fake_midclt_json):
            stdout = StringIO()
            with redirect_stdout(stdout):
                run_truenas_status_export_from_namespace(
                    self._make_args(),
                    environ={},
                )

        self.assertEqual(calls[0], DEFAULT_TRUENAS_STATUS_TIMEOUT)


class TrueNasUpdateSummaryPrivateFieldTests(unittest.TestCase):
    """Ensure private fields from the TrueNAS API are not leaked in summaries."""

    def test_private_field_not_in_update_summary(self) -> None:
        data = {
            "code": "NORMAL",
            "status": {"new_version": {"version": "25.10.1"}},
            "private": "private-update-detail",
        }
        summary = _truenas_update_summary(data)
        self.assertNotIn("private", summary)

    def test_private_alert_fields_not_in_active_alerts(self) -> None:
        data = [
            {
                "dismissed": False,
                "formatted": "Pool needs attention",
                "args": {"private": "private-alert-arg"},
                "mail": {"to": "private@example.test"},
            }
        ]
        alerts = _truenas_active_alerts(data)
        # Only the formatted string should appear
        self.assertEqual(alerts, ["Pool needs attention"])


if __name__ == "__main__":
    unittest.main()
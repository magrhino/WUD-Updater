from __future__ import annotations

import json
import tempfile
import unittest

from wudup.command import CommandResult
from wudup.digest_verifier import ResolvedImageSubject
from wudup.security_scanner import TrivyScanner
from wudup.web_models import SecurityScanConfig


class FakeRunner:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.calls: list[tuple[tuple[str, ...], float | None]] = []

    def capture(
        self,
        args: list[str] | tuple[str, ...],
        *,
        check: bool = True,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        del check
        normalized = tuple(args)
        self.calls.append((normalized, timeout_seconds))
        if normalized == ("trivy", "--version"):
            return CommandResult(
                args=normalized,
                cwd=None,
                returncode=0,
                stdout="Version: 0.50.0\n",
            )
        return CommandResult(
            args=normalized,
            cwd=None,
            returncode=0,
            stdout=self.stdout,
        )


class SecurityScannerTests(unittest.TestCase):
    def test_trivy_registry_scan_uses_fixed_remote_argv_and_normalizes_counts(self) -> None:
        payload = {
            "SchemaVersion": 2,
            "VulnerabilityDB": {
                "Version": "2026-06-26",
                "UpdatedAt": "2026-06-26T00:00:00Z",
            },
            "Results": [
                {
                    "Vulnerabilities": [
                        {"Severity": "HIGH", "FixedVersion": "1.2.3"},
                        {"Severity": "MEDIUM", "FixedVersion": ""},
                    ],
                }
            ],
        }
        runner = FakeRunner(json.dumps(payload))
        with tempfile.TemporaryDirectory(prefix="wudup-trivy-cache-") as cache_dir:
            scanner = TrivyScanner(
                SecurityScanConfig(
                    enabled=True,
                    timeout_seconds=30,
                    cache_dir=cache_dir,
                ),
                runner=runner,  # type: ignore[arg-type]
            )

            result = scanner.scan(_exact_subject())

        self.assertEqual(result.state, "complete")
        self.assertEqual(result.verdict, "findings")
        self.assertEqual(result.scanner_version, "0.50.0")
        self.assertEqual(result.scanner_schema, "2")
        self.assertEqual(result.db_revision, "2026-06-26")
        self.assertEqual(result.severity_counts["high"], 1)
        self.assertEqual(result.severity_counts["medium"], 1)
        self.assertEqual(result.fixable_counts["high"], 1)
        self.assertEqual(result.unfixed_count, 1)
        scan_args, scan_timeout = runner.calls[0]
        self.assertEqual(scan_timeout, 35.0)
        self.assertEqual(
            scan_args,
            (
                "trivy",
                "image",
                "--scanners",
                "vuln",
                "--format",
                "json",
                "--quiet",
                "--disable-telemetry",
                "--image-src",
                "remote",
                "--platform",
                "linux/amd64",
                "--timeout",
                "30s",
                "--cache-dir",
                cache_dir,
                "ghcr.io/acme/app@sha256:child",
            ),
        )

    def test_trivy_invalid_json_returns_error_result(self) -> None:
        scanner = TrivyScanner(
            SecurityScanConfig(enabled=True),
            runner=FakeRunner("{bad json"),  # type: ignore[arg-type]
        )

        result = scanner.scan(_exact_subject())

        self.assertEqual(result.state, "error")
        self.assertEqual(result.error_code, "invalid_json")
        self.assertEqual(result.scanner_version, "0.50.0")

    def test_trivy_missing_results_array_returns_error_result(self) -> None:
        scanner = TrivyScanner(
            SecurityScanConfig(enabled=True),
            runner=FakeRunner("{}"),  # type: ignore[arg-type]
        )

        result = scanner.scan(_exact_subject())

        self.assertEqual(result.state, "error")
        self.assertEqual(result.verdict, "unknown")
        self.assertEqual(result.error_code, "invalid_json")
        self.assertEqual(
            result.error_message,
            "scanner JSON did not include a Results array",
        )

    def test_trivy_does_not_scan_non_exact_subject(self) -> None:
        runner = FakeRunner("{}")
        scanner = TrivyScanner(
            SecurityScanConfig(enabled=True),
            runner=runner,  # type: ignore[arg-type]
        )

        result = scanner.scan(
            ResolvedImageSubject(identity_status="unsupported", error="missing digest")
        )

        self.assertEqual(result.state, "unsupported")
        self.assertEqual(result.error_code, "unsupported")
        self.assertEqual(result.error_message, "missing digest")
        self.assertEqual(runner.calls, [])

    def test_trivy_missing_immutable_ref_uses_unsupported_error_code(self) -> None:
        runner = FakeRunner("{}")
        scanner = TrivyScanner(
            SecurityScanConfig(enabled=True),
            runner=runner,  # type: ignore[arg-type]
        )

        result = scanner.scan(
            ResolvedImageSubject(
                canonical_registry="ghcr.io",
                canonical_repository="acme/app",
                identity_status="exact",
                error="missing manifest digest",
                warnings=("subject warning",),
            )
        )

        self.assertEqual(result.state, "unsupported")
        self.assertEqual(result.error_code, "unsupported")
        self.assertEqual(result.error_message, "missing manifest digest")
        self.assertEqual(result.warnings, ("subject warning",))
        self.assertEqual(runner.calls, [])


def _exact_subject() -> ResolvedImageSubject:
    return ResolvedImageSubject(
        canonical_registry="ghcr.io",
        canonical_repository="acme/app",
        requested_ref="ghcr.io/acme/app:latest",
        reported_digest="sha256:index",
        index_digest="sha256:index",
        manifest_digest="sha256:child",
        os="linux",
        architecture="amd64",
        platform_source="compose",
        identity_status="exact",
    )


if __name__ == "__main__":
    unittest.main()

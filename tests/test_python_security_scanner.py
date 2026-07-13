from __future__ import annotations

import json
import tempfile
import unittest

from wudup.command import CommandResult
from wudup.digest_verifier import ResolvedImageSubject
from wudup.security_scanner import TrivyScanner
from wudup.security_severity import normalize_security_severity
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
        if len(normalized) >= 2 and normalized[:2] == ("trivy", "version"):
            return CommandResult(
                args=normalized,
                cwd=None,
                returncode=0,
                stdout=json.dumps(
                    {
                        "Version": "0.50.0",
                        "VulnerabilityDB": {
                            "Version": "2",
                            "UpdatedAt": "2026-06-26T00:00:00Z",
                        },
                    }
                ),
            )
        return CommandResult(
            args=normalized,
            cwd=None,
            returncode=0,
            stdout=self.stdout,
        )


class SecurityScannerTests(unittest.TestCase):
    def test_security_severity_normalization_is_shared(self) -> None:
        self.assertEqual(normalize_security_severity(" HIGH "), "high")
        self.assertEqual(normalize_security_severity("negligible"), "unknown")
        self.assertEqual(normalize_security_severity(None), "unknown")

    def test_trivy_registry_scan_uses_fixed_remote_argv_and_normalizes_counts(self) -> None:
        payload = {
            "SchemaVersion": 2,
            "VulnerabilityDB": {
                "Version": "2",
                "UpdatedAt": "2026-06-26T00:00:00Z",
            },
            "Results": [
                {
                    "Target": "debian:12",
                    "Class": "os-pkgs",
                    "Type": "debian",
                    "Vulnerabilities": [
                        {"Severity": "HIGH", "FixedVersion": "1.2.3"},
                        {
                            "FixedVersion": "",
                            "InstalledVersion": "2.0.0",
                            "PkgName": "openssl",
                            "PrimaryURL": "http://avd.aquasec.com/nvd/cve-2026-0001",
                            "Severity": "MEDIUM",
                            "Title": "demo vulnerability",
                            "VulnerabilityID": "CVE-2026-0001",
                        },
                        {
                            "PkgName": "ignored-url",
                            "PrimaryURL": "javascript:alert(1)",
                            "Severity": "LOW",
                            "VulnerabilityID": "CVE-2026-0002",
                        },
                        {
                            "PkgName": "duplicate-higher-severity",
                            "Severity": "CRITICAL",
                            "VulnerabilityID": "CVE-2026-0002",
                        },
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
        self.assertEqual(result.db_revision, "2")
        self.assertEqual(result.db_updated_at, "2026-06-26T00:00:00Z")
        self.assertEqual(result.severity_counts["high"], 1)
        self.assertEqual(result.severity_counts["medium"], 1)
        self.assertEqual(result.severity_counts["low"], 1)
        self.assertEqual(result.severity_counts["critical"], 1)
        self.assertEqual(result.advisory_counts["high"], 0)
        self.assertEqual(result.advisory_counts["medium"], 1)
        self.assertEqual(result.advisory_counts["low"], 0)
        self.assertEqual(result.advisory_counts["critical"], 1)
        self.assertEqual(result.fixable_counts["high"], 1)
        self.assertEqual(result.unfixed_count, 3)
        self.assertEqual(result.findings[1].vulnerability_id, "CVE-2026-0001")
        self.assertEqual(result.findings[1].target, "debian:12")
        self.assertEqual(result.findings[1].target_class, "os-pkgs")
        self.assertEqual(result.findings[1].target_type, "debian")
        self.assertEqual(result.findings[1].package_name, "openssl")
        self.assertEqual(result.findings[1].installed_version, "2.0.0")
        self.assertEqual(result.findings[1].fixed_version, "")
        self.assertEqual(result.findings[1].severity, "medium")
        self.assertEqual(result.findings[1].title, "demo vulnerability")
        self.assertEqual(
            result.findings[1].primary_url,
            "https://avd.aquasec.com/nvd/cve-2026-0001",
        )
        self.assertEqual(result.findings[2].primary_url, "")
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

    def test_trivy_refreshes_provenance_for_each_scan(self) -> None:
        class ChangingProvenanceRunner(FakeRunner):
            def __init__(self) -> None:
                super().__init__(json.dumps({"SchemaVersion": 2, "Results": []}))
                self.version_call_count = 0

            def capture(self, args, *, check=True, timeout_seconds=None):
                normalized = tuple(args)
                if normalized[:2] != ("trivy", "version"):
                    return super().capture(
                        args,
                        check=check,
                        timeout_seconds=timeout_seconds,
                    )
                self.calls.append((normalized, timeout_seconds))
                self.version_call_count += 1
                return CommandResult(
                    args=normalized,
                    cwd=None,
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "Version": "0.50.0",
                            "VulnerabilityDB": {
                                "Version": str(self.version_call_count),
                                "UpdatedAt": (
                                    f"2026-06-{25 + self.version_call_count:02d}T00:00:00Z"
                                ),
                            },
                        }
                    ),
                )

        runner = ChangingProvenanceRunner()
        scanner = TrivyScanner(
            SecurityScanConfig(enabled=True),
            runner=runner,  # type: ignore[arg-type]
        )

        first = scanner.scan(_exact_subject())
        second = scanner.scan(_exact_subject())

        self.assertEqual(first.db_revision, "1")
        self.assertEqual(first.db_updated_at, "2026-06-26T00:00:00Z")
        self.assertEqual(second.db_revision, "2")
        self.assertEqual(second.db_updated_at, "2026-06-27T00:00:00Z")
        self.assertEqual(runner.version_call_count, 2)

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

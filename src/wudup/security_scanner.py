"""External security scanner adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .command import CommandRunner
from .digest_verifier import ResolvedImageSubject
from .web_models import SecurityScanConfig


SEVERITIES = ("critical", "high", "medium", "low", "unknown")


@dataclass(frozen=True)
class SecurityScanFinding:
    vulnerability_id: str = ""
    package_name: str = ""
    installed_version: str = ""
    fixed_version: str = ""
    severity: str = "unknown"
    title: str = ""
    primary_url: str = ""


@dataclass(frozen=True)
class SecurityScanResult:
    state: str
    verdict: str = "unknown"
    scanner: str = "trivy"
    scanner_version: str = ""
    scanner_schema: str = ""
    db_revision: str = ""
    db_updated_at: str = ""
    severity_counts: Mapping[str, int] = field(default_factory=dict)
    fixable_counts: Mapping[str, int] = field(default_factory=dict)
    unfixed_count: int = 0
    findings: tuple[SecurityScanFinding, ...] = ()
    warnings: tuple[str, ...] = ()
    error_code: str = ""
    error_message: str = ""


class TrivyScanner:
    def __init__(
        self,
        config: SecurityScanConfig,
        *,
        runner: CommandRunner | None = None,
    ) -> None:
        self.config = config
        self.runner = runner or CommandRunner()
        self._version: str | None = None

    def scan(self, subject: ResolvedImageSubject) -> SecurityScanResult:
        if subject.identity_status != "exact" or not subject.immutable_ref:
            error_code = subject.identity_status or "unsupported"
            if not subject.immutable_ref:
                error_code = "unsupported"
            return SecurityScanResult(
                state="unsupported",
                error_code=error_code,
                error_message=subject.error or "security scan subject is not exact",
                warnings=subject.warnings,
            )
        args = self._scan_args(subject)
        result = self.runner.capture(
            args,
            check=False,
            timeout_seconds=float(self.config.timeout_seconds + 5),
        )
        if not result.ok:
            return SecurityScanResult(
                state="error",
                scanner_version=self.version(),
                error_code="scanner_failed",
                error_message=(result.stderr or result.stdout).strip(),
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return SecurityScanResult(
                state="error",
                scanner_version=self.version(),
                error_code="invalid_json",
                error_message=str(exc),
            )
        if not isinstance(payload, Mapping):
            return SecurityScanResult(
                state="error",
                scanner_version=self.version(),
                error_code="invalid_json",
                error_message="scanner JSON was not an object",
            )
        return _result_from_trivy_payload(
            payload,
            scanner_version=self.version(),
        )

    def version(self) -> str:
        if self._version is not None:
            return self._version
        result = self.runner.capture(
            [self.config.executable, "--version"],
            check=False,
            timeout_seconds=10,
        )
        self._version = _parse_trivy_version(result.stdout) if result.ok else ""
        return self._version

    def _scan_args(self, subject: ResolvedImageSubject) -> list[str]:
        args = [
            self.config.executable,
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
            subject.platform,
            "--timeout",
            f"{self.config.timeout_seconds}s",
        ]
        if self.config.cache_dir:
            args.extend(["--cache-dir", self.config.cache_dir])
        args.append(subject.immutable_ref)
        return args


def _result_from_trivy_payload(
    payload: Mapping[str, Any],
    *,
    scanner_version: str,
) -> SecurityScanResult:
    if not isinstance(payload.get("Results"), list):
        return SecurityScanResult(
            state="error",
            scanner_version=scanner_version,
            error_code="invalid_json",
            error_message="scanner JSON did not include a Results array",
        )
    severity_counts = _empty_counts()
    fixable_counts = _empty_counts()
    unfixed_count = 0
    findings: list[SecurityScanFinding] = []
    for vuln in _vulnerabilities(payload):
        severity = _severity(vuln.get("Severity"))
        severity_counts[severity] += 1
        fixed_version = str(vuln.get("FixedVersion") or "").strip()
        if fixed_version:
            fixable_counts[severity] += 1
        else:
            unfixed_count += 1
        findings.append(_finding_from_vulnerability(vuln, severity))
    total = sum(severity_counts.values())
    db = _db_metadata(payload)
    return SecurityScanResult(
        state="complete",
        verdict="findings" if total else "none_reported",
        scanner_version=scanner_version,
        scanner_schema=str(payload.get("SchemaVersion") or ""),
        db_revision=str(db.get("Version") or db.get("version") or ""),
        db_updated_at=str(
            db.get("UpdatedAt")
            or db.get("updated_at")
            or db.get("DownloadedAt")
            or db.get("downloaded_at")
            or ""
        ),
        severity_counts=severity_counts,
        fixable_counts=fixable_counts,
        unfixed_count=unfixed_count,
        findings=tuple(findings),
    )


def _vulnerabilities(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    values: list[Mapping[str, Any]] = []
    results = payload.get("Results")
    if not isinstance(results, list):
        return ()
    for result in results:
        if not isinstance(result, Mapping):
            continue
        vulns = result.get("Vulnerabilities")
        if not isinstance(vulns, list):
            continue
        values.extend(item for item in vulns if isinstance(item, Mapping))
    return tuple(values)


def _db_metadata(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    db = payload.get("VulnerabilityDB")
    if isinstance(db, Mapping):
        return db
    metadata = payload.get("Metadata")
    if isinstance(metadata, Mapping):
        db = metadata.get("VulnerabilityDB")
        if isinstance(db, Mapping):
            return db
    return {}


def _empty_counts() -> dict[str, int]:
    return dict.fromkeys(SEVERITIES, 0)


def _finding_from_vulnerability(
    vuln: Mapping[str, Any],
    severity: str,
) -> SecurityScanFinding:
    return SecurityScanFinding(
        vulnerability_id=str(vuln.get("VulnerabilityID") or "").strip(),
        package_name=str(vuln.get("PkgName") or "").strip(),
        installed_version=str(vuln.get("InstalledVersion") or "").strip(),
        fixed_version=str(vuln.get("FixedVersion") or "").strip(),
        severity=severity,
        title=str(vuln.get("Title") or "").strip(),
        primary_url=_http_url(vuln.get("PrimaryURL")),
    )


def _http_url(value: object) -> str:
    url = str(value or "").strip()
    return url if url.startswith(("https://", "http://")) else ""


def _severity(value: object) -> str:
    severity = str(value or "").strip().lower()
    return severity if severity in SEVERITIES else "unknown"


def _parse_trivy_version(output: str) -> str:
    for line in output.splitlines():
        line = line.strip()
        if line.lower().startswith("version:"):
            return line.split(":", 1)[1].strip()
    return output.splitlines()[0].strip() if output.splitlines() else ""

"""External security scanner adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .command import CommandRunner
from .digest_verifier import ResolvedImageSubject
from .security_severity import SECURITY_SEVERITIES, normalize_security_severity
from .web_models import SecurityScanConfig


@dataclass(frozen=True)
class SecurityScanFinding:
    target: str = ""
    target_class: str = ""
    target_type: str = ""
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
    advisory_counts: Mapping[str, int] = field(default_factory=dict)
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
        self._provenance: Mapping[str, Any] = {}

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
            provenance=self.provenance(),
        )

    def version(self) -> str:
        return str(self.provenance().get("Version") or "")

    def provenance(self) -> Mapping[str, Any]:
        if self._version is not None:
            return self._provenance
        args = [self.config.executable, "version", "--format", "json"]
        if self.config.cache_dir:
            args.extend(["--cache-dir", self.config.cache_dir])
        result = self.runner.capture(
            args,
            check=False,
            timeout_seconds=10,
        )
        self._provenance = _parse_trivy_provenance(result.stdout) if result.ok else {}
        self._version = str(self._provenance.get("Version") or "")
        return self._provenance

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
    provenance: Mapping[str, Any],
) -> SecurityScanResult:
    scanner_version = str(provenance.get("Version") or "")
    if not isinstance(payload.get("Results"), list):
        return SecurityScanResult(
            state="error",
            scanner_version=scanner_version,
            error_code="invalid_json",
            error_message="scanner JSON did not include a Results array",
        )
    severity_counts = _empty_counts()
    advisory_severities: dict[str, str] = {}
    fixable_counts = _empty_counts()
    unfixed_count = 0
    findings: list[SecurityScanFinding] = []
    for result, vuln in _vulnerabilities(payload):
        severity = normalize_security_severity(vuln.get("Severity"))
        severity_counts[severity] += 1
        vulnerability_id = str(vuln.get("VulnerabilityID") or "").strip()
        if vulnerability_id:
            previous = advisory_severities.get(vulnerability_id)
            if previous is None or SECURITY_SEVERITIES.index(
                severity
            ) < SECURITY_SEVERITIES.index(previous):
                advisory_severities[vulnerability_id] = severity
        fixed_version = str(vuln.get("FixedVersion") or "").strip()
        if fixed_version:
            fixable_counts[severity] += 1
        else:
            unfixed_count += 1
        findings.append(_finding_from_vulnerability(result, vuln, severity))
    total = sum(severity_counts.values())
    advisory_counts = _empty_counts()
    for severity in advisory_severities.values():
        advisory_counts[severity] += 1
    db = _db_metadata(provenance) or _db_metadata(payload)
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
        advisory_counts=advisory_counts,
        fixable_counts=fixable_counts,
        unfixed_count=unfixed_count,
        findings=tuple(findings),
    )


def _vulnerabilities(
    payload: Mapping[str, Any],
) -> tuple[tuple[Mapping[str, Any], Mapping[str, Any]], ...]:
    values: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    results = payload.get("Results")
    if not isinstance(results, list):
        return ()
    for result in results:
        if not isinstance(result, Mapping):
            continue
        vulns = result.get("Vulnerabilities")
        if not isinstance(vulns, list):
            continue
        values.extend((result, item) for item in vulns if isinstance(item, Mapping))
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
    return dict.fromkeys(SECURITY_SEVERITIES, 0)


def _finding_from_vulnerability(
    result: Mapping[str, Any],
    vuln: Mapping[str, Any],
    severity: str,
) -> SecurityScanFinding:
    return SecurityScanFinding(
        target=str(result.get("Target") or "").strip(),
        target_class=str(result.get("Class") or "").strip(),
        target_type=str(result.get("Type") or "").strip(),
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
    if url.startswith("https://"):
        return url
    if url.startswith("http://"):
        return f"https://{url[7:]}"
    return ""


def _parse_trivy_provenance(output: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, Mapping) else {}

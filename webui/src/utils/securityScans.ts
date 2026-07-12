import type {
  PendingItem,
  SecurityScanFinding,
  SecurityScanInfo,
  SecurityScansResponse,
} from "../api/client";

export type SecurityScanDisplayType =
  | "default"
  | "error"
  | "info"
  | "success"
  | "warning";

export type SecurityScanCueDisplay = {
  key: string;
  label: string;
  type: SecurityScanDisplayType;
};

export type SecurityScanSummaryDisplay = {
  label: string;
  type: SecurityScanDisplayType;
};

type SecurityScanDisplaySource = Pick<
  SecurityScanInfo,
  "state" | "verdict" | "severity_counts" | "comparison"
>;

type SecurityScanSummaryContext = {
  securityScans: Pick<SecurityScansResponse, "scanning_enabled"> | null;
  securityScansCurrent: boolean;
  items: SecurityScanDisplaySource[];
};

type PendingPlatformSource = Pick<
  PendingItem,
  | "platform"
  | "platform_os"
  | "platform_architecture"
  | "platform_variant"
  | "wud_metadata"
>;

function pluralize(count: number, singular: string): string {
  return `${count} ${count === 1 ? singular : `${singular}s`}`;
}

export function normalizeSecurityDigest(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  const digest = trimmed.includes("@sha256:")
    ? trimmed.slice(trimmed.lastIndexOf("@") + 1)
    : trimmed;
  return digest.startsWith("sha256:") ? digest : `sha256:${digest}`;
}

export function platformFromParts(
  os: string | undefined,
  architecture: string | undefined,
  variant: string | undefined,
): string {
  const platformOs = os?.trim() ?? "";
  const platformArchitecture = architecture?.trim() ?? "";
  if (!platformOs || !platformArchitecture) {
    return "";
  }
  return [platformOs, platformArchitecture, variant?.trim() ?? ""]
    .filter(Boolean)
    .join("/");
}

export function pendingItemPlatform(item: PendingPlatformSource): string {
  if (item.platform?.trim()) {
    return item.platform.trim();
  }
  const wudMetadata = item.wud_metadata;
  if (wudMetadata?.platform?.trim()) {
    return wudMetadata.platform.trim();
  }
  const wudPlatform = platformFromParts(
    wudMetadata?.platform_os,
    wudMetadata?.platform_architecture,
    wudMetadata?.platform_variant,
  );
  if (wudPlatform) {
    return wudPlatform;
  }
  return platformFromParts(
    item.platform_os,
    item.platform_architecture,
    item.platform_variant,
  );
}

export function securityScanFindingsType(
  scan: Pick<SecurityScanInfo, "severity_counts">,
): "error" | "warning" {
  return scan.severity_counts.critical > 0 || scan.severity_counts.high > 0
    ? "error"
    : "warning";
}

function titleCase(value: string): string {
  return value ? `${value.charAt(0).toUpperCase()}${value.slice(1)}` : "Unknown";
}

function comparisonCueDisplay(
  scan: SecurityScanDisplaySource,
): SecurityScanCueDisplay | null {
  if (scan.state !== "complete") {
    return null;
  }
  const comparison = scan.comparison;
  if (comparison.status === "improved") {
    const remainingCount = comparison.remaining_findings.length;
    return {
      key: "security-improved",
      label: remainingCount > 0 ? "Findings reduced" : "Findings fixed",
      type: remainingCount > 0 ? securityScanFindingsType(scan) : "success",
    };
  }
  if (comparison.status === "mixed") {
    return {
      key: "security-mixed",
      label: "Findings changed",
      type: securityScanFindingsType(scan),
    };
  }
  if (comparison.status === "worse") {
    return {
      key: "security-worse",
      label: "Findings introduced",
      type: securityScanFindingsType(scan),
    };
  }
  if (comparison.status === "unchanged" && comparison.remaining_findings.length > 0) {
    return {
      key: "security-remaining",
      label: "Findings remain",
      type: securityScanFindingsType(scan),
    };
  }
  return null;
}

export function securityScanCueDisplay(
  scan: SecurityScanDisplaySource,
): SecurityScanCueDisplay | null {
  if (scan.state === "disabled") {
    return null;
  }
  const comparisonDisplay = comparisonCueDisplay(scan);
  if (comparisonDisplay) {
    return comparisonDisplay;
  }
  if (scan.state === "complete" && scan.verdict === "findings") {
    return {
      key: "security-findings",
      label: "Findings",
      type: securityScanFindingsType(scan),
    };
  }
  if (scan.state === "complete" && scan.verdict === "none_reported") {
    return {
      key: "security-none-reported",
      label: "None reported",
      type: "success",
    };
  }
  if (scan.state === "not_scanned") {
    return {
      key: "security-not-scanned",
      label: "Not scanned",
      type: "default",
    };
  }
  if (scan.state === "stale") {
    return {
      key: "security-stale",
      label: "Scan stale",
      type: "warning",
    };
  }
  return {
    key: "security-unknown",
    label: "Security unknown",
    type: "warning",
  };
}

export function securityScanSummaryDisplay({
  securityScans,
  securityScansCurrent,
  items,
}: SecurityScanSummaryContext): SecurityScanSummaryDisplay {
  if (!securityScans) {
    return { label: "Security scans loading", type: "default" };
  }
  if (!securityScans.scanning_enabled) {
    return { label: "Security scans off", type: "default" };
  }
  if (!securityScansCurrent) {
    return { label: "Security scans stale", type: "warning" };
  }
  const itemDisplays = items
    .map((scan) => securityScanCueDisplay(scan))
    .filter((display): display is SecurityScanCueDisplay => display !== null);
  if (itemDisplays.some((display) => display.key === "security-stale")) {
    return { label: "Security scans stale", type: "warning" };
  }
  const findings = items.filter(
    (scan) => scan.state === "complete" && scan.verdict === "findings",
  );
  if (findings.length > 0) {
    return {
      label:
        findings.length === 1
          ? "1 candidate with findings"
          : `${findings.length} candidates with findings`,
      type: findings.some((scan) => securityScanFindingsType(scan) === "error")
        ? "error"
        : "warning",
    };
  }
  const complete = items.filter((scan) => scan.state === "complete").length;
  if (complete > 0) {
    return {
      label: `${pluralize(complete, "candidate")} scanned`,
      type: "info",
    };
  }
  return { label: "No candidate scans yet", type: "info" };
}

function digestForReport(value: string): string {
  return value || "unknown";
}

function findingLine(finding: SecurityScanFinding): string {
  const advisory = finding.vulnerability_id || "unknown advisory";
  const pkg = finding.package_name || "unknown package";
  const installed = finding.installed_version || "unknown";
  const fixed = finding.fixed_version || "not published";
  const details = [
    `${advisory} in ${pkg}`,
    `target ${finding.target || "unknown"}`,
    `class ${finding.target_class || "unknown"}`,
    `type ${finding.target_type || "unknown"}`,
    `${titleCase(finding.severity)} severity`,
    `installed ${installed}`,
    `fixed ${fixed}`,
  ];
  if (finding.title) {
    details.push(finding.title);
  }
  if (finding.primary_url) {
    details.push(finding.primary_url);
  }
  return `- ${details.join("; ")}`;
}

export function securityScanMaintainerReport(scan: SecurityScanInfo): string {
  const fixed = scan.comparison.fixed_findings;
  const remaining = scan.comparison.remaining_findings;
  const introduced = scan.comparison.introduced_findings;
  if (!fixed.length && !remaining.length && !introduced.length) {
    return "";
  }

  const currentDigest =
    scan.comparison.current_subject.manifest_digest ||
    scan.comparison.current_subject.reported_digest;
  const candidateDigest = scan.subject.manifest_digest || scan.subject.reported_digest;
  const scannerParts = [scan.scanner, scan.scanner_version].filter(Boolean);
  const scanner = scannerParts.length ? scannerParts.join(" ") : "unknown scanner";
  const database = [
    `revision ${scan.db_revision || "unknown"}`,
    `updated ${scan.db_updated_at || "unknown"}`,
  ].join("; ");
  const subject = scan.subject.requested_ref || `line ${scan.line_no}`;
  const lines = [
    `Security scan update report for ${subject}`,
    "",
    `Comparison: ${scan.comparison.message || scan.comparison.status}`,
    `Scanner: ${scanner}; schema ${scan.scanner_schema || "unknown"}; database ${database}`,
    `Platform: ${scan.subject.platform || "unknown"}`,
    `Installed subject: ${digestForReport(scan.comparison.current_subject.immutable_ref || currentDigest)}`,
    `Candidate index digest: ${digestForReport(scan.subject.index_digest || scan.subject.reported_digest)}`,
    `Candidate platform digest: ${digestForReport(candidateDigest)}`,
    `Exact Trivy subject: ${digestForReport(scan.subject.immutable_ref)}`,
  ];

  if (fixed.length) {
    lines.push(
      "",
      `Fixed installed findings (${fixed.length}):`,
      ...fixed.map(findingLine),
    );
  }
  if (remaining.length) {
    lines.push(
      "",
      `Remaining candidate findings (${remaining.length}):`,
      ...remaining.map(findingLine),
    );
  }
  if (introduced.length) {
    lines.push(
      "",
      `Introduced candidate findings (${introduced.length}):`,
      ...introduced.map(findingLine),
    );
  }
  return lines.join("\n");
}

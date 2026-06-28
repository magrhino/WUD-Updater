import type {
  PendingItem,
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
  "state" | "verdict" | "severity_counts"
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

export function securityScanMatchesPendingItem(
  scan: SecurityScanInfo,
  item: PendingItem,
): boolean {
  if (scan.subject.raw !== item.raw || scan.subject.image !== item.image) {
    return false;
  }
  if (
    normalizeSecurityDigest(scan.subject.reported_digest) !==
    normalizeSecurityDigest(item.digest)
  ) {
    return false;
  }
  const itemPlatform = pendingItemPlatform(item);
  const scanPlatform = scan.subject.platform.trim();
  if (scan.subject.platform_source === "compose") {
    return Boolean(scanPlatform);
  }
  return !scanPlatform || (Boolean(itemPlatform) && scanPlatform === itemPlatform);
}

export function securityScanFindingsType(
  scan: Pick<SecurityScanInfo, "severity_counts">,
): "error" | "warning" {
  return scan.severity_counts.critical > 0 || scan.severity_counts.high > 0
    ? "error"
    : "warning";
}

export function securityScanCueDisplay(
  scan: SecurityScanDisplaySource,
): SecurityScanCueDisplay | null {
  if (scan.state === "disabled") {
    return null;
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
  const findings = itemDisplays.filter(
    (display) => display.key === "security-findings",
  );
  if (findings.length > 0) {
    return {
      label: pluralize(findings.length, "candidate with findings"),
      type: findings.some((display) => display.type === "error")
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

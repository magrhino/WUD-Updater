import { mount, type VueWrapper } from "@vue/test-utils";
import { defineComponent, h, type Component, type VNodeChild } from "vue";
import { describe, expect, it, vi } from "vitest";

import type {
  PendingItem,
  SecurityScanFinding,
  SecurityScanInfo,
} from "../src/api/client";
import PendingCleanupModal from "../src/components/pending/PendingCleanupModal.vue";
import PendingPlanReviewModal from "../src/components/pending/PendingPlanReviewModal.vue";
import PendingRemovalModal from "../src/components/pending/PendingRemovalModal.vue";
import PendingSecurityScanDetails from "../src/components/pending/PendingSecurityScanDetails.vue";
import {
  digestProvenanceDisplay,
  displayDigest,
} from "../src/utils/digestProvenance";
import { securityScanSummaryDisplay } from "../src/utils/securityScans";
import { safetyCues } from "../src/views/pending/safetyCues";
import { createPendingColumns } from "../src/views/pending/tableColumns";
import {
  groupedItemActionLabel,
  groupedItemActionTagType,
  groupedItemServiceKeys,
  groupedItemTarget,
  itemsBreakingCount,
  pendingSourceFileName,
  releaseNoteReason,
  releaseNoteStatus,
  tagInputProps,
  uniqueSorted,
  uniqueStrings,
} from "../src/views/pending/pendingDisplay";
import {
  filterPendingStackGroups,
  normalizePendingSearch,
  pendingItemMatchesSearch,
  type PendingSearchContext,
} from "../src/views/pending/pendingFilter";
import {
  planLineDigestPinLabel,
  planLineDigestUnpinLabel,
} from "../src/views/pending/utils";
import {
  pendingGroupedItem,
  pendingResponse,
  planResponse,
  releaseNoteInfo,
  servicePolicy,
  snooze,
} from "./helpers/fixtures";
import { mountWithApp, naiveStubs } from "./helpers/mount";

type RenderColumn = {
  key?: string;
  render?: (row: PendingItem) => VNodeChild;
};

function mountPendingModal(component: Component, props: Record<string, unknown>): VueWrapper {
  return mount(component, {
    props,
    global: {
      stubs: {
        ...naiveStubs,
        CoreUpdateTourPanel: { template: "<div />" },
      },
    },
  });
}

function securityScanInfo(
  overrides: Partial<SecurityScanInfo> = {},
): SecurityScanInfo {
  const severityCounts = {
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
    unknown: 0,
    ...overrides.severity_counts,
  };
  return {
    line_no: 1,
    state: "not_scanned",
    verdict: "unknown",
    scanner: "trivy",
    scanner_version: "",
    scanner_schema: "",
    scanned_at: "",
    db_revision: "",
    db_updated_at: "",
    fixable_counts: {
      critical: 0,
      high: 0,
      medium: 0,
      low: 0,
      unknown: 0,
    },
    unfixed_count: 0,
    findings: [],
    subject: {
      requested_ref: "repo/app:2.0",
      reported_digest: "sha256:candidate",
      manifest_digest: "sha256:candidate-child",
      platform: "linux/amd64",
    },
    comparison: {
      status: "unknown",
      current_subject: {
        requested_ref: "",
        reported_digest: "",
        manifest_digest: "",
        platform: "",
      },
      fixed_count: 0,
      remaining_count: 0,
      introduced_count: 0,
      fixed_findings: [],
      remaining_findings: [],
      introduced_findings: [],
      message: "",
    },
    warnings: [],
    error_code: "",
    error_message: "",
    ...overrides,
    severity_counts: severityCounts,
  };
}

function securityFinding(
  index: number,
  severity: SecurityScanFinding["severity"] = "high",
  overrides: Partial<SecurityScanFinding> = {},
): SecurityScanFinding {
  const id = String(index).padStart(4, "0");
  return {
    vulnerability_id: `CVE-2026-${id}`,
    package_name: `package-${id}`,
    installed_version: "1.0.0",
    fixed_version: "1.0.1",
    severity,
    title: `${severity} vulnerability ${id}`,
    primary_url: "",
    ...overrides,
  };
}

function securityScanWithFindings(
  findings: SecurityScanFinding[],
): SecurityScanInfo {
  const severity_counts = {
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
    unknown: 0,
  };
  for (const finding of findings) {
    severity_counts[finding.severity] += 1;
  }
  return securityScanInfo({
    state: "complete",
    verdict: "findings",
    findings,
    severity_counts,
  });
}

function pendingPlanReviewModalProps(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    actionCommand: () => "docker compose pull app",
    applyButtonLabel: "Apply 1 update",
    applyDisabled: false,
    applyPreflight: null,
    applyPreflightAttentionChecks: [],
    applyPreflightCheckDetail: () => "",
    applyPreflightCheckLabel: () => "Ready",
    applyPreflightCheckType: () => "success",
    applyPreflightPassedChecks: [],
    applyPreflightPassedText: "",
    applyReadinessStatusLabel: "",
    applyReadinessStatusType: "success",
    applyReadinessSummary: "",
    applyVisible: false,
    cleanupAvailable: false,
    cleanupButtonLabel: "Remove 0 unmatched entries",
    cleanupDisabled: true,
    cleanupDisabledMessage: "",
    cleanupItems: [],
    cleanupReviewSummary: "",
    digestPinLabelApprovalApproved: () => false,
    digestPinLabelApprovalIssues: [],
    digestPinLabelIssueProposedRegex: () => "",
    issueDetailString: () => "",
    issueHint: () => "",
    issueLabel: () => "",
    issueType: () => "warning",
    loading: false,
    mutationDisabledMessage: "",
    plan: planResponse(),
    planActions: [],
    planAlertType: "info",
    planDigestPinLabelRewrites: [],
    planDigestUnpinUpdates: [],
    planLines: [],
    preflightDigestPinNotice: "",
    preflightDigestUnpinNotice: "",
    preflightServiceImpactLabel: "",
    preflightSummary: "1 service ready to update.",
    preflightTagRewriteNotice: "",
    preflightTitle: "Review selected updates",
    show: true,
    staleDiagnosticDetail: () => "",
    staleDiagnosticLabel: () => "",
    visiblePlanIssues: [],
    ...overrides,
  };
}

async function emitModalShowUpdate(wrapper: VueWrapper, value: boolean): Promise<void> {
  const modal = wrapper.getComponent(naiveStubs.NModal as Component);
  await modal.vm.$emit("update:show", value);
}

describe("pending helper modules", () => {
  it("formats digest provenance with tag context and truncated digest detail", () => {
    const digest = "sha256:abcdefghijklmnopqrstuvwxyz0123456789";
    const provenance = {
      source_image: "repo/app:stable",
      resolved_tag: "latest",
      watch_tag: "stable",
      target_digest: digest,
      final_image: `repo/app@${digest}`,
      provenance_source: "plan",
      provenance_confidence: "verified",
    };

    expect(displayDigest(digest)).toBe(
      "sha256:abcdefghijklm...yz0123456789",
    );
    expect(digestProvenanceDisplay(provenance)).toMatchObject({
      primary: "repo/app: stable -> latest",
      digest: "Digest: sha256:abcdefghijklm...yz0123456789",
    });
    expect(digestProvenanceDisplay(provenance)?.title).toContain(
      `Digest: ${digest}`,
    );
    expect(
      planLineDigestPinLabel({
        line_no: 1,
        raw: `repo/app:stable ${digest}`,
        image: "repo/app:stable",
        resolved_image: "repo/app:latest",
        compose_image: "repo/app@sha256:old",
        target_image: `repo/app@${digest}`,
        service: "app",
        digest,
        desired_tag: "",
        action: "digest-pin",
        digest_provenance: provenance,
      }),
    ).toBe(
      "repo/app: stable -> latest (Digest: sha256:abcdefghijklm...yz0123456789)",
    );

    expect(
      planLineDigestUnpinLabel({
        ...planResponse().stacks[0].lines[0],
        action: "digest-unpin",
        compose_image: `repo/app@${digest}`,
        target_image: "repo/app:latest",
      }),
    ).toBe(
      "repo/app@sha256:abcdefghijklmnopqrstuvwxyz0123456789 -> repo/app:latest",
    );
  });

  it("builds safety cues from versions, release notes, policies, and snoozes", () => {
    const major = pendingGroupedItem({
      line_no: 1,
      current_tag: "1.2.3",
      desired_tag: "2.0.0",
      services: ["app"],
    });
    const minor = pendingGroupedItem({
      line_no: 2,
      current_tag: "1.2.3",
      desired_tag: "1.3.0",
      services: ["worker"],
    });
    const patch = pendingGroupedItem({
      line_no: 3,
      current_tag: "1.2.3",
      desired_tag: "1.2.4",
      services: ["api"],
    });
    const digestLatest = pendingGroupedItem({
      line_no: 4,
      current_tag: "latest",
      desired_tag: "",
      digest: "sha256:abc",
      action: "recreate_stack",
      services: ["cache"],
    });
    const pending = pendingResponse([major, minor, patch, digestLatest]);
    const note = releaseNoteInfo({
      line_no: 1,
      breaking: true,
      breaking_reasons: ["Major version update."],
    });
    const noReleaseNote = releaseNoteInfo({
      line_no: 4,
      status: "unsupported",
      links: [],
      error: "no supported GitHub release source found",
    });

    const majorLabels = safetyCues(major, {
      pending,
      releaseNote: note,
      releaseNotesLoaded: true,
      releaseNotesLoading: false,
      securityScan: null,
      securityScansCurrent: false,
      securityScansEnabled: false,
      securityScansLoaded: false,
      securityScansLoading: false,
      servicePolicies: [servicePolicy({ service_key: "media/app", auto_update: true })],
      snoozes: [snooze({ service_key: "media/app" })],
    }).map((cue) => cue.label);
    expect(majorLabels).toContain("Major bump");
    expect(majorLabels).toContain("Possible breaking");
    expect(majorLabels).toContain("Snoozed");
    expect(majorLabels).toContain("Auto-update");

    expect(
      safetyCues(minor, {
        pending,
        releaseNote: null,
        releaseNotesLoaded: false,
        releaseNotesLoading: false,
        securityScan: null,
        securityScansCurrent: false,
        securityScansEnabled: false,
        securityScansLoaded: false,
        securityScansLoading: false,
        servicePolicies: [],
        snoozes: [],
      }).map((cue) => cue.label),
    ).toContain("Minor bump");
    expect(
      safetyCues(patch, {
        pending,
        releaseNote: null,
        releaseNotesLoaded: false,
        releaseNotesLoading: false,
        securityScan: null,
        securityScansCurrent: false,
        securityScansEnabled: false,
        securityScansLoaded: false,
        securityScansLoading: false,
        servicePolicies: [],
        snoozes: [],
      }).map((cue) => cue.label),
    ).toContain("Patch bump");

    const digestLabels = safetyCues(digestLatest, {
      pending,
      releaseNote: noReleaseNote,
      releaseNotesLoaded: true,
      releaseNotesLoading: false,
      securityScan: null,
      securityScansCurrent: false,
      securityScansEnabled: false,
      securityScansLoaded: false,
      securityScansLoading: false,
      servicePolicies: [],
      snoozes: [],
    }).map((cue) => cue.label);
    expect(digestLabels).toContain("Digest-only");
    expect(digestLabels).toContain("Mutable latest");
    expect(digestLabels).toContain("Stack restart");
    expect(digestLabels).toContain("No release notes");
  });

  it("adds candidate security scan cues without implying safety", () => {
    const item = pendingGroupedItem({ line_no: 3, image: "repo/app:1.0" });
    const pending = pendingResponse([item]);
    const securityCuesFor = (
      securityScan: SecurityScanInfo | null,
      overrides: Partial<Parameters<typeof safetyCues>[1]> = {},
    ) =>
      safetyCues(item, {
        pending,
        releaseNote: null,
        releaseNotesLoaded: false,
        releaseNotesLoading: false,
        securityScan,
        securityScansCurrent: true,
        securityScansEnabled: true,
        securityScansLoaded: true,
        securityScansLoading: false,
        servicePolicies: [],
        snoozes: [],
        ...overrides,
      }).filter((cue) => cue.key.startsWith("security-"));
    const completeFindingsScan = securityScanInfo({
      line_no: item.line_no,
      state: "complete",
      verdict: "findings",
      severity_counts: {
        critical: 0,
        high: 1,
        medium: 0,
        low: 0,
        unknown: 0,
      },
    });
    const completeLowerSeverityScan = securityScanInfo({
      line_no: item.line_no,
      state: "complete",
      verdict: "findings",
      severity_counts: {
        critical: 0,
        high: 0,
        medium: 2,
        low: 1,
        unknown: 1,
      },
    });
    const mixedComparisonScan = securityScanInfo({
      line_no: item.line_no,
      state: "complete",
      verdict: "findings",
      severity_counts: {
        critical: 0,
        high: 1,
        medium: 0,
        low: 0,
        unknown: 0,
      },
      comparison: {
        status: "mixed",
        current_subject: {
          requested_ref: "repo/app:1.0",
          reported_digest: "sha256:installed",
          manifest_digest: "sha256:installed-child",
          platform: "linux/amd64",
        },
        fixed_count: 1,
        remaining_count: 1,
        introduced_count: 1,
        fixed_findings: [securityFinding(1, "medium")],
        remaining_findings: [securityFinding(2, "high")],
        introduced_findings: [securityFinding(3, "high")],
        message: "1 finding fixed, 1 remains, and 1 introduced.",
      },
    });
    const noneReportedScan = securityScanInfo({
      line_no: item.line_no,
      state: "complete",
      verdict: "none_reported",
    });
    const notScannedScan = securityScanInfo({
      line_no: item.line_no,
      state: "not_scanned",
      verdict: "unknown",
    });
    const staleScan = securityScanInfo({
      line_no: item.line_no,
      state: "stale",
      verdict: "findings",
      severity_counts: {
        critical: 0,
        high: 0,
        medium: 1,
        low: 0,
        unknown: 0,
      },
    });
    const disabledScan = securityScanInfo({
      line_no: item.line_no,
      state: "disabled",
      verdict: "unknown",
    });

    expect(securityCuesFor(completeFindingsScan)).toContainEqual(
      expect.objectContaining({
        key: "security-findings",
        label: "Findings",
        type: "error",
      }),
    );
    expect(securityCuesFor(completeLowerSeverityScan)).toContainEqual(
      expect.objectContaining({
        key: "security-findings",
        label: "Findings",
        type: "warning",
      }),
    );
    expect(securityCuesFor(mixedComparisonScan)).toContainEqual(
      expect.objectContaining({
        key: "security-mixed",
        label: "Findings changed",
        type: "error",
      }),
    );
    expect(securityCuesFor(noneReportedScan)).toContainEqual(
      expect.objectContaining({
        key: "security-none-reported",
        label: "None reported",
        type: "success",
      }),
    );
    expect(securityCuesFor(noneReportedScan).map((cue) => cue.label)).not.toContain(
      "Safe",
    );
    expect(securityCuesFor(notScannedScan)).toContainEqual(
      expect.objectContaining({
        key: "security-not-scanned",
        label: "Not scanned",
        type: "default",
      }),
    );
    expect(securityCuesFor(staleScan)).toContainEqual(
      expect.objectContaining({
        key: "security-stale",
        label: "Scan stale",
        type: "warning",
      }),
    );
    expect(
      securityCuesFor(null, { securityScansCurrent: false }),
    ).toContainEqual(
      expect.objectContaining({
        key: "security-stale",
        label: "Scan stale",
        type: "warning",
      }),
    );
    expect(securityCuesFor(null)).toContainEqual(
      expect.objectContaining({
        key: "security-unknown",
        label: "Security unknown",
        type: "warning",
      }),
    );
    expect(securityCuesFor(disabledScan)).toEqual([]);
    expect(
      securityCuesFor(completeFindingsScan, { securityScansLoaded: false }),
    ).toEqual([]);
    expect(
      securityCuesFor(completeFindingsScan, { securityScansEnabled: false }),
    ).toEqual([]);
  });

  it("renders candidate security scan vulnerability rows", () => {
    const wrapper = mountPendingModal(PendingSecurityScanDetails, {
      scan: securityScanInfo({
        state: "complete",
        verdict: "findings",
        scanned_at: "2026-06-26T00:00:00+00:00",
        scanner_version: "0.71.2",
        severity_counts: {
          critical: 0,
          high: 1,
          medium: 0,
          low: 0,
          unknown: 0,
        },
        fixable_counts: {
          critical: 0,
          high: 1,
          medium: 0,
          low: 0,
          unknown: 0,
        },
        findings: [
          {
            vulnerability_id: "CVE-2026-0001",
            package_name: "openssl",
            installed_version: "1.0.0",
            fixed_version: "1.0.1",
            severity: "high",
            title: "demo vulnerability",
            primary_url: "https://avd.aquasec.com/nvd/cve-2026-0001",
          },
        ],
      }),
    });

    expect(wrapper.text()).toContain("1 finding");
    expect(wrapper.text()).toContain("1 High");
    expect(wrapper.text()).toContain("1 fixable finding");
    expect(wrapper.text()).toContain("CVE-2026-0001");
    expect(wrapper.text()).toContain("openssl");
    expect(wrapper.text()).toContain("1.0.0");
    expect(wrapper.text()).toContain("1.0.1");
    expect(wrapper.find("a").attributes("href")).toBe(
      "https://avd.aquasec.com/nvd/cve-2026-0001",
    );
  });

  it("renders security scan comparison deltas and report copy action", () => {
    const fixed = securityFinding(1, "medium", {
      package_name: "libssl",
    });
    const remaining = securityFinding(2, "high", {
      package_name: "openssl",
    });
    const introduced = securityFinding(3, "critical", {
      package_name: "curl",
    });
    const wrapper = mountPendingModal(PendingSecurityScanDetails, {
      scan: securityScanInfo({
        state: "complete",
        verdict: "findings",
        scanner_version: "0.71.2",
        scanner_schema: "trivy-json",
        db_revision: "trivy-db-2026-06-26",
        subject: {
          requested_ref: "repo/app:2.0",
          reported_digest: "sha256:candidate",
          manifest_digest: "sha256:candidate-child",
          platform: "linux/amd64",
        },
        severity_counts: {
          critical: 1,
          high: 1,
          medium: 0,
          low: 0,
          unknown: 0,
        },
        findings: [remaining, introduced],
        comparison: {
          status: "mixed",
          current_subject: {
            requested_ref: "repo/app:1.0",
            reported_digest: "sha256:installed",
            manifest_digest: "sha256:installed-child",
            platform: "linux/amd64",
          },
          fixed_count: 1,
          remaining_count: 1,
          introduced_count: 1,
          fixed_findings: [fixed],
          remaining_findings: [remaining],
          introduced_findings: [introduced],
          message: "1 finding fixed, 1 remains, and 1 introduced.",
        },
      }),
    });

    const text = wrapper.text();
    expect(text).toContain("Update comparison");
    expect(text).toContain("Mixed");
    expect(text).toContain("1 finding fixed, 1 remains, and 1 introduced.");
    expect(text).toContain("1 fixed finding");
    expect(text).toContain("1 remaining finding");
    expect(text).toContain("1 introduced finding");
    expect(text).toContain("Installed");
    expect(text).toContain("Candidate");
    expect(text).toContain("linux/amd64");
    expect(text).toContain("Copy report");
    expect(text).toContain("CVE-2026-0002");
    expect(text).toContain("CVE-2026-0003");
  });

  it("filters candidate security scan findings by present severity categories", async () => {
    const wrapper = mountPendingModal(PendingSecurityScanDetails, {
      scan: securityScanWithFindings([
        securityFinding(1, "critical"),
        securityFinding(2, "high"),
        securityFinding(3, "high"),
        securityFinding(4, "low"),
      ]),
    });

    const options = wrapper
      .find('select[aria-label="Security finding category filter"]')
      .findAll("option")
      .map((option) => option.text());

    expect(options).toEqual([
      "All categories (4)",
      "Critical (1)",
      "High (2)",
      "Low (1)",
    ]);
    expect(options).not.toContain("Medium (0)");
    expect(options).not.toContain("Unknown (0)");

    await wrapper
      .find('select[aria-label="Security finding category filter"]')
      .setValue("high");

    expect(wrapper.text()).toContain("CVE-2026-0002");
    expect(wrapper.text()).toContain("CVE-2026-0003");
    expect(wrapper.text()).not.toContain("CVE-2026-0001");
    expect(wrapper.text()).not.toContain("CVE-2026-0004");
  });

  it("clears stale security scan severity filters after scan refresh", async () => {
    const wrapper = mountPendingModal(PendingSecurityScanDetails, {
      scan: securityScanWithFindings([
        securityFinding(1, "critical"),
        securityFinding(2, "high"),
      ]),
    });

    await wrapper
      .find('select[aria-label="Security finding category filter"]')
      .setValue("critical");
    await wrapper.setProps({
      scan: securityScanWithFindings([securityFinding(3, "high")]),
    });

    expect(wrapper.text()).toContain("CVE-2026-0003");
    expect(wrapper.text()).not.toContain("CVE-2026-0001");
  });

  it("paginates candidate security scan findings", async () => {
    const wrapper = mountPendingModal(PendingSecurityScanDetails, {
      scan: securityScanWithFindings(
        Array.from({ length: 12 }, (_, index) => securityFinding(index + 1)),
      ),
    });

    expect(wrapper.text()).toContain("Showing 1-10 of 12 findings");
    expect(wrapper.text()).toContain("CVE-2026-0001");
    expect(wrapper.text()).toContain("CVE-2026-0010");
    expect(wrapper.text()).not.toContain("CVE-2026-0011");

    const pageTwo = wrapper.findAll("button").find((button) => button.text() === "2");
    expect(pageTwo).toBeTruthy();
    await pageTwo?.trigger("click");

    expect(wrapper.text()).toContain("Showing 11-12 of 12 findings");
    expect(wrapper.text()).not.toContain("CVE-2026-0001");
    expect(wrapper.text()).toContain("CVE-2026-0011");
    expect(wrapper.text()).toContain("CVE-2026-0012");

    await wrapper.setProps({
      scan: securityScanWithFindings(
        Array.from({ length: 11 }, (_, index) => securityFinding(index + 101)),
      ),
    });

    expect(wrapper.text()).toContain("Showing 1-10 of 11 findings");
    expect(wrapper.text()).toContain("CVE-2026-0101");
    expect(wrapper.text()).toContain("CVE-2026-0110");
    expect(wrapper.text()).not.toContain("CVE-2026-0111");

    const pageOne = wrapper.findAll("button").find((button) => button.text() === "1");
    expect(pageOne?.attributes("disabled")).toBeDefined();
  });

  it("summarizes candidate security scans with shared severity semantics", () => {
    const highImpactScan = securityScanInfo({
      line_no: 1,
      state: "complete",
      verdict: "findings",
      severity_counts: {
        critical: 0,
        high: 1,
        medium: 0,
        low: 0,
        unknown: 0,
      },
    });
    const lowerSeverityScan = securityScanInfo({
      line_no: 2,
      state: "complete",
      verdict: "findings",
      severity_counts: {
        critical: 0,
        high: 0,
        medium: 1,
        low: 0,
        unknown: 0,
      },
    });
    const cleanScan = securityScanInfo({
      line_no: 3,
      state: "complete",
      verdict: "none_reported",
    });
    const staleScan = securityScanInfo({
      line_no: 4,
      state: "stale",
      verdict: "findings",
    });

    expect(
      securityScanSummaryDisplay({
        securityScans: null,
        securityScansCurrent: false,
        items: [],
      }),
    ).toEqual({ label: "Security scans loading", type: "default" });
    expect(
      securityScanSummaryDisplay({
        securityScans: { scanning_enabled: false },
        securityScansCurrent: false,
        items: [],
      }),
    ).toEqual({ label: "Security scans off", type: "default" });
    expect(
      securityScanSummaryDisplay({
        securityScans: { scanning_enabled: true },
        securityScansCurrent: false,
        items: [highImpactScan],
      }),
    ).toEqual({ label: "Security scans stale", type: "warning" });
    expect(
      securityScanSummaryDisplay({
        securityScans: { scanning_enabled: true },
        securityScansCurrent: true,
        items: [highImpactScan],
      }),
    ).toEqual({ label: "1 candidate with findings", type: "error" });
    expect(
      securityScanSummaryDisplay({
        securityScans: { scanning_enabled: true },
        securityScansCurrent: true,
        items: [staleScan],
      }),
    ).toEqual({ label: "Security scans stale", type: "warning" });
    expect(
      securityScanSummaryDisplay({
        securityScans: { scanning_enabled: true },
        securityScansCurrent: true,
        items: [lowerSeverityScan],
      }),
    ).toEqual({ label: "1 candidate with findings", type: "warning" });
    expect(
      securityScanSummaryDisplay({
        securityScans: { scanning_enabled: true },
        securityScansCurrent: true,
        items: [highImpactScan, lowerSeverityScan],
      }),
    ).toEqual({ label: "2 candidates with findings", type: "error" });
    expect(
      securityScanSummaryDisplay({
        securityScans: { scanning_enabled: true },
        securityScansCurrent: true,
        items: [cleanScan],
      }),
    ).toEqual({ label: "1 candidate scanned", type: "info" });
    expect(
      securityScanSummaryDisplay({
        securityScans: { scanning_enabled: true },
        securityScansCurrent: true,
        items: [],
      }),
    ).toEqual({ label: "No candidate scans yet", type: "info" });
  });

  it("formats pending queue display helpers without store dependencies", () => {
    const item = pendingGroupedItem({
      image: "repo/app:1.0",
      target_image: "repo/app:2.0",
      resolved_image: "repo/app:2.0",
      services: ["app"],
      action: "tag-update",
    });
    const breakingNote = releaseNoteInfo({
      line_no: item.line_no,
      breaking: true,
      breaking_reasons: ["Major version update."],
    });

    expect(uniqueSorted([3, 1, 3, 2])).toEqual([1, 2, 3]);
    expect(uniqueStrings(["worker", "", "api", "worker"])).toEqual([
      "api",
      "worker",
    ]);
    expect(pendingSourceFileName("/out/images.todo")).toBe("images.todo");
    expect(groupedItemServiceKeys({ name: "media" }, item)).toEqual([
      "media/app",
    ]);
    expect(groupedItemTarget(item)).toBe("repo/app:2.0");
    expect(groupedItemActionLabel(item)).toBe("Tag update");
    expect(groupedItemActionTagType(item)).toBe("warning");
    expect(itemsBreakingCount([item], () => breakingNote)).toBe(1);
    expect(tagInputProps(item)).toEqual({ "aria-label": "New tag for repo/app:1.0" });
    expect(
      releaseNoteReason(releaseNoteInfo({
        links: [],
        error: "missing LSIO upstream mapping for linuxserver/radarr",
      })),
    ).toBe(
      "Add a LinuxServer.io upstream map entry for linuxserver/radarr.",
    );
    expect(
      releaseNoteStatus(
        releaseNoteInfo({ links: [], status: "error" }),
        false,
      ),
    ).toBe("Check failed");
  });

  it("matches pending search fields from items, groups, safety cues, diagnostics, and release notes", () => {
    const app = pendingGroupedItem({
      line_no: 7,
      raw: "repo/app:latest sha256=feedface",
      image: "repo/app:latest",
      repo: "repo/app",
      key: "repo/app",
      current_tag: "latest",
      desired_tag: "",
      digest: "sha256:feedface",
      services: ["worker"],
      action: "digest-pin",
      diagnostic: {
        code: "compose-label-active-file-missing",
        message: "Container worker was created from stack media.",
        hint: "Restore docker-compose.archive.yml before applying.",
        stack: "media",
        service: "worker",
        compose_file: "docker-compose.yml",
        found_files: ["docker-compose.archive.yml"],
        details: {
          preflight_findings: ["Docker labels reference docker-compose.yml."],
        },
      },
    });
    const db = pendingGroupedItem({
      line_no: 8,
      image: "postgres:16",
      repo: "postgres",
      services: ["db"],
    });
    const group = {
      name: "media",
      directory: "/docker/media",
      compose_file: "docker-compose.yml",
      project_directory: "/docker/media",
      services_label: "worker, db",
      services: ["worker", "db"],
      line_numbers: [7, 8],
      items: [app, db],
    };
    const note = releaseNoteInfo({
      line_no: 7,
      links: [],
      status: "unsupported",
      error: "no supported GitHub release source found",
    });
    const context = {
      releaseChangelogFor: () => ({
        status: "ready" as const,
        body: "Server-Sent Events replace WebSocket live updates.",
        sourceUrl: "https://raw.githubusercontent.com/t-mart/mousehole/master/CHANGELOG.md",
        error: "",
      }),
      releaseNoteFor: () => note,
      releaseNoteReason,
      releaseNoteStatus: (value: typeof note | null) =>
        releaseNoteStatus(value, false),
      riskCues: () => [
        { key: "mutable-latest", label: "Mutable latest", type: "warning" as const },
      ],
    };

    expect(normalizePendingSearch("  Mutable   Latest ")).toBe("mutable latest");
    expect(pendingItemMatchesSearch(app, "digest pin", context)).toBe(true);
    expect(pendingItemMatchesSearch(app, "feedface", context)).toBe(true);
    expect(pendingItemMatchesSearch(app, "docker-compose.archive", context)).toBe(true);
    expect(pendingItemMatchesSearch(app, "Only GHCR", context)).toBe(true);
    expect(pendingItemMatchesSearch(app, "server-sent events", context)).toBe(true);
    expect(pendingItemMatchesSearch(app, "mutable latest", context)).toBe(true);

    const itemMatchedGroups = filterPendingStackGroups([group], "worker", context);
    expect(itemMatchedGroups).toHaveLength(1);
    expect(itemMatchedGroups[0].items).toEqual([app]);
    expect(itemMatchedGroups[0].visibleLineNumbers).toEqual([7]);
    expect(itemMatchedGroups[0].line_numbers).toEqual([7, 8]);

    const groupMatchedGroups = filterPendingStackGroups(
      [group],
      "docker/media",
      context,
    );
    expect(groupMatchedGroups[0].items).toEqual([app, db]);
    expect(groupMatchedGroups[0].visibleLineNumbers).toEqual([7, 8]);
  });

  it("matches diagnostic details without recursing through circular references", () => {
    const detailNode: Record<string, unknown> = {
      finding: "Circular diagnostic marker",
    };
    detailNode.self = detailNode;
    const item = pendingGroupedItem({
      diagnostic: {
        code: "compose-label-active-file-missing",
        message: "Container worker was created from stack media.",
        hint: "Restore docker-compose.yml before applying.",
        stack: "media",
        service: "worker",
        compose_file: "docker-compose.yml",
        found_files: [],
        details: {
          nested: detailNode,
          again: detailNode,
        },
      },
    });
    const context: PendingSearchContext = {
      releaseChangelogFor: () => null,
      releaseNoteFor: () => null,
      releaseNoteReason,
      releaseNoteStatus: (value) => releaseNoteStatus(value, false),
      riskCues: () => [],
    };

    expect(pendingItemMatchesSearch(item, "circular diagnostic", context)).toBe(
      true,
    );
  });

  it("creates fallback table renderers for tags, digests, safety, and release notes", async () => {
    const item = pendingGroupedItem({
      line_no: 1,
      image: "repo/app:1.0",
      repo: "repo/app",
      desired_tag: "2.0.0",
      digest: "sha256:abcdefghijklmnopqrstuvwxyz0123456789",
    });
    const updateTagOverride = vi.fn();
    const columns = createPendingColumns({
      displayDigest: () => "sha256:abcdef...789",
      displayValue: (value) => value || "None",
      releaseNoteFor: () =>
        releaseNoteInfo({
          breaking: true,
          breaking_reasons: ["Major version update."],
        }),
      releaseNoteReason: () => "",
      releaseNoteStatus: () => "",
      riskCues: () => [{ key: "major-bump", label: "Major bump", type: "error" }],
      tagInputProps: (row) => ({ "aria-label": `New tag for ${row.image}` }),
      tagOverrideValue: () => "2.0.0",
      updateTagOverride,
    });

    const renderColumn = (key: string) => {
      const column = columns.find((item) => (item as RenderColumn).key === key) as
        | RenderColumn
        | undefined;
      return column?.render?.(item) ?? null;
    };
    const TestRenderer = defineComponent({
      setup() {
        return () =>
          h("div", [
            renderColumn("desired_tag"),
            renderColumn("digest"),
            renderColumn("safety_cues"),
            renderColumn("release_notes"),
          ]);
      },
    });

    const wrapper = mountWithApp(TestRenderer);
    expect(wrapper.find("input").attributes("aria-label")).toBe(
      "New tag for repo/app:1.0",
    );
    await wrapper.find("input").setValue("2.1.0");
    expect(updateTagOverride).toHaveBeenCalledWith(item, "2.1.0");
    expect(wrapper.text()).toContain("sha256:abcdef...789");
    expect(wrapper.text()).toContain("Major bump");
    expect(wrapper.text()).toContain("GitHub release");
    expect(wrapper.text()).toContain("Possible breaking change");
    expect(wrapper.find(".release-note-link").attributes("rel")).toBe(
      "noopener noreferrer",
    );
  });

  it("renders digest provenance ahead of raw digest values in pending tables", () => {
    const digest = "sha256:abcdefghijklmnopqrstuvwxyz0123456789";
    const item = pendingGroupedItem({
      line_no: 1,
      image: "repo/app:latest",
      repo: "repo/app",
      desired_tag: "",
      digest,
      digest_provenance: {
        source_image: "repo/app:latest",
        resolved_tag: "latest",
        watch_tag: "latest",
        target_digest: digest,
        final_image: `repo/app@${digest}`,
        provenance_source: "compose",
        provenance_confidence: "recovered",
      },
    });
    const columns = createPendingColumns({
      displayDigest: () => "raw digest fallback",
      displayValue: (value) => value || "None",
      releaseNoteFor: () => null,
      releaseNoteReason: () => "",
      releaseNoteStatus: () => "Not checked",
      riskCues: () => [],
      tagInputProps: (row) => ({ "aria-label": `New tag for ${row.image}` }),
      tagOverrideValue: () => "",
      updateTagOverride: vi.fn(),
    });
    const digestColumn = columns.find((column) => {
      return (column as RenderColumn).key === "digest";
    }) as RenderColumn | undefined;
    const TestRenderer = defineComponent({
      setup() {
        return () => h("div", [digestColumn?.render?.(item) ?? null]);
      },
    });

    const wrapper = mountWithApp(TestRenderer);
    expect(wrapper.text()).toContain("repo/app: latest -> latest");
    expect(wrapper.text()).toContain(
      "Digest: sha256:abcdefghijklm...yz0123456789",
    );
    expect(wrapper.text()).not.toContain("raw digest fallback");
    expect(wrapper.find(".digest-provenance").attributes("title")).toContain(
      `Digest: ${digest}`,
    );
  });

  it("forwards pending modal update-close events to the owning view", async () => {
    const modalCases = [
      {
        component: PendingPlanReviewModal,
        props: pendingPlanReviewModalProps(),
      },
      {
        component: PendingCleanupModal,
        props: {
          assistantActions: [],
          assistantFindings: [],
          assistantReasons: [],
          cleanupButtonLabel: "Remove 0 unmatched entries",
          cleanupDisabled: true,
          cleanupItems: [],
          cleanupLineLabel: () => "#1",
          loading: false,
          pendingSourceLabel: "images.todo",
          show: true,
        },
      },
      {
        component: PendingRemovalModal,
        props: {
          loading: false,
          pendingSourceLabel: "images.todo",
          removalConfirmButtonLabel: "Remove 0 selected entries",
          removalDisabled: true,
          removalItems: [],
          removalLineLabel: () => "#1",
          show: true,
        },
      },
    ];

    for (const { component, props } of modalCases) {
      const wrapper = mountPendingModal(component, props);

      await emitModalShowUpdate(wrapper, true);
      expect(wrapper.emitted("close")).toBeUndefined();

      await emitModalShowUpdate(wrapper, false);
      expect(wrapper.emitted("close")).toHaveLength(1);
    }
  });

  it("renders digest-unpin notices and plan line labels", () => {
    const plan = planResponse();
    const line = {
      ...plan.stacks[0].lines[0],
      action: "digest-unpin" as const,
      compose_image: "repo/app@sha256:old",
      target_image: "repo/app:latest",
    };
    const update = {
      source_image: "repo/app@sha256:old",
      resolved_tag: "latest",
      tag_image: "repo/app:latest",
      current_digest: "sha256:old",
      target_digest: "sha256:new",
      watch_tag: "latest",
      marker: "wudup.resolved-tag=latest",
      label_key: "wud.tag.include",
      label_value: "^latest$$",
      services: ["app"],
    };
    const wrapper = mountPendingModal(
      PendingPlanReviewModal,
      pendingPlanReviewModalProps({
        plan: {
          ...plan,
          status: "blocked",
          stacks: [{ ...plan.stacks[0], lines: [line] }],
        },
        planDigestUnpinUpdates: [{ stack: "media", update }],
        planLines: [{ stack: "media", line }],
        preflightDigestUnpinNotice:
          "1 digest unpin migration will rewrite pinned Compose images back to their watched tag before pulling.",
      }),
    );

    expect(wrapper.text()).toContain("Digest unpin migration");
    expect(wrapper.text()).toContain("1 digest unpin migration");
    expect(wrapper.text()).toContain("repo/app@sha256:old");
    expect(wrapper.text()).toContain("repo/app:latest");
    expect(wrapper.text()).toContain("Digest unpin");
  });
});

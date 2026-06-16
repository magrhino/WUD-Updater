import { mount, type VueWrapper } from "@vue/test-utils";
import { defineComponent, h, type Component, type VNodeChild } from "vue";
import { describe, expect, it, vi } from "vitest";

import type { PendingItem } from "../src/api/client";
import PendingCleanupModal from "../src/components/pending/PendingCleanupModal.vue";
import PendingPlanReviewModal from "../src/components/pending/PendingPlanReviewModal.vue";
import PendingRemovalModal from "../src/components/pending/PendingRemovalModal.vue";
import {
  digestProvenanceDisplay,
  displayDigest,
} from "../src/utils/digestProvenance";
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
} from "../src/views/pending/pendingDisplay";
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
        servicePolicies: [],
        snoozes: [],
      }).map((cue) => cue.label),
    ).toContain("Patch bump");

    const digestLabels = safetyCues(digestLatest, {
      pending,
      releaseNote: noReleaseNote,
      releaseNotesLoaded: true,
      releaseNotesLoading: false,
      servicePolicies: [],
      snoozes: [],
    }).map((cue) => cue.label);
    expect(digestLabels).toContain("Digest-only");
    expect(digestLabels).toContain("Mutable latest");
    expect(digestLabels).toContain("Stack restart");
    expect(digestLabels).toContain("No release notes");
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
      marker: "wud-updater.resolved-tag=latest",
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

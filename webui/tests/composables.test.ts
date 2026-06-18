import { createPinia, setActivePinia } from "pinia";
import { computed, ref } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises } from "@vue/test-utils";

import type { ApplyJobProgressEvent, PlanIssue } from "../src/api/client";
import { useUpdateTargetOptions } from "../src/composables/useUpdateTargetOptions";
import { useAuthStore } from "../src/stores/auth";
import { useRunsStore } from "../src/stores/runs";
import { useSettingsStore } from "../src/stores/settings";
import { useUpdatesStore } from "../src/stores/updates";
import {
  applyJobLogResponse,
  applyJobResponse,
  applyPreflightResponse,
  authSession,
  pendingGroupedItem,
  pendingItem,
  pendingResponse,
  planResponse,
  snooze,
  updateTarget,
  updateTargetsResponse,
} from "./helpers/fixtures";
import {
  usePendingApplyJob,
  type PendingApplyJobPanelRef,
} from "../src/views/pending/usePendingApplyJob";
import {
  usePendingPlanReviewState,
} from "../src/views/pending/usePendingPlanReviewState";
import { usePendingQueueState } from "../src/views/pending/usePendingQueueState";
import { usePendingSelectionState } from "../src/views/pending/usePendingSelectionState";
import { mockApplyJobStream } from "./helpers/applyJobStream";

describe("useUpdateTargetOptions", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("returns empty options when update targets have not loaded", () => {
    const options = useUpdateTargetOptions();

    expect(options.targets.value).toEqual([]);
    expect(options.serviceKeyOptions.value).toEqual([]);
    expect(options.imageRepoOptions.value).toEqual([]);
    expect(options.tagOptionsForImageRepo("repo/app")).toEqual([]);
  });

  it("derives sorted, de-duplicated service and image options from the updates store", () => {
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([
      updateTarget({
        service_key: "media/sonarr",
        image_repo: "repo/sonarr",
        current_tag: "4.0",
      }),
      updateTarget({
        service_key: "media/radarr",
        image_repo: "repo/radarr",
        current_tag: "5.0",
      }),
      updateTarget({
        service_key: "media/sonarr",
        image_repo: "repo/sonarr",
        current_tag: "4.1",
      }),
      updateTarget({
        service_key: "",
        image_repo: "",
        current_tag: "ignored",
      }),
    ]);
    const options = useUpdateTargetOptions();

    expect(options.serviceKeyOptions.value).toEqual([
      { label: "media/radarr", value: "media/radarr" },
      { label: "media/sonarr", value: "media/sonarr" },
    ]);
    expect(options.imageRepoOptions.value).toEqual([
      { label: "repo/radarr", value: "repo/radarr" },
      { label: "repo/sonarr", value: "repo/sonarr" },
    ]);
  });

  it("finds targets and tag options by service key and image repository", () => {
    const updates = useUpdatesStore();
    updates.updateTargets = updateTargetsResponse([
      updateTarget({
        service_key: "media/radarr",
        image_repo: "repo/radarr",
        current_tag: "5.0",
      }),
      updateTarget({
        service_key: "media/sonarr",
        image_repo: "repo/sonarr",
        current_tag: "4.0",
      }),
      updateTarget({
        service_key: "media/sonarr-beta",
        image_repo: "repo/sonarr",
        current_tag: "  ",
      }),
      updateTarget({
        service_key: "media/sonarr-nightly",
        image_repo: "repo/sonarr",
        current_tag: "4.0",
      }),
    ]);
    const options = useUpdateTargetOptions();

    expect(options.targetForServiceKey("media/radarr")?.image_repo).toBe(
      "repo/radarr",
    );
    expect(options.targetForImageRepo("repo/sonarr")?.service_key).toBe(
      "media/sonarr",
    );
    expect(options.tagOptionsForImageRepo("repo/sonarr")).toEqual([
      { label: "4.0", value: "4.0" },
    ]);
    expect(options.tagOptionsForImageRepo("repo/missing")).toEqual([]);
  });
});

function failedApplyPreflight(code: string, detail: string) {
  const base = applyPreflightResponse();
  return applyPreflightResponse({
    ok: false,
    failures: 1,
    checks: base.checks.map((check) =>
      check.code === code
        ? {
            ...check,
            status: "FAIL" as const,
            detail,
          }
        : check,
    ),
  });
}

function warningApplyPreflight(code: string, detail: string) {
  const base = applyPreflightResponse();
  return applyPreflightResponse({
    warnings: 1,
    checks: base.checks.map((check) =>
      check.code === code
        ? {
            ...check,
            status: "WARN" as const,
            detail,
          }
        : check,
    ),
  });
}

function setupPendingPlanReview(mutationsEnabled = true) {
  const auth = useAuthStore();
  auth.session = authSession({ mutations_enabled: mutationsEnabled });
  const updates = useUpdatesStore();
  const selectedLineNumbers = ref<number[]>([]);
  const selectedLineSet = computed(() => new Set(selectedLineNumbers.value));
  const stackGroups = computed(() => updates.pending?.grouping.groups ?? []);
  const unmatchedItems = computed(() => updates.pending?.grouping.unmatched ?? []);
  const pendingSourceLabel = computed(() => "images.todo");
  const tagOverrideErrorForLines = vi.fn(() => "");
  const state = usePendingPlanReviewState({
    pendingSourceLabel,
    selectedLineNumbers,
    selectedLineSet,
    stackGroups,
    tagOverrideErrorForLines,
    unmatchedItems,
  });

  return {
    state,
    updates,
    selectedLineNumbers,
    selectedLineSet,
    tagOverrideErrorForLines,
  };
}

function setupPendingApplyJob() {
  const updates = useUpdatesStore();
  const runs = useRunsStore();
  const panelRef = ref<PendingApplyJobPanelRef | null>({
    focusPanel: vi.fn(),
    logElement: () => null,
  });
  const loadPendingAndReleaseNotes = vi.fn().mockResolvedValue(undefined);
  const state = usePendingApplyJob({
    applyJobPanelRef: panelRef,
    loadPendingAndReleaseNotes,
  });

  return {
    state,
    updates,
    runs,
    loadPendingAndReleaseNotes,
  };
}

function digestPinApprovalIssue(
  overrides: Partial<PlanIssue> = {},
): PlanIssue {
  return {
    severity: "error",
    code: "compose-digest-pin-label-rewrite-unapproved",
    message: "Digest-pin label rewrite must be approved.",
    line_no: 1,
    stack: "media",
    service: "app",
    hint: "",
    details: {
      stack: "media",
      service: "app",
      label_key: "org.opencontainers.image.version",
      current_label_value: "1.0",
      planned_tag: "1.1",
      proposed_label_value: "1.1",
    },
    ...overrides,
  };
}

describe("usePendingQueueState", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("filters snoozed entries out of selectable stack groups", () => {
    const updates = useUpdatesStore();
    const settings = useSettingsStore();
    const blocked = pendingGroupedItem({
      line_no: 1,
      image: "repo/app:1.0",
      services: ["app"],
    });
    const allowed = pendingGroupedItem({
      line_no: 2,
      image: "repo/worker:1.0",
      repo: "repo/worker",
      services: ["worker"],
    });
    updates.pending = pendingResponse([blocked, allowed]);
    settings.snoozes = [
      snooze({
        kind: "time",
        service_key: "media/app",
        active: true,
      }),
    ];

    const state = usePendingQueueState();

    expect(state.snoozedItems.value.map(({ item }) => item.line_no)).toEqual([1]);
    expect(state.stackGroups.value).toHaveLength(1);
    expect(state.stackGroups.value[0]?.items.map((item) => item.line_no)).toEqual([2]);
    expect(state.selectableLineNumbers.value).toEqual([2]);
    expect(state.pendingSourceLabel.value).toBe("images.todo");
  });

  it("treats whitespace-only pending source files as empty", () => {
    const updates = useUpdatesStore();
    updates.pending = { ...pendingResponse([]), source_file: "   " };

    const state = usePendingQueueState();

    expect(state.pendingSourceLabel.value).toBe("Pending file");
    expect(state.pendingSourceDisplay.value).toBe("Pending file");
  });
});

describe("usePendingSelectionState", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("syncs tag overrides with pending items and builds apply payloads", () => {
    const updates = useUpdatesStore();
    const onSelectionChanged = vi.fn();
    updates.pending = pendingResponse([
      pendingItem({
        line_no: 1,
        image: "repo/app:1.0",
        desired_tag: "1.1",
      }),
      pendingItem({
        line_no: 2,
        image: "repo/worker:1.0",
        repo: "repo/worker",
        desired_tag: "",
      }),
    ]);
    const state = usePendingSelectionState({
      pendingItems: computed(() => updates.pending?.items ?? []),
      selectableLineNumbers: computed(() => [1, 2]),
      onSelectionChanged,
    });

    const item = updates.pending.items[0];
    expect(state.tagOverridesForLines([1])).toEqual([]);

    state.updateTagOverride(item, "bad tag");
    expect(state.selectedLineNumbers.value).toEqual([1]);
    expect(state.tagOverrideErrorForLines([1])).toContain("invalid new tag");

    state.updateTagOverride(item, "1.2");
    expect(state.tagOverridesForLines([1])).toEqual([{ line_no: 1, tag: "1.2" }]);
    expect(state.lineNumbersHaveTagUpdates([1, 2])).toBe(true);

    state.selectAllVisible();
    expect(state.selectedLineNumbers.value).toEqual([1, 2]);
    state.updateCheckedRowKeys([2, 2, "bad-key"]);
    expect(state.selectedLineNumbers.value).toEqual([2]);
    expect(onSelectionChanged).toHaveBeenCalled();
  });

  it("clears stale tag overrides when pending items reload", async () => {
    const updates = useUpdatesStore();
    updates.pending = pendingResponse([
      pendingItem({
        line_no: 1,
        image: "repo/app:1.0",
        desired_tag: "1.1",
      }),
    ]);
    const state = usePendingSelectionState({
      pendingItems: computed(() => updates.pending?.items ?? []),
      selectableLineNumbers: computed(() => [1]),
    });

    state.updateTagOverride(updates.pending.items[0], "1.2");
    expect(state.tagOverridesForLines([1])).toEqual([
      { line_no: 1, tag: "1.2" },
    ]);

    updates.pending = pendingResponse([
      pendingItem({
        line_no: 1,
        image: "repo/app:1.0",
        desired_tag: "1.1",
      }),
    ]);
    await flushPromises();
    expect(state.tagOverridesForLines([1])).toEqual([
      { line_no: 1, tag: "1.2" },
    ]);

    updates.pending = pendingResponse([
      pendingItem({
        line_no: 1,
        image: "repo/app:2.0",
        desired_tag: "2.1",
      }),
    ]);
    await flushPromises();

    expect(state.tagOverrideValue(updates.pending.items[0])).toBe("2.1");
    expect(state.tagOverridesForLines([1])).toEqual([]);
  });
});

describe("usePendingPlanReviewState", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("owns update intent labels and apply payloads", () => {
    const { state } = setupPendingPlanReview();
    const tagOverrides = [{ line_no: 1, tag: "1.2" }];

    state.setUpdateIntent({
      title: "Preview media plan",
      contextLabel: "media",
      lineNumbers: [1],
      allowTagUpdates: true,
      tagOverrides,
      digestPinLabelRewriteApprovals: [],
    });

    expect(state.planContextLabel.value).toBe("media");
    expect(state.preflightTitle.value).toBe("Preview media plan");
    expect(
      state.applyPlanPayload({
        allowTagUpdates: false,
        tagOverrides: [],
      }),
    ).toEqual({
      allowTagUpdates: true,
      tagOverrides,
      digestPinLabelRewriteApprovals: [],
    });

    state.clearUpdateIntent();

    expect(state.planContextLabel.value).toBe("selected updates");
    expect(
      state.applyPlanPayload({
        allowTagUpdates: false,
        tagOverrides: [],
      }),
    ).toEqual({
      allowTagUpdates: false,
      tagOverrides: [],
      digestPinLabelRewriteApprovals: [],
    });
  });

  it("disables selected updates when reactive tag validation changes", () => {
    const auth = useAuthStore();
    auth.session = authSession({ mutations_enabled: true });
    const updates = useUpdatesStore();
    const selectedLineNumbers = ref<number[]>([1]);
    const selectedLineSet = computed(() => new Set(selectedLineNumbers.value));
    const tagValidationError = ref("");
    const state = usePendingPlanReviewState({
      pendingSourceLabel: computed(() => "images.todo"),
      selectedLineNumbers,
      selectedLineSet,
      stackGroups: computed(() => updates.pending?.grouping.groups ?? []),
      tagOverrideErrorForLines: () => tagValidationError.value,
      unmatchedItems: computed(() => updates.pending?.grouping.unmatched ?? []),
    });

    expect(state.updateSelectedDisabled.value).toBe(false);

    tagValidationError.value = "repo/app:1.0 has an invalid new tag.";
    expect(state.updateSelectedDisabled.value).toBe(true);

    tagValidationError.value = "";
    updates.loading = true;
    expect(state.updateSelectedDisabled.value).toBe(true);
  });

  it("derives apply readiness states from the current plan preflight", () => {
    const { state, updates } = setupPendingPlanReview();

    expect(state.applyReadinessStatusLabel.value).toBe("");
    expect(state.applyReadinessStatusType.value).toBe("error");
    expect(state.applyVisible.value).toBe(false);

    updates.plan = planResponse();

    expect(state.applyReadinessStatusLabel.value).toBe("Ready");
    expect(state.applyReadinessStatusType.value).toBe("success");
    expect(state.applyReadinessSummary.value).toBe("Required resources are reachable.");
    expect(state.applyButtonLabel.value).toBe("Apply 1 update");

    updates.plan = planResponse({
      apply_preflight: warningApplyPreflight(
        "bind-mounts-safe",
        "One bind mount should be reviewed.",
      ),
    });

    expect(state.applyReadinessStatusLabel.value).toBe("Warnings");
    expect(state.applyReadinessStatusType.value).toBe("warning");
    expect(state.applyPreflightAttentionChecks.value).toHaveLength(1);
    expect(state.applyReadinessSummary.value).toBe(
      "1 warning to review before applying.",
    );

    updates.plan = planResponse({
      can_apply: false,
      apply_preflight: failedApplyPreflight(
        "mutations-enabled",
        "Set WUD_WEB_MUTATIONS_ENABLED=true.",
      ),
    });

    expect(state.applyReadinessStatusLabel.value).toBe("Blocked");
    expect(state.applyReadinessStatusType.value).toBe("error");
    expect(state.applyDisabled.value).toBe(true);
    expect(state.applyReadinessSummary.value).toBe(
      "1 failed check must be fixed before applying.",
    );
  });

  it("derives cleanup and removal state without exposing stale cleanup issues", () => {
    const { state, updates, selectedLineNumbers } = setupPendingPlanReview(false);
    const item = pendingGroupedItem({
      line_no: 1,
      image: "repo/old:latest",
      repo: "repo/old",
      services: [],
      diagnostic: {
        code: "compose-label-active-file-missing",
        message:
          "Container old was created from stack media, but docker-compose.yml is missing.",
        hint: "Restore an active Compose file or remove the stale pending line.",
        stack: "media",
        service: "old",
        compose_file: "docker-compose.yml",
        found_files: ["docker-compose.archive.yml"],
        details: {
          preflight_findings: [
            "Compose file missing",
            "Archived file found",
            "Compose file missing",
          ],
          possible_reasons: ["Stack moved", "Stack moved"],
          recommended_actions: [
            "Restore Compose file",
            "Remove stale line",
            "Restore Compose file",
          ],
        },
      },
    });
    selectedLineNumbers.value = [1];
    updates.plan = planResponse({
      can_apply: false,
      issues: [
        {
          severity: "error",
          code: "compose-label-active-file-missing",
          message: "No Compose service matched repo/old:latest.",
          line_no: 1,
          stack: "",
          service: "",
          hint: "",
          details: {},
        },
      ],
      cleanup: {
        cleanup_id: "cleanup-test",
        can_remove_unmatched: false,
        items: [
          {
            line_no: item.line_no,
            raw: item.raw,
            image: item.image,
            desired_tag: item.desired_tag,
            digest: item.digest,
            reason: "compose-label-active-file-missing",
            diagnostic: item.diagnostic,
          },
        ],
      },
    });

    expect(state.cleanupButtonLabel.value).toBe("Remove 1 unmatched entry");
    expect(state.cleanupDisabled.value).toBe(true);
    expect(state.cleanupDisabledMessage.value).toContain("Read-only mode is active");
    expect(state.removeSelectedDisabled.value).toBe(true);
    expect(state.removeSelectedDisabledMessage.value).toContain(
      "Read-only mode is active",
    );
    expect(state.removalButtonLabel.value).toBe("Remove 1 selected entry");
    expect(state.cleanupReviewSummary.value).toContain(
      "1 entry needs review: Compose file missing.",
    );
    expect(state.cleanupAssistantFindings.value).toEqual([
      "Compose file missing",
      "Archived file found",
    ]);
    expect(state.cleanupAssistantReasons.value).toEqual(["Stack moved"]);
    expect(state.cleanupAssistantActions.value).toEqual([
      "Restore Compose file",
      "Remove stale line",
    ]);
    expect(state.visiblePlanIssues.value).toEqual([]);
  });

  it("keeps global plan issues visible when cleanup hides line-level stale issues", () => {
    const { state, updates } = setupPendingPlanReview();

    updates.plan = planResponse({
      issues: [
        {
          severity: "error",
          code: "compose-label-active-file-missing",
          message: "Global compose discovery issue.",
          line_no: null,
          stack: "",
          service: "",
          hint: "",
          details: {},
        },
        {
          severity: "error",
          code: "compose-label-active-file-missing",
          message: "Line-level stale entry.",
          line_no: 1,
          stack: "",
          service: "",
          hint: "",
          details: {},
        },
      ],
      cleanup: {
        cleanup_id: "cleanup-test",
        can_remove_unmatched: false,
        items: [
          {
            line_no: 1,
            raw: "repo/old:latest",
            image: "repo/old:latest",
            desired_tag: "",
            digest: "",
            reason: "compose-label-active-file-missing",
            diagnostic: null,
          },
        ],
      },
    });

    expect(state.visiblePlanIssues.value).toEqual([
      expect.objectContaining({
        line_no: null,
        message: "Global compose discovery issue.",
      }),
    ]);
  });

  it("replans with digest-pin label rewrite approval before marking it approved", async () => {
    const { state, updates } = setupPendingPlanReview();
    const issue = digestPinApprovalIssue();
    const createPlan = vi.spyOn(updates, "createPlan").mockResolvedValue(undefined);

    expect(state.digestPinLabelApprovalApproved(issue)).toBe(false);
    expect(await state.approveDigestPinLabelRewrite(issue)).toBe(false);

    state.setUpdateIntent({
      title: "Preview media plan",
      contextLabel: "media",
      lineNumbers: [1],
      allowTagUpdates: true,
      tagOverrides: [{ line_no: 1, tag: "1.1" }],
      digestPinLabelRewriteApprovals: [],
    });

    await expect(state.approveDigestPinLabelRewrite(issue)).resolves.toBe(true);
    expect(createPlan).toHaveBeenCalledWith(
      [1],
      true,
      [{ line_no: 1, tag: "1.1" }],
      [
        {
          stack: "media",
          service: "app",
          label_key: "org.opencontainers.image.version",
          current_label_value: "1.0",
          planned_tag: "1.1",
          proposed_label_value: "1.1",
        },
      ],
    );
    expect(state.digestPinLabelApprovalApproved(issue)).toBe(true);
  });

  it("surfaces digest-pin notice only when the plan contains digest-pin rewrites", () => {
    const { state, updates } = setupPendingPlanReview();

    expect(state.preflightDigestPinNotice.value).toBe("");

    updates.plan = planResponse({
      digest_pin_updates: true,
      stacks: [
        {
          ...planResponse().stacks[0],
          digest_pin_updates: [
            {
              source_image: "repo/app:1.0",
              resolved_tag: "1.1",
              planned_digest: "sha256:abc",
              final_image: "repo/app@sha256:abc",
              watch_tag: "1.1",
              marker: "sha256=abc",
              label_key: "org.opencontainers.image.version",
              label_value: "1.1",
              services: ["app"],
              label_rewrites: [],
            },
          ],
        },
      ],
    });

    expect(state.preflightDigestPinNotice.value).toBe(
      "1 digest-pin rewrite will pin approved tag updates after pull verification.",
    );
  });

  it("surfaces digest-unpin notice without digest-pin notice", () => {
    const { state, updates } = setupPendingPlanReview();

    updates.plan = planResponse({
      digest_pin_updates: false,
      stacks: [
        {
          ...planResponse().stacks[0],
          digest_unpin_updates: [
            {
              source_image: "repo/app@sha256:old",
              resolved_tag: "latest",
              tag_image: "repo/app:latest",
              current_digest: "sha256:old",
              target_digest: "sha256:new",
              watch_tag: "latest",
              marker: "wud-updater.resolved-tag=latest",
              label_key: "wud.tag.include",
              label_value: "^latest$",
              services: ["app"],
            },
          ],
          lines: [
            {
              ...planResponse().stacks[0].lines[0],
              action: "digest-unpin",
              compose_image: "repo/app@sha256:old",
              target_image: "repo/app:latest",
            },
          ],
        },
      ],
    });

    expect(state.preflightDigestPinNotice.value).toBe("");
    expect(state.preflightDigestUnpinNotice.value).toBe(
      "1 digest unpin migration will rewrite pinned Compose images back to their watched tag before pulling.",
    );
    expect(state.planDigestUnpinUpdates.value).toHaveLength(1);
  });
});

describe("usePendingApplyJob", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("creates apply snapshots from the current plan store state", () => {
    const { state, updates } = setupPendingApplyJob();
    updates.plan = planResponse();

    expect(state.createApplyJobSnapshot()).toMatchObject({
      contextLabel: "media",
      serviceCount: 1,
      stackCount: 1,
      sourceFile: "/out/images.todo",
      lines: [
        {
          lineNo: 1,
          serviceLabel: "app",
          tagRewriteLabel: "repo/app:1.0 -> repo/app:1.1",
          digestPinLabel: "",
          composeImage: "repo/app:1.0",
          targetImage: "repo/app:1.1",
        },
      ],
    });
  });

  it("derives apply job labels, logs, and failed progress precedence", () => {
    const { state, updates } = setupPendingApplyJob();
    const failedPull: ApplyJobProgressEvent = {
      job_id: "job-test",
      phase: "pull",
      status: "failure",
      message: "[media] Pull failed.",
      created_at: "2026-05-28T12:00:02+00:00",
      stack: "media",
      services: ["calibre"],
      line_numbers: [1],
    };
    const laterPullSuccess: ApplyJobProgressEvent = {
      job_id: "job-test",
      phase: "pull",
      status: "success",
      message: "[infra] Images pulled and verified.",
      created_at: "2026-05-28T12:00:03+00:00",
      stack: "infra",
      services: ["watchtower"],
      line_numbers: [2],
    };

    updates.setApplyJob(applyJobResponse({ status: "queued" }));

    expect(state.applyJobActive.value).toBe(true);
    expect(state.applyJobTitle.value).toBe("Applying 1 update");
    expect(state.applyJobNowTitle.value).toBe("Queued to start");
    expect(state.applyJobLatestLogMessage.value).toBe("Waiting for log output.");
    expect(state.applyJobLiveLogVisible.value).toBe(true);

    updates.setApplyJobLog(
      applyJobLogResponse({
        content: "first log line\nsecond log line\n",
      }),
    );

    expect(state.applyJobLatestLogMessage.value).toBe("second log line");

    updates.setApplyJob(
      applyJobResponse({
        status: "running",
        progress: [failedPull, laterPullSuccess],
      }),
    );

    expect(state.applyJobProgressSummary.value).toBe("Pull images failed");
    expect(state.applyJobProgressSteps.value.find((step) => step.key === "pull")).toMatchObject({
      status: "failure",
      message: "[media] Pull failed.",
      detail: "media / calibre / lines 1",
    });

    updates.setApplyJob(
      applyJobResponse({
        status: "failure",
        error: "updater exited with status 1",
        progress: [failedPull, laterPullSuccess],
      }),
    );

    expect(state.applyJobTitle.value).toBe("Apply failed");
    expect(state.applyJobNowTitle.value).toBe("Failed: Pull images");
    expect(state.applyJobNowMessage.value).toBe("updater exited with status 1");
  });

  it("keeps fallback verification stable when a job response omits progress events", () => {
    const { state, updates } = setupPendingApplyJob();
    updates.plan = planResponse();
    state.applyJobSnapshot.value = state.createApplyJobSnapshot();
    const job = applyJobResponse({ status: "success" });
    (job as unknown as { progress: unknown }).progress = {};

    updates.setApplyJob(job);

    expect(state.applyJobVerification.value).toMatchObject({
      status: "needs_review",
      total_count: 1,
      needs_review_count: 1,
      items: [
        {
          line_no: 1,
          image_status: "unknown",
          container_status: "unknown",
          health_status: "unknown",
          wud_status: "unknown",
          follow_up_needed: true,
        },
      ],
    });
  });

  it("handles stream errors and duplicate progress events", async () => {
    const { state, updates } = setupPendingApplyJob();
    const stream = mockApplyJobStream();
    const progress: ApplyJobProgressEvent = {
      job_id: "job-test",
      phase: "pull",
      status: "running",
      message: "[media] Pulling selected image updates.",
      created_at: "2026-05-28T12:00:01+00:00",
      stack: "media",
      services: ["calibre"],
      line_numbers: [1],
    };
    updates.setApplyJob(applyJobResponse({ status: "running" }));

    state.subscribeApplyJob("job-test");
    stream.emitLogData("{");
    await flushPromises();

    expect(updates.error).toBe("Job log stream returned invalid data.");
    expect(stream.close).not.toHaveBeenCalled();

    const progressData = JSON.stringify(progress);
    stream.emitProgressData(progressData);
    stream.emitProgressData(progressData);

    expect(updates.applyJob?.progress).toEqual([progress]);

    stream.emitJobData("{");
    await flushPromises();

    expect(updates.error).toBe("Job status stream returned invalid data.");
    expect(stream.close).toHaveBeenCalledTimes(1);
  });

  it("ignores invalid or mismatched progress stream events without closing the stream", () => {
    const { state, updates } = setupPendingApplyJob();
    const stream = mockApplyJobStream();
    const progress: ApplyJobProgressEvent = {
      job_id: "other-job",
      phase: "pull",
      status: "running",
      message: "[media] Pulling selected image updates.",
      created_at: "2026-05-28T12:00:01+00:00",
      stack: "media",
      services: ["calibre"],
      line_numbers: [1],
    };
    updates.setApplyJob(applyJobResponse({ job_id: "job-test", status: "running" }));

    state.subscribeApplyJob("job-test");
    stream.emitProgressData("{");

    expect(updates.error).toBe("Job progress stream returned invalid data.");
    expect(stream.close).not.toHaveBeenCalled();

    stream.emitProgressData(JSON.stringify(progress));
    expect(updates.applyJob?.progress).toEqual([]);
  });

  it("closes and refreshes after a terminal job stream event", async () => {
    const { state, updates, runs, loadPendingAndReleaseNotes } =
      setupPendingApplyJob();
    const stream = mockApplyJobStream();
    const loadApplyJobLogFromRun = vi
      .spyOn(updates, "loadApplyJobLogFromRun")
      .mockResolvedValue(applyJobLogResponse());
    const loadRuns = vi.spyOn(runs, "loadRuns").mockResolvedValue(undefined);

    state.subscribeApplyJob("job-test");
    stream.emitJobData(
      JSON.stringify(
        applyJobResponse({
          status: "success",
          run_id: 42,
        }),
      ),
    );
    await flushPromises();

    expect(stream.close).toHaveBeenCalledTimes(1);
    expect(loadApplyJobLogFromRun).toHaveBeenCalledWith(
      expect.objectContaining({ job_id: "job-test", run_id: 42 }),
    );
    expect(loadPendingAndReleaseNotes).toHaveBeenCalledTimes(1);
    expect(loadRuns).toHaveBeenCalledTimes(1);
  });

  it("derives the latest log message from apply job log content", () => {
    const { state, updates } = setupPendingApplyJob();

    // Setup an active job so fallback message is "Waiting for log output."
    updates.setApplyJob(applyJobResponse({ status: "running" }));

    updates.setApplyJobLog(applyJobLogResponse({ content: "" }));
    expect(state.applyJobLatestLogMessage.value).toBe("Waiting for log output.");

    updates.setApplyJobLog(applyJobLogResponse({ content: "   \n\t\n" }));
    expect(state.applyJobLatestLogMessage.value).toBe("Waiting for log output.");

    updates.setApplyJobLog(applyJobLogResponse({ content: "single line content" }));
    expect(state.applyJobLatestLogMessage.value).toBe("single line content");

    updates.setApplyJobLog(applyJobLogResponse({ content: "first\nsecond\n\n\n" }));
    expect(state.applyJobLatestLogMessage.value).toBe("second");
  });
});

import { createPinia, setActivePinia } from "pinia";
import { computed, ref } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { webApi, type ApplyJobProgressEvent } from "../src/api/client";
import { useUpdateTargetOptions } from "../src/composables/useUpdateTargetOptions";
import { useAuthStore } from "../src/stores/auth";
import { useRunsStore } from "../src/stores/runs";
import { useUpdatesStore } from "../src/stores/updates";
import {
  applyJobLogResponse,
  applyJobResponse,
  applyPreflightResponse,
  authSession,
  pendingGroupedItem,
  planResponse,
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

function mockApplyJobStream() {
  const close = vi.fn();
  let jobListener: ((event: MessageEvent<string>) => void) | null = null;
  let logListener: ((event: MessageEvent<string>) => void) | null = null;
  let progressListener: ((event: MessageEvent<string>) => void) | null = null;
  vi.spyOn(webApi, "openJobStream").mockReturnValue({
    addEventListener: vi.fn((type: string, listener: EventListener) => {
      if (type === "job") {
        jobListener = listener as (event: MessageEvent<string>) => void;
      }
      if (type === "log") {
        logListener = listener as (event: MessageEvent<string>) => void;
      }
      if (type === "progress") {
        progressListener = listener as (event: MessageEvent<string>) => void;
      }
    }),
    close,
    onerror: null,
    onmessage: null,
    onopen: null,
    readyState: 1,
    url: "",
    withCredentials: true,
    CONNECTING: 0,
    OPEN: 1,
    CLOSED: 2,
    dispatchEvent: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as EventSource);

  return {
    close,
    emitJobData(data: string): void {
      jobListener?.(new MessageEvent("job", { data }));
    },
    emitLogData(data: string): void {
      logListener?.(new MessageEvent("log", { data }));
    },
    emitProgressData(data: string): void {
      progressListener?.(new MessageEvent("progress", { data }));
    },
  };
}

describe("usePendingPlanReviewState", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("reflects mutation state label and type based on auth session", () => {
    const { state } = setupPendingPlanReview(false);
    expect(state.mutationStateLabel.value).toBe("Read-only");
    expect(state.mutationStateType.value).toBe("success");
    expect(state.pendingApplyTourDetail.value).toContain("Read-only mode keeps Apply disabled");

    const { state: stateEnabled } = setupPendingPlanReview(true);
    expect(stateEnabled.mutationStateLabel.value).toBe("Mutations enabled");
    expect(stateEnabled.mutationStateType.value).toBe("warning");
    expect(stateEnabled.pendingApplyTourDetail.value).toContain("Apply starts a server-side job");
  });

  it("derives updateSelectedDisabled from selection, loading, and tag override error", () => {
    const { state, updates, selectedLineNumbers, tagOverrideErrorForLines } =
      setupPendingPlanReview();

    // No selection → disabled
    expect(state.updateSelectedDisabled.value).toBe(true);

    // Has selection, no error
    selectedLineNumbers.value = [1];
    expect(state.updateSelectedDisabled.value).toBe(false);

    // Tag override error — must also poke selectedLineNumbers to invalidate the computed
    tagOverrideErrorForLines.mockReturnValue("Tag value is invalid");
    selectedLineNumbers.value = [...selectedLineNumbers.value];
    expect(state.updateSelectedDisabled.value).toBe(true);
    tagOverrideErrorForLines.mockReturnValue("");
    selectedLineNumbers.value = [...selectedLineNumbers.value];

    // Loading
    updates.loading = true;
    expect(state.updateSelectedDisabled.value).toBe(true);
    updates.loading = false;
    expect(state.updateSelectedDisabled.value).toBe(false);
  });

  it("derives planAlertType from plan status", () => {
    const { state, updates } = setupPendingPlanReview();

    expect(state.planAlertType.value).toBe("info");

    updates.plan = planResponse({ status: "blocked" });
    expect(state.planAlertType.value).toBe("error");

    updates.plan = planResponse({ status: "empty" });
    expect(state.planAlertType.value).toBe("warning");

    updates.plan = planResponse({ status: "ready" });
    expect(state.planAlertType.value).toBe("info");
  });

  it("derives preflightTitle for all plan and intent scenarios", () => {
    const { state, updates } = setupPendingPlanReview();

    // No plan, no intent
    expect(state.preflightTitle.value).toBe("Preview selected plan");

    // No plan with intent title
    state.setUpdateIntent({
      title: "Preview infra plan",
      contextLabel: "infra",
      lineNumbers: [1],
      allowTagUpdates: false,
      tagOverrides: [],
      digestPinLabelRewriteApprovals: [],
    });
    expect(state.preflightTitle.value).toBe("Preview infra plan");
    state.clearUpdateIntent();

    // Plan blocked
    updates.plan = planResponse({ status: "blocked" });
    expect(state.preflightTitle.value).toBe("Plan blocked");

    // Plan empty
    updates.plan = planResponse({ status: "empty" });
    expect(state.preflightTitle.value).toBe("No changes to apply");

    // Ready plan with single stack name → "Review X plan"
    updates.plan = planResponse({ status: "ready" });
    expect(state.preflightTitle.value).toBe("Review media plan");

    // Multi-stack context → "Review N stacks"
    updates.plan = planResponse({
      status: "ready",
      summary: { target_count: 2, matched_target_count: 2, stack_count: 2, service_count: 2, skipped_count: 0, issue_count: 0 },
      stacks: [
        { name: "media", directory: "/docker/media", compose_file: "docker-compose.yml", project_directory: "/docker/media", services_label: "app", services: ["app"], pull_services: ["app"], stop_services: ["app"], force_recreate: false, up_no_deps: true, tag_updates: [], digest_pin_updates: [], actions: [], lines: [{ line_no: 1, raw: "repo/app:1.0", image: "repo/app:1.0", resolved_image: "repo/app:1.0", compose_image: "repo/app:1.0", target_image: "repo/app:1.1", service: "app", digest: "", desired_tag: "1.1", action: "tag-update" }] },
        { name: "infra", directory: "/docker/infra", compose_file: "docker-compose.yml", project_directory: "/docker/infra", services_label: "db", services: ["db"], pull_services: ["db"], stop_services: ["db"], force_recreate: false, up_no_deps: true, tag_updates: [], digest_pin_updates: [], actions: [], lines: [{ line_no: 2, raw: "repo/db:1.0", image: "repo/db:1.0", resolved_image: "repo/db:1.0", compose_image: "repo/db:1.0", target_image: "repo/db:1.1", service: "db", digest: "", desired_tag: "1.1", action: "tag-update" }] },
      ],
    });
    expect(state.preflightTitle.value).toBe("Review 2 stacks");
  });

  it("derives preflightSummary for blocked, empty, and ready plans", () => {
    const { state, updates } = setupPendingPlanReview();

    // No plan
    expect(state.preflightSummary.value).toBe("");

    // Blocked plan with issues
    updates.plan = planResponse({
      status: "blocked",
      summary: { target_count: 1, matched_target_count: 0, stack_count: 1, service_count: 1, skipped_count: 0, issue_count: 2 },
      issues: [
        { severity: "error", code: "test-err", message: "err1", line_no: 1, stack: "", service: "", hint: "", details: {} },
        { severity: "error", code: "test-err2", message: "err2", line_no: 2, stack: "", service: "", hint: "", details: {} },
      ],
    });
    expect(state.preflightSummary.value).toBe("2 issues must be fixed before applying.");

    // Empty plan
    updates.plan = planResponse({ status: "empty" });
    expect(state.preflightSummary.value).toBe("No selected services need changes.");

    // Ready plan
    updates.plan = planResponse({ status: "ready" });
    expect(state.preflightSummary.value).toBe("1 service ready to update.");
  });

  it("derives preflightServiceImpactLabel for single and multi-stack plans", () => {
    const { state, updates } = setupPendingPlanReview();

    // No plan
    expect(state.preflightServiceImpactLabel.value).toBe("");

    // Single stack → service name only
    updates.plan = planResponse({ status: "ready" });
    expect(state.preflightServiceImpactLabel.value).toBe("app");

    // Multi-stack → "stack / service" format
    updates.plan = planResponse({
      status: "ready",
      summary: { target_count: 2, matched_target_count: 2, stack_count: 2, service_count: 2, skipped_count: 0, issue_count: 0 },
      stacks: [
        { name: "media", directory: "/docker/media", compose_file: "docker-compose.yml", project_directory: "/docker/media", services_label: "app", services: ["app"], pull_services: ["app"], stop_services: ["app"], force_recreate: false, up_no_deps: true, tag_updates: [], digest_pin_updates: [], actions: [], lines: [{ line_no: 1, raw: "repo/app:1.0", image: "repo/app:1.0", resolved_image: "repo/app:1.0", compose_image: "repo/app:1.0", target_image: "repo/app:1.1", service: "app", digest: "", desired_tag: "1.1", action: "tag-update" }] },
        { name: "infra", directory: "/docker/infra", compose_file: "docker-compose.yml", project_directory: "/docker/infra", services_label: "db", services: ["db"], pull_services: ["db"], stop_services: ["db"], force_recreate: false, up_no_deps: true, tag_updates: [], digest_pin_updates: [], actions: [], lines: [{ line_no: 2, raw: "repo/db:1.0", image: "repo/db:1.0", resolved_image: "repo/db:1.0", compose_image: "repo/db:1.0", target_image: "repo/db:1.1", service: "db", digest: "", desired_tag: "1.1", action: "tag-update" }] },
      ],
    });
    expect(state.preflightServiceImpactLabel.value).toBe("media / app, infra / db");
  });

  it("derives cleanupDisabledMessage for read-only and mutations-enabled-but-blocked cases", () => {
    const { state, updates } = setupPendingPlanReview(true);

    // No plan → empty
    expect(state.cleanupDisabledMessage.value).toBe("");

    // Plan with cleanup items, can_remove_unmatched=true → empty
    updates.plan = planResponse({
      cleanup: { cleanup_id: "c1", can_remove_unmatched: true, items: [{ line_no: 1, raw: "x", image: "repo/x:1.0", desired_tag: null, digest: "", reason: "unmatched", diagnostic: null }] },
    });
    expect(state.cleanupDisabledMessage.value).toBe("");

    // Mutations enabled but can_remove_unmatched=false → generic blocked message
    updates.plan = planResponse({
      cleanup: { cleanup_id: "c2", can_remove_unmatched: false, items: [{ line_no: 1, raw: "x", image: "repo/x:1.0", desired_tag: null, digest: "", reason: "unmatched", diagnostic: null }] },
    });
    expect(state.cleanupDisabledMessage.value).toBe("These pending entries cannot be removed right now.");

    // Read-only mode → read-only message
    const { state: readOnlyState, updates: readOnlyUpdates } = setupPendingPlanReview(false);
    readOnlyUpdates.plan = planResponse({
      cleanup: { cleanup_id: "c3", can_remove_unmatched: false, items: [{ line_no: 1, raw: "x", image: "repo/x:1.0", desired_tag: null, digest: "", reason: "unmatched", diagnostic: null }] },
    });
    expect(readOnlyState.cleanupDisabledMessage.value).toContain("Read-only mode is active");
  });

  it("derives pendingCleanupMessage from the pending cleanup store state", () => {
    const { state, updates } = setupPendingPlanReview();

    expect(state.pendingCleanupMessage.value).toBe("");

    updates.pendingCleanup = { cleanup_id: "c1", removed_count: 3 };
    expect(state.pendingCleanupMessage.value).toBe(
      "3 pending entries removed from images.todo.",
    );

    updates.pendingCleanup = { cleanup_id: "c2", removed_count: 1 };
    expect(state.pendingCleanupMessage.value).toBe(
      "1 pending entry removed from images.todo.",
    );
  });

  it("derives removalConfirmButtonLabel from removal items count", () => {
    const { state, updates } = setupPendingPlanReview();

    expect(state.removalConfirmButtonLabel.value).toBe("Remove 0 selected entries");

    updates.pendingRemovalPlan = {
      plan_id: "r1",
      can_remove: true,
      lines: [
        { line_no: 1, raw: "x", image: "repo/x:1.0", desired_tag: null, digest: "" },
        { line_no: 2, raw: "y", image: "repo/y:2.0", desired_tag: null, digest: "" },
      ],
    };
    expect(state.removalConfirmButtonLabel.value).toBe("Remove 2 selected entries");
  });

  it("derives batchSummaryLabel and selectedUpdateContext from stack groups", () => {
    const { state, updates, selectedLineNumbers } = setupPendingPlanReview();

    selectedLineNumbers.value = [1];
    // No stack groups → "selected updates"
    expect(state.selectedUpdateContext.value).toBe("selected updates");
    expect(state.batchSummaryLabel.value).toBe("1 update selected");

    // One matching stack group → stack name context
    updates.pending = {
      source_file: "/out/images.todo",
      exists: true,
      count: 1,
      items: [],
      grouping: {
        status: "ready",
        groups: [{ name: "media", directory: "/docker/media", compose_file: "docker-compose.yml", project_directory: "/docker/media", services_label: "app", services: ["app"], line_numbers: [1], items: [] }],
        unmatched: [],
        warnings: [],
      },
      warnings: [],
    };
    expect(state.selectedUpdateContext.value).toBe("media");
    expect(state.batchSummaryLabel.value).toBe("1 update selected in media");

    // Two matching stacks → pluralized
    selectedLineNumbers.value = [1, 2];
    updates.pending = {
      source_file: "/out/images.todo",
      exists: true,
      count: 2,
      items: [],
      grouping: {
        status: "ready",
        groups: [
          { name: "media", directory: "/docker/media", compose_file: "docker-compose.yml", project_directory: "/docker/media", services_label: "app", services: ["app"], line_numbers: [1], items: [] },
          { name: "infra", directory: "/docker/infra", compose_file: "docker-compose.yml", project_directory: "/docker/infra", services_label: "db", services: ["db"], line_numbers: [2], items: [] },
        ],
        unmatched: [],
        warnings: [],
      },
      warnings: [],
    };
    expect(state.selectedUpdateContext.value).toBe("2 stacks");
    expect(state.batchSummaryLabel.value).toBe("2 updates selected in 2 stacks");
  });

  it("derives mutationDisabledMessage for all plan-apply disabled states", () => {
    const { state, updates } = setupPendingPlanReview(true);

    // No plan → empty
    expect(state.mutationDisabledMessage.value).toBe("");

    // Ready plan that can apply → empty
    updates.plan = planResponse({ status: "ready", can_apply: true });
    expect(state.mutationDisabledMessage.value).toBe("");

    // Ready plan, mutations enabled, preflight failed
    updates.plan = planResponse({
      status: "ready",
      can_apply: false,
      apply_preflight: failedApplyPreflight("mutations-enabled", "Set WUD_WEB_MUTATIONS_ENABLED=true."),
    });
    expect(state.mutationDisabledMessage.value).toBe(
      "Fix the failed apply readiness check before applying updates.",
    );

    // Ready plan, mutations enabled, preflight ok, still cannot apply
    updates.plan = planResponse({
      status: "ready",
      can_apply: false,
      apply_preflight: applyPreflightResponse({ ok: true }),
    });
    expect(state.mutationDisabledMessage.value).toBe("This plan cannot be applied.");

    // Read-only mode with ready plan that cannot apply
    const { state: readOnlyState, updates: readOnlyUpdates } = setupPendingPlanReview(false);
    readOnlyUpdates.plan = planResponse({ status: "ready", can_apply: false });
    expect(readOnlyState.mutationDisabledMessage.value).toContain("Read-only mode is active");
  });

  it("derives applyPreflightCheckDetail for PASS, unmatched, and other codes", () => {
    const { state, updates } = setupPendingPlanReview();

    const passCheck = applyPreflightResponse().checks.find(
      (c) => c.code === "docker-reachable",
    )!;
    expect(state.applyPreflightCheckDetail(passCheck)).toBe("");

    // Unmatched without cleanup items → generic message
    const unmatchedCheck = {
      status: "FAIL" as const,
      code: "selected-services-matched",
      label: "Selected services matched",
      detail: "unmatched",
      source_check_codes: [],
    };
    expect(state.applyPreflightCheckDetail(unmatchedCheck)).toBe(
      "Selected update is unmatched.",
    );

    // Unmatched with cleanup items → stale review summary
    updates.plan = planResponse({
      cleanup: {
        cleanup_id: "c1",
        can_remove_unmatched: false,
        items: [{ line_no: 1, raw: "x", image: "repo/x:1.0", desired_tag: null, digest: "", reason: "unmatched", diagnostic: null }],
      },
    });
    const detail = state.applyPreflightCheckDetail(unmatchedCheck);
    expect(detail).toContain("1 entry needs review");

    // Other check code → returns check.detail
    const otherCheck = {
      status: "FAIL" as const,
      code: "bind-mounts-safe",
      label: "Bind mounts safe",
      detail: "Bind mount /data may be unsafe.",
      source_check_codes: [],
    };
    expect(state.applyPreflightCheckDetail(otherCheck)).toBe("Bind mount /data may be unsafe.");
  });

  it("derives digestPinLabelApprovalApproved correctly", () => {
    const { state } = setupPendingPlanReview();

    const approvalIssue: import("../src/api/client").PlanIssue = {
      severity: "error",
      code: "compose-digest-pin-label-rewrite-unapproved",
      message: "Label rewrite unapproved.",
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
    };

    // No intent → false
    expect(state.digestPinLabelApprovalApproved(approvalIssue)).toBe(false);

    // Intent without the approval → false
    state.setUpdateIntent({
      title: "t",
      contextLabel: "media",
      lineNumbers: [1],
      allowTagUpdates: false,
      tagOverrides: [],
      digestPinLabelRewriteApprovals: [],
    });
    expect(state.digestPinLabelApprovalApproved(approvalIssue)).toBe(false);

    // Intent with matching approval → true
    state.setUpdateIntent({
      title: "t",
      contextLabel: "media",
      lineNumbers: [1],
      allowTagUpdates: false,
      tagOverrides: [],
      digestPinLabelRewriteApprovals: [
        {
          stack: "media",
          service: "app",
          label_key: "org.opencontainers.image.version",
          current_label_value: "1.0",
          planned_tag: "1.1",
          proposed_label_value: "1.1",
        },
      ],
    });
    expect(state.digestPinLabelApprovalApproved(approvalIssue)).toBe(true);
  });

  it("derives issueLabel, issueType, issueHint, and issueDetailString helpers", () => {
    const { state } = setupPendingPlanReview();

    const errorIssue: import("../src/api/client").PlanIssue = {
      severity: "error",
      code: "test-error",
      message: "Something failed",
      line_no: 5,
      stack: "media",
      service: "app",
      hint: "Check the config",
      details: { extra_key: "extra_value" },
    };

    expect(state.issueType(errorIssue)).toBe("error");
    expect(state.issueLabel(errorIssue)).toBe("line 5 / media / app: Something failed");
    expect(state.issueHint(errorIssue)).toBe("Check the config");
    expect(state.issueDetailString(errorIssue, "extra_key")).toBe("extra_value");
    expect(state.issueDetailString(errorIssue, "missing_key")).toBe("");

    const warnIssue: import("../src/api/client").PlanIssue = {
      severity: "warning",
      code: "test-warning",
      message: "Worth noting",
      line_no: null,
      stack: "",
      service: "",
      hint: "",
      details: {},
    };
    expect(state.issueType(warnIssue)).toBe("warning");
    expect(state.issueLabel(warnIssue)).toBe("Worth noting");
    expect(state.issueHint(warnIssue)).toBe("");
  });

  it("does not hide issues with null line_no when cleanup keys overlap by code", () => {
    const { state, updates } = setupPendingPlanReview();

    updates.plan = planResponse({
      issues: [
        {
          severity: "error",
          code: "compose-label-active-file-missing",
          message: "Global issue (no line)",
          line_no: null,
          stack: "",
          service: "",
          hint: "",
          details: {},
        },
        {
          severity: "error",
          code: "compose-label-active-file-missing",
          message: "Line-level issue",
          line_no: 1,
          stack: "",
          service: "",
          hint: "",
          details: {},
        },
      ],
      cleanup: {
        cleanup_id: "c1",
        can_remove_unmatched: false,
        items: [{ line_no: 1, raw: "x", image: "repo/x:1.0", desired_tag: null, digest: "", reason: "compose-label-active-file-missing", diagnostic: null }],
      },
    });

    const visible = state.visiblePlanIssues.value;
    // Line 1 issue is hidden by cleanup preview
    expect(visible.some((i) => i.line_no === 1)).toBe(false);
    // Global issue (null line_no) is never hidden
    expect(visible.some((i) => i.line_no === null)).toBe(true);
  });

  it("derives staleDiagnosticLabel and staleDiagnosticDetail for all diagnostic codes", () => {
    const { state } = setupPendingPlanReview();

    const cases: Array<{ code: string; label: string; detail: string }> = [
      {
        code: "compose-label-active-file-missing",
        label: "Compose file missing",
        detail: "Running container exists, but its Compose file is missing or archived.",
      },
      {
        code: "compose-label-undiscovered-active-file",
        label: "Stack not discovered",
        detail: "Running container exists, but Compose discovery does not include its stack.",
      },
      {
        code: "matching-container-without-compose-labels",
        label: "Missing Compose labels",
        detail: "Running container exists, but Docker did not report Compose labels.",
      },
      {
        code: "unmatched",
        label: "No Compose match",
        detail: "No discovered Compose service or running container matched this line.",
      },
    ];

    for (const { code, label, detail } of cases) {
      const item = { diagnostic: { code, message: "", hint: "", stack: "", service: "", compose_file: "", found_files: [], details: {} } };
      expect(state.staleDiagnosticLabel(item)).toBe(label);
      expect(state.staleDiagnosticDetail(item)).toBe(detail);
    }

    // Default with diagnostic (unknown code with message)
    const unknownWithMsg = { diagnostic: { code: "unknown-code", message: "Custom message.", hint: "", stack: "", service: "", compose_file: "", found_files: [], details: {} } };
    expect(state.staleDiagnosticLabel(unknownWithMsg)).toBe("Unmatched source");
    expect(state.staleDiagnosticDetail(unknownWithMsg)).toBe("Custom message.");

    // Default with no diagnostic
    const noDiag = { diagnostic: null };
    expect(state.staleDiagnosticLabel(noDiag)).toBe("No Compose match");
    expect(state.staleDiagnosticDetail(noDiag)).toBe("No discovered Compose service matched this line.");
  });

  it("derives preflightTagRewriteNotice when allowTagUpdates is set and tag rewrites exist", () => {
    const { state, updates } = setupPendingPlanReview();

    // No intent → no notice
    updates.plan = planResponse({
      stacks: [{
        name: "media",
        directory: "/docker/media",
        compose_file: "docker-compose.yml",
        project_directory: "/docker/media",
        services_label: "app",
        services: ["app"],
        pull_services: ["app"],
        stop_services: ["app"],
        force_recreate: false,
        up_no_deps: true,
        tag_updates: [{ old_image: "repo/app:1.0", desired_tag: "1.1", new_image: "repo/app:1.1", services: ["app"] }],
        digest_pin_updates: [],
        actions: [],
        lines: [{ line_no: 1, raw: "repo/app:1.0", image: "repo/app:1.0", resolved_image: "repo/app:1.0", compose_image: "repo/app:1.0", target_image: "repo/app:1.1", service: "app", digest: "", desired_tag: "1.1", action: "tag-update" }],
      }],
    });
    expect(state.preflightTagRewriteNotice.value).toBe("");

    // Intent with allowTagUpdates=false → no notice
    state.setUpdateIntent({
      title: "t",
      contextLabel: "media",
      lineNumbers: [1],
      allowTagUpdates: false,
      tagOverrides: [],
      digestPinLabelRewriteApprovals: [],
    });
    expect(state.preflightTagRewriteNotice.value).toBe("");

    // Intent with allowTagUpdates=true → notice
    state.setUpdateIntent({
      title: "t",
      contextLabel: "media",
      lineNumbers: [1],
      allowTagUpdates: true,
      tagOverrides: [],
      digestPinLabelRewriteApprovals: [],
    });
    expect(state.preflightTagRewriteNotice.value).toBe(
      "1 tag rewrite will be applied before recreating selected services.",
    );
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
    await Promise.resolve();

    expect(updates.error).toBe("Job log stream returned invalid data.");
    expect(stream.close).not.toHaveBeenCalled();

    const progressData = JSON.stringify(progress);
    stream.emitProgressData(progressData);
    stream.emitProgressData(progressData);

    expect(updates.applyJob?.progress).toEqual([progress]);

    stream.emitJobData("{");
    await Promise.resolve();

    expect(updates.error).toBe("Job status stream returned invalid data.");
    expect(stream.close).toHaveBeenCalledTimes(1);
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

  it("reflects alert type, succeeded, and panel status label for each job status", () => {
    const { state, updates } = setupPendingApplyJob();

    expect(state.applyJobAlertType.value).toBe("info");
    expect(state.applyJobSucceeded.value).toBe(false);
    expect(state.applyJobPanelStatusLabel.value).toBe("Job");

    updates.setApplyJob(applyJobResponse({ status: "queued" }));
    expect(state.applyJobAlertType.value).toBe("info");
    expect(state.applyJobPanelStatusLabel.value).toBe("Queued");
    expect(state.applyJobSucceeded.value).toBe(false);

    updates.setApplyJob(applyJobResponse({ status: "running" }));
    expect(state.applyJobAlertType.value).toBe("info");
    expect(state.applyJobPanelStatusLabel.value).toBe("Running");
    expect(state.applyJobActive.value).toBe(true);

    updates.setApplyJob(applyJobResponse({ status: "success" }));
    expect(state.applyJobAlertType.value).toBe("success");
    expect(state.applyJobPanelStatusLabel.value).toBe("Complete");
    expect(state.applyJobSucceeded.value).toBe(true);
    expect(state.applyJobActive.value).toBe(false);

    updates.setApplyJob(applyJobResponse({ status: "failure" }));
    expect(state.applyJobAlertType.value).toBe("error");
    expect(state.applyJobPanelStatusLabel.value).toBe("Failed");
    expect(state.applyJobSucceeded.value).toBe(false);
  });

  it("derives started label, log title, and live log toggle label", () => {
    const { state, updates } = setupPendingApplyJob();

    expect(state.applyJobStartedLabel.value).toBe("");

    updates.setApplyJob(applyJobResponse({ started_at: null }));
    expect(state.applyJobStartedLabel.value).toBe("Queued");

    updates.setApplyJob(applyJobResponse({ started_at: "2026-05-28T12:00:00+00:00" }));
    expect(state.applyJobStartedLabel.value).toBe("2026-05-28T12:00:00+00:00");

    // Log title precedence: applyJobLog.log_file > applyJob.log_file > "Live log"
    expect(state.applyJobLogTitle.value).toBe("Live log");

    updates.setApplyJob(applyJobResponse({ log_file: "job-log.txt" }));
    expect(state.applyJobLogTitle.value).toBe("job-log.txt");

    updates.setApplyJobLog(applyJobLogResponse({ log_file: "/out/logs/explicit.log" }));
    expect(state.applyJobLogTitle.value).toBe("/out/logs/explicit.log");

    // Live log toggle label
    expect(state.applyJobLiveLogToggleLabel.value).toBe("Hide live log output");
    state.applyJobLiveLogExpanded.value = false;
    expect(state.applyJobLiveLogToggleLabel.value).toBe("Show live log output");
  });

  it("derives log waiting states correctly", () => {
    const { state, updates } = setupPendingApplyJob();

    // No log loaded → waiting = true
    expect(state.applyJobLogWaiting.value).toBe(true);

    // Log with error → waiting = false (error path: !log is false, log.error is truthy → return !log = false)
    updates.setApplyJobLog(applyJobLogResponse({ error: "log fetch failed", exists: false, content: "" }));
    expect(state.applyJobLogWaiting.value).toBe(false);

    // Log file not yet present (exists=false, no content) → waiting = true
    updates.setApplyJobLog(applyJobLogResponse({ error: "", exists: false, content: "" }));
    expect(state.applyJobLogWaiting.value).toBe(true);

    // Log with content → waiting = false
    updates.setApplyJobLog(applyJobLogResponse({ content: "some output\n" }));
    expect(state.applyJobLogWaiting.value).toBe(false);
  });

  it("derives log empty message and latest log message for inactive job", () => {
    const { state, updates } = setupPendingApplyJob();

    // No job → inactive
    updates.setApplyJobLog(applyJobLogResponse({ content: "" }));
    expect(state.applyJobLogEmptyMessage.value).toBe("No live log was captured.");
    expect(state.applyJobLatestLogMessage.value).toBe("No log output captured.");

    // Active job
    updates.setApplyJob(applyJobResponse({ status: "running" }));
    expect(state.applyJobLogEmptyMessage.value).toBe("Waiting for log output.");
    expect(state.applyJobLatestLogMessage.value).toBe("Waiting for log output.");
  });

  it("derives impact label for single-stack and multi-stack snapshots", () => {
    const { state } = setupPendingApplyJob();

    expect(state.applyJobImpactLabel.value).toBe("");

    state.applyJobSnapshot.value = {
      contextLabel: "media",
      serviceCount: 2,
      stackCount: 1,
      sourceFile: "/out/images.todo",
      lines: [],
    };
    expect(state.applyJobImpactLabel.value).toBe("2 services in media");

    state.applyJobSnapshot.value = {
      contextLabel: "2 stacks",
      serviceCount: 3,
      stackCount: 2,
      sourceFile: "/out/images.todo",
      lines: [],
    };
    expect(state.applyJobImpactLabel.value).toBe("3 services across 2 stacks");
  });

  it("derives now description IDs based on whether detail is present", () => {
    const { state, updates } = setupPendingApplyJob();

    updates.setApplyJob(applyJobResponse({ status: "queued" }));
    // No progress steps have events, no snapshot → no detail
    expect(state.applyJobNowDescriptionIds.value).toBe("apply-job-now-message");

    // Provide a snapshot so applyJobImpactLabel is non-empty
    state.applyJobSnapshot.value = {
      contextLabel: "media",
      serviceCount: 1,
      stackCount: 1,
      sourceFile: "/out/images.todo",
      lines: [],
    };
    expect(state.applyJobNowDescriptionIds.value).toBe(
      "apply-job-now-message apply-job-now-detail",
    );
  });

  it("derives progress summary for empty, running, and complete progress states", () => {
    const { state, updates } = setupPendingApplyJob();

    // No progress, no active job
    updates.setApplyJob(applyJobResponse({ status: "success" }));
    expect(state.applyJobProgressSummary.value).toBe("No progress events");

    // No progress, active job
    updates.setApplyJob(applyJobResponse({ status: "running" }));
    expect(state.applyJobProgressSummary.value).toBe("Starting");

    // Running step
    const runningStep: ApplyJobProgressEvent = {
      job_id: "job-test",
      phase: "pull",
      status: "running",
      message: "Pulling images.",
      created_at: "2026-05-28T12:00:01+00:00",
      stack: "media",
      services: ["app"],
      line_numbers: [1],
    };
    updates.setApplyJob(applyJobResponse({ status: "running", progress: [runningStep] }));
    expect(state.applyJobProgressSummary.value).toBe("Pull images");

    // Completion success
    const completionSuccess: ApplyJobProgressEvent = {
      job_id: "job-test",
      phase: "completion",
      status: "success",
      message: "Done.",
      created_at: "2026-05-28T12:00:05+00:00",
      stack: "",
      services: [],
      line_numbers: [],
    };
    updates.setApplyJob(
      applyJobResponse({ status: "success", progress: [completionSuccess] }),
    );
    expect(state.applyJobProgressSummary.value).toBe("Complete");
  });

  it("derives applyJobNowTitle for success, running-step, completed-step, and starting states", () => {
    const { state, updates } = setupPendingApplyJob();

    // No job
    expect(state.applyJobNowTitle.value).toBe("");

    // Success
    updates.setApplyJob(applyJobResponse({ status: "success" }));
    expect(state.applyJobNowTitle.value).toBe("Update complete");

    // Failure without step
    updates.setApplyJob(applyJobResponse({ status: "failure" }));
    expect(state.applyJobNowTitle.value).toBe("Apply failed");

    // Running step
    const runningStep: ApplyJobProgressEvent = {
      job_id: "job-test",
      phase: "recreate",
      status: "running",
      message: "Recreating services.",
      created_at: "2026-05-28T12:00:02+00:00",
      stack: "media",
      services: ["app"],
      line_numbers: [1],
    };
    updates.setApplyJob(applyJobResponse({ status: "running", progress: [runningStep] }));
    expect(state.applyJobNowTitle.value).toBe("Running: Recreate");

    // Completed step (success step, no running, no failure, no completion phase)
    const successStep: ApplyJobProgressEvent = {
      job_id: "job-test",
      phase: "preflight",
      status: "success",
      message: "Preflight passed.",
      created_at: "2026-05-28T12:00:01+00:00",
      stack: "",
      services: [],
      line_numbers: [],
    };
    updates.setApplyJob(applyJobResponse({ status: "running", progress: [successStep] }));
    expect(state.applyJobNowTitle.value).toBe("Completed: Preflight");

    // Running status, no steps at all → "Starting updater"
    updates.setApplyJob(applyJobResponse({ status: "running", progress: [] }));
    expect(state.applyJobNowTitle.value).toBe("Starting updater");
  });

  it("derives applyJobNowMessage from step message or status message fallback", () => {
    const { state, updates } = setupPendingApplyJob();

    // No job
    expect(state.applyJobNowMessage.value).toBe("");

    // Running job without progress step → falls back to status message
    updates.setApplyJob(applyJobResponse({ status: "running" }));
    expect(state.applyJobNowMessage.value).toBe("Updater command is running.");

    // Running step available → uses step message
    const runningStep: ApplyJobProgressEvent = {
      job_id: "job-test",
      phase: "pull",
      status: "running",
      message: "[media] Pulling images now.",
      created_at: "2026-05-28T12:00:01+00:00",
      stack: "media",
      services: ["app"],
      line_numbers: [1],
    };
    updates.setApplyJob(applyJobResponse({ status: "running", progress: [runningStep] }));
    expect(state.applyJobNowMessage.value).toBe("[media] Pulling images now.");

    // Success without error → status message
    updates.setApplyJob(applyJobResponse({ status: "success" }));
    expect(state.applyJobNowMessage.value).toBe("1 update finished. Pending updates and run history were refreshed.");
  });

  it("closes stream on onerror when job is already terminal", () => {
    const { updates } = setupPendingApplyJob();
    let onErrorHandler: (() => void) | null = null;
    const close = vi.fn();
    vi.spyOn(webApi, "openJobStream").mockReturnValue({
      addEventListener: vi.fn(),
      close,
      get onerror() {
        return null;
      },
      set onerror(handler) {
        onErrorHandler = handler as () => void;
      },
      onmessage: null,
      onopen: null,
      readyState: 1,
      url: "",
      withCredentials: true,
      CONNECTING: 0,
      OPEN: 1,
      CLOSED: 2,
      dispatchEvent: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as EventSource);

    const { state } = setupPendingApplyJob();
    updates.setApplyJob(applyJobResponse({ status: "success" }));
    state.subscribeApplyJob("job-test");

    expect(onErrorHandler).not.toBeNull();
    onErrorHandler!();
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("ignores progress events with a mismatched job_id", () => {
    const { state, updates } = setupPendingApplyJob();
    const stream = mockApplyJobStream();
    updates.setApplyJob(applyJobResponse({ job_id: "job-test", status: "running" }));

    state.subscribeApplyJob("job-test");

    const mismatchedProgress: ApplyJobProgressEvent = {
      job_id: "other-job",
      phase: "pull",
      status: "running",
      message: "Pulling.",
      created_at: "2026-05-28T12:00:01+00:00",
      stack: "media",
      services: ["app"],
      line_numbers: [1],
    };
    stream.emitProgressData(JSON.stringify(mismatchedProgress));

    expect(updates.applyJob?.progress).toEqual([]);
  });

  it("falls back to snapshot line count when job has no selected_line_numbers", () => {
    const { state } = setupPendingApplyJob();

    // applyJobUpdateCount: job.selected_line_numbers || snapshot.lines.length || 0
    state.applyJobSnapshot.value = {
      contextLabel: "media",
      serviceCount: 3,
      stackCount: 1,
      sourceFile: "/out/images.todo",
      lines: [
        { key: "a", lineNo: 1, serviceLabel: "app", tagRewriteLabel: "", digestPinLabel: "", composeImage: "repo/app:1.0", targetImage: "repo/app:1.1" },
        { key: "b", lineNo: 2, serviceLabel: "db", tagRewriteLabel: "", digestPinLabel: "", composeImage: "repo/db:1.0", targetImage: "repo/db:1.1" },
        { key: "c", lineNo: 3, serviceLabel: "cache", tagRewriteLabel: "", digestPinLabel: "", composeImage: "repo/cache:1.0", targetImage: "repo/cache:1.1" },
      ],
    };
    // No applyJob set → job has no selected_line_numbers
    expect(state.applyJobUpdateLabel.value).toBe("3 updates");
  });

  it("handles reconnectObservedApplyJob when no remembered job id is set", async () => {
    const { state, updates } = setupPendingApplyJob();

    updates.rememberedApplyJobId = null;
    // Should return early without error
    await expect(state.reconnectObservedApplyJob()).resolves.toBeUndefined();
  });
});

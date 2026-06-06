<script setup lang="ts">
import { computed, h, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { breakpointsTailwind, useBreakpoints } from "@vueuse/core";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Play,
  Trash2,
  X,
  XCircle,
} from "@lucide/vue";
import {
  NAlert,
  NButton,
  NCheckbox,
  NDataTable,
  NInput,
  NModal,
  NTag,
  type DataTableColumns,
  type DataTableRowKey,
} from "naive-ui";

import {
  webApi,
  type ApplyJobLogResponse,
  type ApplyJobProgressEvent,
  type ApplyJobResponse,
  type ApplyPreflightCheck,
  type ApplyPreflightStatus,
  type DigestPinLabelRewriteApprovalRequest,
  type PendingDiagnostic,
  type PendingGroupedItem,
  type PendingItem,
  type PendingRemovalPlanLine,
  type PendingStackGroup,
  type PlanCleanupItem,
  type PlanAction,
  type PlanIssue,
  type PlanLine,
  type ReleaseNoteInfo,
  type TagOverrideRequest,
} from "../api/client";
import CoreUpdateTourPanel from "../components/CoreUpdateTourPanel.vue";
import { useAuthStore } from "../stores/auth";
import { useUpdatesStore } from "../stores/updates";
import { useRunsStore } from "../stores/runs";
import { useSettingsStore } from "../stores/settings";

const updates = useUpdatesStore();
const runs = useRunsStore();
const settings = useSettingsStore();
const auth = useAuthStore();
const breakpoints = useBreakpoints(breakpointsTailwind);
const isMobile = breakpoints.smaller("md");
const selectedLineNumbers = ref<number[]>([]);
const tagOverrides = ref<Record<number, string>>({});
const showPreflightModal = ref(false);
const showCleanupModal = ref(false);
const showRemovalModal = ref(false);
const jobEventSource = ref<EventSource | null>(null);
const applyJobPanelRef = ref<HTMLElement | null>(null);
const applyJobPanelLogRef = ref<HTMLElement | null>(null);
const applyJobLiveLogExpanded = ref(true);
const applyJobRunLogFallbackRunId = ref<number | null>(null);
const terminalJobStatuses = new Set<ApplyJobResponse["status"]>([
  "success",
  "failure",
]);
const tagValuePattern = /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$/;

type UpdateIntent = {
  title: string;
  contextLabel: string;
  lineNumbers: number[];
  allowTagUpdates: boolean;
  tagOverrides: TagOverrideRequest[];
  digestPinLabelRewriteApprovals: DigestPinLabelRewriteApprovalRequest[];
};

type ApplyJobSnapshotLine = {
  key: string;
  lineNo: number;
  serviceLabel: string;
  tagRewriteLabel: string;
  digestPinLabel: string;
  composeImage: string;
  targetImage: string;
};

type ApplyJobPlanSnapshot = {
  contextLabel: string;
  serviceCount: number;
  stackCount: number;
  sourceFile: string;
  lines: ApplyJobSnapshotLine[];
};

type AssistantDetailKey =
  | "preflight_findings"
  | "possible_reasons"
  | "recommended_actions";
type DiagnosticItem = {
  diagnostic?: PendingDiagnostic | null;
};

type SafetyCue = {
  key: string;
  label: string;
  type: "default" | "error" | "info" | "success" | "warning";
};

type ApplyJobProgressPhase = {
  key: string;
  label: string;
  waitingMessage: string;
};

type ApplyJobProgressStep = ApplyJobProgressPhase & {
  status: "pending" | ApplyJobProgressEvent["status"];
  statusLabel: string;
  message: string;
  detail: string;
  event: ApplyJobProgressEvent | null;
};

const applyJobProgressPhases: ApplyJobProgressPhase[] = [
  {
    key: "preflight",
    label: "Preflight",
    waitingMessage: "Waiting to validate the pending file and Compose state.",
  },
  {
    key: "pull",
    label: "Pull images",
    waitingMessage: "Waiting for image pulls to begin.",
  },
  {
    key: "recreate",
    label: "Recreate",
    waitingMessage: "Waiting to recreate selected services.",
  },
  {
    key: "health",
    label: "Health wait",
    waitingMessage: "Waiting for container health checks.",
  },
  {
    key: "cleanup",
    label: "Cleanup",
    waitingMessage: "Waiting to reconcile the pending file.",
  },
  {
    key: "completion",
    label: "Complete",
    waitingMessage: "Waiting for the updater result.",
  },
];

const updateIntent = ref<UpdateIntent | null>(null);
const applyJobSnapshot = ref<ApplyJobPlanSnapshot | null>(null);

const columns = computed<DataTableColumns<PendingItem>>(() => [
  { type: "selection", width: 48 },
  { title: "Line", key: "line_no", width: 80 },
  {
    title: "Image",
    key: "image",
    minWidth: 240,
    render: (row) =>
      h("code", { class: "pending-table-value", title: row.image }, row.image),
  },
  {
    title: "Repository",
    key: "repo",
    minWidth: 200,
    render: (row) =>
      h("span", { class: "pending-table-value", title: row.repo }, row.repo),
  },
  {
    title: "Current tag",
    key: "current_tag",
    minWidth: 120,
    render: (row) => displayValue(row.current_tag),
  },
  {
    title: "New tag",
    key: "desired_tag",
    minWidth: 160,
    render: (row) => {
      if (!row.desired_tag) {
        return displayValue("");
      }
      return h(NInput, {
        value: tagOverrideValue(row),
        size: "small",
        class: "tag-override-input",
        placeholder: row.desired_tag,
        inputProps: tagInputProps(row),
        onUpdateValue: (value: string) => updateTagOverride(row, value),
      });
    },
  },
  {
    title: "New digest",
    key: "digest",
    minWidth: 220,
    render: (row) =>
      row.digest
        ? h("code", { class: "digest-value", title: row.digest }, displayDigest(row.digest))
        : displayValue(""),
  },
  {
    title: "Safety cues",
    key: "safety_cues",
    minWidth: 200,
    render: (row) => renderRiskBadges(row),
  },
  {
    title: "Release notes",
    key: "release_notes",
    minWidth: 220,
    render: (row) => renderReleaseNotes(row),
  },
]);

const allLineNumbers = computed(
  () => uniqueSorted(updates.pending?.items.map((item) => item.line_no) ?? []),
);
const groupingReady = computed(
  () => updates.pending?.grouping.status === "ready",
);
const stackGroups = computed(() =>
  groupingReady.value ? (updates.pending?.grouping.groups ?? []) : [],
);
const unmatchedItems = computed(() =>
  groupingReady.value ? (updates.pending?.grouping.unmatched ?? []) : [],
);
const stackLineNumbers = computed(() =>
  uniqueSorted(stackGroups.value.flatMap((group) => group.line_numbers)),
);
const pendingLoaded = computed(() => updates.pending !== null);
const pendingLoadFailed = computed(
  () => !pendingLoaded.value && !updates.loading && Boolean((updates.error || runs.error)),
);
const pendingLoading = computed(
  () => !pendingLoaded.value && !pendingLoadFailed.value,
);
const pendingHeadingText = computed(() =>
  updates.pending
    ? pluralize(updates.pending.count, "pending update")
    : pendingLoadFailed.value
      ? "Pending updates unavailable"
      : "Loading pending updates",
);
const selectableLineNumbers = computed(() =>
  groupingReady.value ? stackLineNumbers.value : allLineNumbers.value,
);
const selectAllLabel = computed(() =>
  groupingReady.value ? "Select all stack updates" : "Select all",
);
const releaseNotesByLine = computed(() => {
  const notes = new Map<number, ReleaseNoteInfo>();
  for (const item of updates.releaseNotes?.items ?? []) {
    notes.set(item.line_no, item);
  }
  return notes;
});
const latestRun = computed(() => runs.runs[0] ?? null);
const pendingSourceFile = computed(() => updates.pending?.source_file ?? "Pending file");
const pendingSourceLabel = computed(() => fileName(pendingSourceFile.value));
const pendingSourceDisplay = computed(() =>
  updates.pending?.source_file ? `Source ${pendingSourceLabel.value}` : "Pending file",
);
const selectedLineSet = computed(() => new Set(selectedLineNumbers.value));
const mutationStateLabel = computed(() =>
  auth.session?.mutations_enabled ? "Mutations enabled" : "Read-only",
);
const mutationStateType = computed(() =>
  auth.session?.mutations_enabled ? "warning" : "success",
);
const pendingApplyTourDetail = computed(() =>
  auth.session?.mutations_enabled
    ? "Apply starts a server-side job, streams the live log, and writes a run record you can verify afterward."
    : "Read-only mode keeps Apply disabled. You can still preview impact now, then enable browser mutations server-side when you are ready to apply.",
);
const selectedTagOverrideError = computed(() => {
  return tagOverrideErrorForLines(selectedLineNumbers.value);
});
const updateSelectedDisabled = computed(
  () =>
    selectedLineNumbers.value.length === 0 ||
    updates.loading ||
    Boolean(selectedTagOverrideError.value),
);
const removeSelectedDisabled = computed(
  () =>
    selectedLineNumbers.value.length === 0 ||
    updates.loading ||
    !auth.session?.mutations_enabled,
);
const removeSelectedDisabledMessage = computed(() => {
  if (!selectedLineNumbers.value.length || auth.session?.mutations_enabled) {
    return "";
  }
  return "Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to remove selected entries.";
});
const planAlertType = computed(() => {
  if (updates.plan?.status === "blocked") {
    return "error";
  }
  if (updates.plan?.status === "empty") {
    return "warning";
  }
  return "info";
});
const planContextLabel = computed(() => {
  if (!updates.plan) {
    return updateIntent.value?.contextLabel ?? "selected updates";
  }
  if (updates.plan.stacks.length === 1) {
    return updates.plan.stacks[0].name;
  }
  if (updates.plan.summary.stack_count > 1) {
    return pluralize(updates.plan.summary.stack_count, "stack");
  }
  return updateIntent.value?.contextLabel ?? "selected updates";
});
const preflightTitle = computed(() => {
  if (!updates.plan) {
    return updateIntent.value?.title ?? "Preview selected plan";
  }
  if (updates.plan.status === "blocked") {
    return "Plan blocked";
  }
  if (updates.plan.status === "empty") {
    return "No changes to apply";
  }
  const context = planContextLabel.value;
  if (context === "selected updates") {
    return "Review selected updates";
  }
  if (/^\d+ stacks?$/.test(context)) {
    return `Review ${context}`;
  }
  return `Review ${context} plan`;
});
const preflightSummary = computed(() => {
  if (!updates.plan) {
    return "";
  }
  if (updates.plan.status === "blocked") {
    const issueCount = updates.plan.summary.issue_count || updates.plan.issues.length;
    return `${pluralize(issueCount, "issue")} must be fixed before applying.`;
  }
  if (updates.plan.status === "empty") {
    return "No selected services need changes.";
  }
  const serviceCount =
    updates.plan.summary.service_count ||
    updates.plan.summary.target_count ||
    updates.plan.selected_line_numbers.length;
  return `${pluralize(serviceCount, "service")} ready to update.`;
});
const preflightServiceImpactLabel = computed(() => {
  if (!updates.plan || updates.plan.status !== "ready") {
    return "";
  }
  return summarizeList(
    planLines.value.map(({ stack, line }) =>
      updates.plan && updates.plan.summary.stack_count > 1
        ? `${stack} / ${line.service || "stack-level"}`
        : line.service || "stack-level",
    ),
    4,
  );
});
const applyPreflight = computed(() => updates.plan?.apply_preflight ?? null);
const applyPreflightPassedChecks = computed(() =>
  applyPreflight.value?.checks.filter((check) => check.status === "PASS") ?? [],
);
const applyPreflightAttentionChecks = computed(() =>
  applyPreflight.value?.checks.filter((check) => check.status !== "PASS") ?? [],
);
const applyPreflightPassedText = computed(() =>
  applyPreflightPassedChecks.value.map((check) => check.label).join(", "),
);
const applyReadinessStatusLabel = computed(() => {
  if (!applyPreflight.value) {
    return "";
  }
  if (!applyPreflight.value.ok) {
    return "Blocked";
  }
  return applyPreflight.value.warnings > 0 ? "Warnings" : "Ready";
});
const applyReadinessStatusType = computed<"success" | "warning" | "error">(() => {
  if (!applyPreflight.value?.ok) {
    return "error";
  }
  return applyPreflight.value.warnings > 0 ? "warning" : "success";
});
const applyReadinessSummary = computed(() => {
  if (!applyPreflight.value) {
    return "";
  }
  if (applyPreflight.value.failures > 0) {
    return `${pluralize(applyPreflight.value.failures, "failed check")} must be fixed before applying.`;
  }
  if (applyPreflight.value.warnings > 0) {
    return `${pluralize(applyPreflight.value.warnings, "warning")} to review before applying.`;
  }
  return "Required resources are reachable.";
});
const applyVisible = computed(() => updates.plan?.status === "ready");
const applyAvailable = computed(() => applyVisible.value && !!updates.plan?.can_apply);
const applyDisabled = computed(() => !applyAvailable.value || updates.loading);
const applyButtonLabel = computed(() =>
  updates.plan?.selected_line_numbers.length
    ? `Apply ${pluralize(updates.plan.selected_line_numbers.length, "update")}`
    : "Apply selected updates",
);
const cleanupItems = computed(() => updates.plan?.cleanup.items ?? []);
const cleanupAvailable = computed(() => cleanupItems.value.length > 0);
const visiblePlanIssues = computed(() => {
  const issues = updates.plan?.issues ?? [];
  if (!cleanupItems.value.length) {
    return issues;
  }
  const cleanupKeys = new Set(cleanupItems.value.flatMap(cleanupIssueKeys));
  return issues.filter((issue) => !issueHiddenByCleanupPreview(issue, cleanupKeys));
});
const digestPinLabelApprovalIssues = computed(() =>
  visiblePlanIssues.value.filter(
    (issue) =>
      issue.code === "compose-digest-pin-label-rewrite-unapproved" &&
      digestPinLabelApprovalFromIssue(issue) !== null,
  ),
);
const planDigestPinLabelRewrites = computed(() =>
  planDigestPinUpdates.value.flatMap(({ stack, update }) =>
    (update.label_rewrites ?? []).map((rewrite) => ({ stack, rewrite })),
  ),
);
const unmatchedReviewSummary = computed(() =>
  staleReviewSummary(unmatchedItems.value, "pending line", "pending lines"),
);
const unmatchedReviewCountLabel = computed(() =>
  reviewCountLabel(unmatchedItems.value.length, "item"),
);
const unmatchedIssueSummary = computed(() =>
  staleIssueSummary(unmatchedItems.value),
);
const cleanupAssistantFindings = computed(() =>
  assistantDetailList(cleanupItems.value, "preflight_findings"),
);
const cleanupAssistantReasons = computed(() =>
  assistantDetailList(cleanupItems.value, "possible_reasons"),
);
const cleanupAssistantActions = computed(() =>
  assistantDetailList(cleanupItems.value, "recommended_actions"),
);
const cleanupReviewSummary = computed(() => {
  const summary = staleReviewSummary(cleanupItems.value, "entry", "entries");
  return summary
    ? `${summary} Cleanup only removes WUD pending lines.`
    : "Cleanup only removes WUD pending lines.";
});
const cleanupButtonLabel = computed(() =>
  `Remove ${pluralize(cleanupItems.value.length, "unmatched entry", "unmatched entries")}`,
);
const cleanupDisabled = computed(
  () => !updates.plan?.cleanup.can_remove_unmatched || updates.loading,
);
const cleanupDisabledMessage = computed(() => {
  if (!updates.plan || !cleanupAvailable.value || updates.plan.cleanup.can_remove_unmatched) {
    return "";
  }
  if (!auth.session?.mutations_enabled) {
    return "Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to remove stale pending entries.";
  }
  return "These pending entries cannot be removed right now.";
});
const pendingCleanupMessage = computed(() => {
  if (!updates.pendingCleanup) {
    return "";
  }
  return `${pluralize(updates.pendingCleanup.removed_count, "pending entry", "pending entries")} removed from ${pendingSourceLabel.value}.`;
});
const removalItems = computed(() => updates.pendingRemovalPlan?.lines ?? []);
const removalButtonLabel = computed(() =>
  `Remove ${pluralize(selectedLineNumbers.value.length, "selected entry", "selected entries")}`,
);
const removalConfirmButtonLabel = computed(() =>
  `Remove ${pluralize(removalItems.value.length, "selected entry", "selected entries")}`,
);
const removalDisabled = computed(
  () => !updates.pendingRemovalPlan?.can_remove || updates.loading,
);
const mutationDisabledMessage = computed(() => {
  if (!updates.plan || updates.plan.status !== "ready" || updates.plan.can_apply) {
    return "";
  }
  if (!auth.session?.mutations_enabled) {
    return "Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to apply updates.";
  }
  if (!updates.plan.apply_preflight.ok) {
    return "Fix the failed apply readiness check before applying updates.";
  }
  return "This plan cannot be applied.";
});
const selectedStackNames = computed(() =>
  stackGroups.value
    .filter((group) => group.line_numbers.some((lineNo) => selectedLineSet.value.has(lineNo)))
    .map((group) => group.name),
);
const selectedUpdateContext = computed(() => {
  if (selectedStackNames.value.length === 1) {
    return selectedStackNames.value[0];
  }
  if (selectedStackNames.value.length > 1) {
    return pluralize(selectedStackNames.value.length, "stack");
  }
  return "selected updates";
});
const batchSummaryLabel = computed(() => {
  const count = pluralize(selectedLineNumbers.value.length, "update");
  return selectedUpdateContext.value === "selected updates"
    ? `${count} selected`
    : `${count} selected in ${selectedUpdateContext.value}`;
});
const planLines = computed(() =>
  updates.plan?.stacks.flatMap((stack) =>
    stack.lines.map((line) => ({ stack: stack.name, line })),
  ) ?? [],
);
const planActions = computed(() =>
  updates.plan?.stacks.flatMap((stack) =>
    stack.actions.map((action) => ({ stack: stack.name, action })),
  ) ?? [],
);
const planTagUpdates = computed(() =>
  updates.plan?.stacks.flatMap((stack) =>
    stack.tag_updates.map((update) => ({ stack: stack.name, update })),
  ) ?? [],
);
const planDigestPinUpdates = computed(() =>
  updates.plan?.stacks.flatMap((stack) =>
    (stack.digest_pin_updates ?? []).map((update) => ({ stack: stack.name, update })),
  ) ?? [],
);
const plannedTagRewriteLines = computed(() =>
  planLines.value.filter(
    ({ line }) => Boolean(line.desired_tag) && line.action !== "digest-pin",
  ),
);
const plannedDigestPinLines = computed(() =>
  planLines.value.filter(({ line }) => line.action === "digest-pin"),
);
const visibleTagRewriteCount = computed(
  () => planTagUpdates.value.length || plannedTagRewriteLines.value.length,
);
const visibleDigestPinCount = computed(
  () => planDigestPinUpdates.value.length || plannedDigestPinLines.value.length,
);
const preflightTagRewriteNotice = computed(() => {
  if (!updateIntent.value?.allowTagUpdates || !visibleTagRewriteCount.value || !updates.plan) {
    return "";
  }
  return `${pluralize(visibleTagRewriteCount.value, "tag rewrite")} will be applied before recreating selected services.`;
});
const preflightDigestPinNotice = computed(() => {
  if (!visibleDigestPinCount.value || !updates.plan?.digest_pin_updates) {
    return "";
  }
  return `${pluralize(visibleDigestPinCount.value, "digest-pin rewrite")} will pin approved tag updates after pull verification.`;
});
const applyJobAlertType = computed(() => {
  if (updates.applyJob?.status === "failure") {
    return "error";
  }
  if (updates.applyJob?.status === "success") {
    return "success";
  }
  return "info";
});
const applyJobActive = computed(
  () => Boolean(updates.applyJob && !terminalJobStatuses.has(updates.applyJob.status)),
);
const applyJobSucceeded = computed(() => updates.applyJob?.status === "success");
const applyJobUpdateCount = computed(
  () =>
    updates.applyJob?.selected_line_numbers.length ||
    applyJobSnapshot.value?.lines.length ||
    0,
);
const applyJobUpdateLabel = computed(() =>
  pluralize(applyJobUpdateCount.value, "update"),
);
const applyJobTitle = computed(() => {
  if (!updates.applyJob) {
    return "";
  }
  if (updates.applyJob.status === "queued" || updates.applyJob.status === "running") {
    return `Applying ${applyJobUpdateLabel.value}`;
  }
  if (updates.applyJob.status === "success") {
    return "Apply complete";
  }
  if (updates.applyJob.status === "failure") {
    return "Apply failed";
  }
  return "Apply job";
});
const applyJobStatusMessage = computed(() => {
  if (!updates.applyJob) {
    return "";
  }
  if (updates.applyJob.status === "queued") {
    return "Waiting for the updater job to start.";
  }
  if (updates.applyJob.status === "running") {
    return "Updater command is running.";
  }
  if (updates.applyJob.status === "success") {
    return `${applyJobUpdateLabel.value} finished. Pending updates and run history were refreshed.`;
  }
  if (updates.applyJob.error) {
    return updates.applyJob.error;
  }
  return "Updater stopped before completing the selected updates.";
});
const applyJobStartedLabel = computed(() => {
  if (!updates.applyJob) {
    return "";
  }
  return updates.applyJob.started_at || "Queued";
});
const applyJobSnapshotLines = computed(() => applyJobSnapshot.value?.lines ?? []);
const applyJobImpactLabel = computed(() => {
  if (!applyJobSnapshot.value) {
    return "";
  }
  const serviceCount =
    applyJobSnapshot.value.serviceCount || applyJobSnapshotLines.value.length;
  const stackCount = applyJobSnapshot.value.stackCount;
  if (stackCount > 1) {
    return `${pluralize(serviceCount, "service")} across ${pluralize(stackCount, "stack")}`;
  }
  return `${pluralize(serviceCount, "service")} in ${applyJobSnapshot.value.contextLabel}`;
});
const applyJobLogText = computed(() => updates.applyJobLog?.content ?? "");
const applyJobLogTitle = computed(
  () => updates.applyJobLog?.log_file || updates.applyJob?.log_file || "Live log",
);
const applyJobLiveLogVisible = computed(
  () => applyJobActive.value || applyJobLiveLogExpanded.value,
);
const applyJobLiveLogToggleLabel = computed(() =>
  applyJobLiveLogExpanded.value ? "Hide live log output" : "Show live log output",
);
const applyJobLatestLogLine = computed(() => {
  const lines = applyJobLogText.value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  return lines.at(-1) ?? "";
});
const applyJobLatestLogMessage = computed(() => {
  if (applyJobLatestLogLine.value) {
    return applyJobLatestLogLine.value;
  }
  return applyJobActive.value ? "Waiting for log output." : "No log output captured.";
});
const applyJobLogEmptyMessage = computed(() =>
  applyJobActive.value ? "Waiting for log output." : "No live log was captured.",
);
const applyJobLogWaiting = computed(() => {
  const log = updates.applyJobLog;
  if (!log || log.error) {
    return !log;
  }
  return !log.exists && !log.content;
});
const displayApplyJobProgressByPhase = computed(() => {
  const displayEvents = new Map<string, ApplyJobProgressEvent>();
  for (const event of updates.applyJob?.progress ?? []) {
    displayEvents.set(
      event.phase,
      displayProgressEvent(displayEvents.get(event.phase) ?? null, event),
    );
  }
  return displayEvents;
});
const applyJobProgressSteps = computed<ApplyJobProgressStep[]>(() =>
  applyJobProgressPhases.map((phase) => {
    const event = displayApplyJobProgressByPhase.value.get(phase.key) ?? null;
    const status = event?.status ?? "pending";
    return {
      ...phase,
      status,
      statusLabel: progressStatusLabel(status),
      message: event?.message || phase.waitingMessage,
      detail: progressEventDetail(event),
      event,
    };
  }),
);
const applyJobProgressSummary = computed(() => {
  const progress = updates.applyJob?.progress ?? [];
  if (!progress.length) {
    return applyJobActive.value ? "Starting" : "No progress events";
  }
  const failed = applyJobProgressSteps.value.find((step) => step.status === "failure");
  if (failed) {
    return `${failed.label} failed`;
  }
  const running = applyJobProgressSteps.value.find((step) => step.status === "running");
  if (running) {
    return running.label;
  }
  const complete = displayApplyJobProgressByPhase.value.get("completion");
  if (complete?.status === "success") {
    return "Complete";
  }
  return `${progress.length} updates`;
});
const applyJobCurrentStep = computed<ApplyJobProgressStep | null>(() => {
  const failed = applyJobProgressSteps.value.find((step) => step.status === "failure");
  if (failed) {
    return failed;
  }
  const running = applyJobProgressSteps.value.find((step) => step.status === "running");
  if (running) {
    return running;
  }
  const completion = displayApplyJobProgressByPhase.value.get("completion");
  if (completion?.status === "success") {
    return (
      applyJobProgressSteps.value.find((step) => step.key === "completion") ?? null
    );
  }
  return [...applyJobProgressSteps.value].reverse().find((step) => step.event) ?? null;
});
const applyJobNowTitle = computed(() => {
  if (!updates.applyJob) {
    return "";
  }
  const step = applyJobCurrentStep.value;
  if (updates.applyJob.status === "failure") {
    return step ? `Failed: ${step.label}` : "Apply failed";
  }
  if (updates.applyJob.status === "success") {
    return "Update complete";
  }
  if (step?.status === "running") {
    return `Running: ${step.label}`;
  }
  if (step?.status === "success") {
    return `Completed: ${step.label}`;
  }
  if (updates.applyJob.status === "queued") {
    return "Queued to start";
  }
  return "Starting updater";
});
const applyJobNowMessage = computed(() => {
  if (!updates.applyJob) {
    return "";
  }
  if (updates.applyJob.status === "failure" && updates.applyJob.error) {
    return updates.applyJob.error;
  }
  return applyJobCurrentStep.value?.message || applyJobStatusMessage.value;
});
const applyJobNowDetail = computed(() =>
  applyJobCurrentStep.value?.detail || applyJobImpactLabel.value,
);
const applyJobNowDescriptionIds = computed(() =>
  applyJobNowDetail.value
    ? "apply-job-now-message apply-job-now-detail"
    : "apply-job-now-message",
);
const applyJobNowStatusLabel = computed(() => {
  if (updates.applyJob?.status === "success") {
    return "Complete";
  }
  if (updates.applyJob?.status === "failure") {
    return "Failed";
  }
  return applyJobProgressSummary.value;
});
const applyJobPanelStatusLabel = computed(() => {
  if (updates.applyJob?.status === "queued") {
    return "Queued";
  }
  if (updates.applyJob?.status === "running") {
    return "Running";
  }
  if (updates.applyJob?.status === "success") {
    return "Complete";
  }
  if (updates.applyJob?.status === "failure") {
    return "Failed";
  }
  return "Job";
});

function rowKey(row: PendingItem): number {
  return row.line_no;
}

function progressStatusLabel(status: ApplyJobProgressStep["status"]): string {
  if (status === "running") {
    return "Running";
  }
  if (status === "success") {
    return "Done";
  }
  if (status === "failure") {
    return "Failed";
  }
  if (status === "skipped") {
    return "Skipped";
  }
  return "Waiting";
}

function progressTagType(
  status: ApplyJobProgressStep["status"],
): "default" | "success" | "warning" | "error" {
  if (status === "success") {
    return "success";
  }
  if (status === "running") {
    return "warning";
  }
  if (status === "failure") {
    return "error";
  }
  return "default";
}

function displayProgressEvent(
  current: ApplyJobProgressEvent | null,
  next: ApplyJobProgressEvent,
): ApplyJobProgressEvent {
  if (!current || current.status !== "failure") {
    return next;
  }
  if (next.status === "failure") {
    return next;
  }
  return current;
}

function progressEventDetail(event: ApplyJobProgressEvent | null): string {
  if (!event) {
    return "";
  }
  const parts = [];
  if (event.stack) {
    parts.push(event.stack);
  }
  if (event.services.length) {
    parts.push(event.services.join(", "));
  }
  if (event.line_numbers.length) {
    parts.push(`lines ${event.line_numbers.join(", ")}`);
  }
  return parts.join(" / ");
}

function displayValue(value: string): string {
  return value || "None";
}

function displayDigest(value: string): string {
  if (!value || value.length <= 36) {
    return value;
  }
  return `${value.slice(0, 20)}...${value.slice(-12)}`;
}

function previewImageLabel(value: string): string {
  return value.includes("sha256:") ? displayDigest(value) : value;
}

function releaseNoteFor(item: PendingItem): ReleaseNoteInfo | null {
  return releaseNotesByLine.value.get(item.line_no) ?? null;
}

function uniqueSorted(values: number[]): number[] {
  return [...new Set(values)].sort((left, right) => left - right);
}

function fileName(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || trimmed === "Pending file") {
    return "Pending file";
  }
  return trimmed.split(/[\\/]/).filter(Boolean).at(-1) ?? trimmed;
}

function releaseNoteStatus(note: ReleaseNoteInfo | null): string {
  if (note?.links.length) {
    return "";
  }
  if (updates.releaseNotesLoading) {
    return "Checking...";
  }
  if (note?.status === "unsupported") {
    return "Unavailable";
  }
  if (note?.status === "error") {
    return "Check failed";
  }
  return "Not checked";
}

function releaseNoteReason(note: ReleaseNoteInfo | null): string {
  const error = note?.error.trim() ?? "";
  if (!error) {
    return "";
  }
  const missingMapping = error.match(/^missing LSIO upstream mapping for (.+)$/);
  if (missingMapping?.[1]) {
    return `Add a LinuxServer.io upstream map entry for ${missingMapping[1]}.`;
  }
  if (error === "no supported GitHub release source found") {
    return "Only GHCR and mapped LinuxServer.io images have release-note links.";
  }
  return error;
}

function renderReleaseNotes(row: PendingItem) {
  const note = releaseNoteFor(row);
  const reason = releaseNoteReason(note);
  if (!note?.links.length) {
    return h(
      "span",
      {
        class: "release-notes-muted",
        title: reason || undefined,
      },
      [
        h("span", { class: "release-notes-status" }, releaseNoteStatus(note)),
        reason ? h("span", { class: "release-notes-reason" }, reason) : null,
      ],
    );
  }
  return h("div", { class: "release-notes-cell" }, [
    ...note.links.map((link) =>
      h(
        "a",
        {
          key: `${row.line_no}-${link.kind}-${link.url}`,
          class: "release-note-link",
          href: link.url,
          target: "_blank",
          rel: "noreferrer",
        },
        [
          link.label,
          h(ExternalLink, {
            size: 14,
            "aria-hidden": "true",
          }),
        ],
      ),
    ),
    note.breaking ? breakingCue(note) : null,
  ]);
}

function getPendingGroupedItem(lineNo: number): PendingGroupedItem | undefined {
  if (!updates.pending?.grouping) return undefined;
  for (const group of updates.pending.grouping.groups) {
    const found = group.items.find((i) => i.line_no === lineNo);
    if (found) return found;
  }
  return updates.pending.grouping.unmatched.find((i) => i.line_no === lineNo);
}

function pendingServiceKeys(row: PendingItem): string[] {
  if (!updates.pending?.grouping) return [];
  const keys: string[] = [];
  for (const group of updates.pending.grouping.groups) {
    const item = group.items.find((i) => i.line_no === row.line_no);
    if (!item) continue;
    for (const service of item.services) {
      keys.push(`${group.name}/${service}`);
    }
  }
  const unmatched = updates.pending.grouping.unmatched.find(
    (item) => item.line_no === row.line_no,
  );
  if (unmatched?.diagnostic?.stack && unmatched.diagnostic.service) {
    keys.push(`${unmatched.diagnostic.stack}/${unmatched.diagnostic.service}`);
  }
  return [...new Set(keys)];
}

function riskCues(row: PendingItem): SafetyCue[] {
  const groupedItem = getPendingGroupedItem(row.line_no);
  const serviceKeys = pendingServiceKeys(row);
  const cues: SafetyCue[] = [];
  const addCue = (key: string, label: string, type: SafetyCue["type"]) => {
    cues.push({ key, label, type });
  };

  const parseVersion = (tag: string) => {
    const m = tag.match(/^v?(\d+)\.(\d+)(?:\.(\d+))?/);
    if (!m) return null;
    return {
      major: parseInt(m[1]!, 10),
      minor: parseInt(m[2]!, 10),
      patch: m[3] ? parseInt(m[3]!, 10) : 0,
    };
  };

  if (row.current_tag && row.desired_tag && row.current_tag !== row.desired_tag) {
    const c = parseVersion(row.current_tag);
    const d = parseVersion(row.desired_tag);
    if (c && d) {
      if (c.major !== d.major) addCue("major-bump", "Major bump", "error");
      else if (c.minor !== d.minor) addCue("minor-bump", "Minor bump", "warning");
      else if (c.patch !== d.patch) addCue("patch-bump", "Patch bump", "info");
    }
  }

  if (!row.desired_tag && row.digest) {
    addCue("digest-only", "Digest-only", "info");
  }

  if (row.desired_tag === "latest" || (!row.desired_tag && row.current_tag === "latest")) {
    addCue("mutable-latest", "Mutable latest", "warning");
  }

  if (groupedItem?.action === "recreate_stack") {
    addCue("stack-restart", "Stack restart", "warning");
  }

  const note = releaseNoteFor(row);
  if (note?.breaking) {
    addCue("possible-breaking", "Possible breaking", "warning");
  }
  if (
    updates.releaseNotes &&
    !updates.releaseNotesLoading &&
    (!note?.links.length || note.status === "error" || note.status === "unsupported")
  ) {
    addCue("no-release-notes", "No release notes", "warning");
  }

  if (settings.snoozes.some((s) => serviceKeys.includes(s.service_key))) {
    addCue("snoozed", "Snoozed", "default");
  }
  const policy = settings.servicePolicies.find((p) => serviceKeys.includes(p.service_key));
  if (policy?.auto_update) {
    addCue("auto-update", "Auto-update", "success");
  }

  return cues;
}

function renderRiskBadges(row: PendingItem) {
  const badges = riskCues(row).map((cue) =>
    h(NTag, { key: cue.key, size: "small", type: cue.type, class: "safety-badge" }, () => cue.label),
  );
  if (badges.length === 0) return h("span", { class: "risk-badges-muted" }, "None");
  return h("div", { class: "risk-badges-container" }, badges);
}

function breakingCue(note: ReleaseNoteInfo) {
  return h(
    "span",
    {
      class: "release-breaking-cue",
      title: note.breaking_reasons.join(" "),
      "aria-label": "Possible breaking change",
    },
    [
      h(AlertTriangle, {
        size: 14,
        "aria-hidden": "true",
      }),
      "Possible breaking change",
    ],
  );
}

function tagOverrideValue(item: PendingItem): string {
  return tagOverrides.value[item.line_no] ?? item.desired_tag;
}

function pendingItemsForLines(lineNumbers: number[]): PendingItem[] {
  const lineSet = new Set(lineNumbers);
  return (updates.pending?.items ?? []).filter((item) => lineSet.has(item.line_no));
}

function tagOverrideErrorForLines(lineNumbers: number[]): string {
  for (const item of pendingItemsForLines(lineNumbers)) {
    if (!item.desired_tag) {
      continue;
    }
    const tag = tagOverrideValue(item).trim();
    if (!tagValuePattern.test(tag)) {
      return `${item.image} has an invalid new tag. Use a Docker tag value like ${item.desired_tag}.`;
    }
  }
  return "";
}

function tagOverridesForLines(lineNumbers: number[]): TagOverrideRequest[] {
  return pendingItemsForLines(lineNumbers)
    .filter((item) => item.desired_tag)
    .map((item) => ({
      line_no: item.line_no,
      tag: tagOverrideValue(item).trim(),
    }))
    .filter((item) => {
      const original = updates.pending?.items.find(
        (pendingItem) => pendingItem.line_no === item.line_no,
      );
      return original !== undefined && item.tag !== original.desired_tag;
    });
}

function lineNumbersHaveTagUpdates(lineNumbers: number[]): boolean {
  return pendingItemsForLines(lineNumbers).some((item) => Boolean(item.desired_tag));
}

function clearPreflight(): void {
  showPreflightModal.value = false;
  showCleanupModal.value = false;
  showRemovalModal.value = false;
  updateIntent.value = null;
  updates.clearPlan();
}

function updateTagOverride(item: PendingItem, value: string): void {
  tagOverrides.value = {
    ...tagOverrides.value,
    [item.line_no]: value,
  };
  if (!selectedLineSet.value.has(item.line_no)) {
    selectedLineNumbers.value = uniqueSorted([
      ...selectedLineNumbers.value,
      item.line_no,
    ]);
  }
  clearPreflight();
}

function updateCheckedRowKeys(keys: DataTableRowKey[]): void {
  selectedLineNumbers.value = uniqueSorted(
    keys.map((key) => Number(key)).filter((key) => Number.isFinite(key)),
  );
  clearPreflight();
}

function toggleLine(lineNo: number, checked: boolean): void {
  const selected = new Set(selectedLineNumbers.value);
  if (checked) {
    selected.add(lineNo);
  } else {
    selected.delete(lineNo);
  }
  selectedLineNumbers.value = [...selected].sort((left, right) => left - right);
  clearPreflight();
}

function selectAllVisible(): void {
  selectedLineNumbers.value = [...selectableLineNumbers.value];
  clearPreflight();
}

function clearSelection(): void {
  selectedLineNumbers.value = [];
  clearPreflight();
}

function stackSelected(group: PendingStackGroup): boolean {
  return (
    group.line_numbers.length > 0 &&
    group.line_numbers.every((lineNo) => selectedLineSet.value.has(lineNo))
  );
}

function stackIndeterminate(group: PendingStackGroup): boolean {
  return (
    group.line_numbers.some((lineNo) => selectedLineSet.value.has(lineNo)) &&
    !stackSelected(group)
  );
}

function stackHasSelection(group: PendingStackGroup): boolean {
  return group.line_numbers.some((lineNo) => selectedLineSet.value.has(lineNo));
}

function toggleStack(group: PendingStackGroup, checked: boolean): void {
  const selected = new Set(selectedLineNumbers.value);
  for (const lineNo of group.line_numbers) {
    if (checked) {
      selected.add(lineNo);
    } else {
      selected.delete(lineNo);
    }
  }
  selectedLineNumbers.value = uniqueSorted([...selected]);
  clearPreflight();
}

function updateDisabled(lineNumbers: number[]): boolean {
  return (
    lineNumbers.length === 0 ||
    updates.loading ||
    Boolean(tagOverrideErrorForLines(lineNumbers))
  );
}

async function startSelectedUpdate(): Promise<void> {
  await startUpdateFlow({
    title: "Preview selected plan",
    contextLabel: selectedUpdateContext.value,
    lineNumbers: selectedLineNumbers.value,
  });
}

async function startStackUpdate(group: PendingStackGroup): Promise<void> {
  await startUpdateFlow({
    title: `Preview ${group.name} plan`,
    contextLabel: group.name,
    lineNumbers: group.line_numbers,
  });
}

async function startUpdateFlow(input: {
  title: string;
  contextLabel: string;
  lineNumbers: number[];
}): Promise<void> {
  const lineNumbers = uniqueSorted(input.lineNumbers);
  if (lineNumbers.length === 0 || updates.loading) {
    return;
  }
  selectedLineNumbers.value = lineNumbers;
  const validationError = tagOverrideErrorForLines(lineNumbers);
  if (validationError) {
    clearPreflight();
    return;
  }

  const intent: UpdateIntent = {
    title: input.title,
    contextLabel: input.contextLabel,
    lineNumbers,
    allowTagUpdates: lineNumbersHaveTagUpdates(lineNumbers),
    tagOverrides: tagOverridesForLines(lineNumbers),
    digestPinLabelRewriteApprovals: [],
  };
  updateIntent.value = intent;
  try {
    await updates.createPlan(
      intent.lineNumbers,
      intent.allowTagUpdates,
      intent.tagOverrides,
      intent.digestPinLabelRewriteApprovals,
    );
  } catch {
    showPreflightModal.value = false;
    updateIntent.value = null;
    return;
  }
  if (updates.plan) {
    showPreflightModal.value = true;
  }
}

function closePreflightModal(): void {
  clearPreflight();
}

function openCleanupModal(): void {
  if (!cleanupAvailable.value) {
    return;
  }
  showCleanupModal.value = true;
}

function closeCleanupModal(): void {
  showCleanupModal.value = false;
}

async function startSelectedRemoval(): Promise<void> {
  const lineNumbers = uniqueSorted(selectedLineNumbers.value);
  if (lineNumbers.length === 0 || removeSelectedDisabled.value) {
    return;
  }
  selectedLineNumbers.value = lineNumbers;
  try {
    await updates.createRemovalPlan(lineNumbers);
  } catch {
    showRemovalModal.value = false;
    return;
  }
  if (updates.pendingRemovalPlan?.lines.length) {
    showRemovalModal.value = true;
  }
}

function closeRemovalModal(): void {
  showRemovalModal.value = false;
  updates.clearPlan();
}

async function confirmSelectedRemoval(): Promise<void> {
  const removal = updates.pendingRemovalPlan;
  if (!removal?.removal_id || removalDisabled.value || !removal.lines.length) {
    return;
  }
  const result = await updates.removeSelectedPending(
    removal.removal_id,
    removal.lines.map((item) => ({ line_no: item.line_no, raw: item.raw })),
  );
  const removedLines = new Set(result.removed.map((item) => item.line_no));
  selectedLineNumbers.value = selectedLineNumbers.value.filter(
    (lineNo) => !removedLines.has(lineNo),
  );
  showRemovalModal.value = false;
  await Promise.all([
    loadPendingAndReleaseNotes({ preserveCleanup: true }),
    runs.loadRuns(),
  ]);
}

async function confirmCleanup(): Promise<void> {
  const cleanup = updates.plan?.cleanup;
  if (!cleanup?.cleanup_id || cleanupDisabled.value || !cleanup.items.length) {
    return;
  }
  const result = await updates.cleanupPending(
    cleanup.cleanup_id,
    cleanup.items.map((item) => ({ line_no: item.line_no, raw: item.raw })),
  );
  const removedLines = new Set(result.removed.map((item) => item.line_no));
  selectedLineNumbers.value = selectedLineNumbers.value.filter(
    (lineNo) => !removedLines.has(lineNo),
  );
  showCleanupModal.value = false;
  showPreflightModal.value = false;
  updateIntent.value = null;
  await Promise.all([
    loadPendingAndReleaseNotes({ preserveCleanup: true }),
    runs.loadRuns(),
  ]);
}

async function confirmApply(): Promise<void> {
  if (!updates.plan || applyDisabled.value) {
    return;
  }
  const intent = updateIntent.value;
  const lineNumbers = updates.plan.selected_line_numbers;
  const snapshot = createApplyJobSnapshot();
  const job = await updates.createJob(
    updates.plan.plan_id,
    lineNumbers,
    intent?.allowTagUpdates ?? lineNumbersHaveTagUpdates(lineNumbers),
    intent?.tagOverrides ?? tagOverridesForLines(lineNumbers),
    intent?.digestPinLabelRewriteApprovals ?? [],
  );
  applyJobSnapshot.value = snapshot;
  subscribeApplyJob(job.job_id);
  showPreflightModal.value = false;
  updateIntent.value = null;
  await focusApplyJobPanel();
}

function subscribeApplyJob(jobId: string): void {
  closeJobStream();
  const source = webApi.openJobStream(jobId);
  jobEventSource.value = source;
  source.addEventListener("job", (event) => {
    void handleJobEvent(event as MessageEvent<string>);
  });
  source.addEventListener("progress", (event) => {
    handleJobProgressEvent(event as MessageEvent<string>);
  });
  source.addEventListener("log", (event) => {
    void handleJobLogEvent(event as MessageEvent<string>);
  });
  source.onerror = () => {
    if (updates.applyJob && terminalJobStatuses.has(updates.applyJob.status)) {
      closeJobStream();
      return;
    }
    void recoverOrRefreshApplyJob(jobId);
  };
}

async function handleJobEvent(event: MessageEvent<string>): Promise<void> {
  let job: ApplyJobResponse;
  try {
    job = JSON.parse(event.data) as ApplyJobResponse;
  } catch {
    updates.setError("Job status stream returned invalid data.");
    closeJobStream();
    return;
  }
  updates.setApplyJob(job);
  if (!terminalJobStatuses.has(job.status)) {
    return;
  }
  closeJobStream();
  await loadTerminalApplyJobLogIfMissing(job);
  await refreshAfterTerminalJob();
}

function handleJobProgressEvent(event: MessageEvent<string>): void {
  let progress: ApplyJobProgressEvent;
  try {
    progress = JSON.parse(event.data) as ApplyJobProgressEvent;
  } catch {
    updates.setError("Job progress stream returned invalid data.");
    return;
  }
  const job = updates.applyJob;
  if (!job || job.job_id !== progress.job_id) {
    return;
  }
  const progressEvents = job.progress ?? [];
  if (progressEvents.some((item) => progressEventKey(item) === progressEventKey(progress))) {
    return;
  }
  updates.setApplyJob({
    ...job,
    progress: [...progressEvents, progress],
  });
}

async function loadTerminalApplyJobLogIfMissing(
  job: ApplyJobResponse | null = updates.applyJob,
): Promise<void> {
  if (
    !job?.run_id ||
    !terminalJobStatuses.has(job.status) ||
    updates.applyJobLog?.content ||
    applyJobRunLogFallbackRunId.value === job.run_id
  ) {
    return;
  }
  applyJobRunLogFallbackRunId.value = job.run_id;
  await updates.loadApplyJobLogFromRun(job);
}

async function handleJobLogEvent(event: MessageEvent<string>): Promise<void> {
  let log: ApplyJobLogResponse;
  try {
    log = JSON.parse(event.data) as ApplyJobLogResponse;
  } catch {
    updates.setError("Job log stream returned invalid data.");
    return;
  }
  const panelShouldScroll = shouldAutoScrollLog(applyJobPanelLogRef.value);
  updates.setApplyJobLog(log);
  await nextTick();
  if (panelShouldScroll) {
    scrollLogToBottom(applyJobPanelLogRef.value);
  }
}

function closeJobStream(): void {
  jobEventSource.value?.close();
  jobEventSource.value = null;
}

function progressEventKey(event: ApplyJobProgressEvent): string {
  return [
    event.created_at,
    event.phase,
    event.status,
    event.stack,
    event.message,
  ].join("\u0000");
}

async function recoverOrRefreshApplyJob(jobId: string): Promise<void> {
  const job = await updates
    .loadApplyJob(jobId, { recoverMissing: true })
    .catch(() => undefined);
  if (job === undefined) {
    return;
  }
  if (job === null) {
    closeJobStream();
    await runs.loadRuns().catch(() => undefined);
    return;
  }
  if (terminalJobStatuses.has(job.status)) {
    closeJobStream();
    await refreshAfterTerminalJob();
  }
}

async function reconnectObservedApplyJob(): Promise<void> {
  if (!updates.rememberedApplyJobId) {
    return;
  }
  const job = await updates
    .loadApplyJob(updates.rememberedApplyJobId, { recoverMissing: true })
    .catch(() => undefined);
  if (job === undefined) {
    return;
  }
  if (job === null) {
    await runs.loadRuns().catch(() => undefined);
    return;
  }
  if (terminalJobStatuses.has(job.status)) {
    await refreshAfterTerminalJob();
    return;
  }
  subscribeApplyJob(job.job_id);
}

async function refreshAfterTerminalJob(): Promise<void> {
  await Promise.all([loadPendingAndReleaseNotes(), runs.loadRuns()]);
}

function createApplyJobSnapshot(): ApplyJobPlanSnapshot | null {
  if (!updates.plan) {
    return null;
  }
  return {
    contextLabel: planContextLabel.value,
    serviceCount:
      updates.plan.summary.service_count ||
      updates.plan.summary.target_count ||
      planLines.value.length,
    stackCount: updates.plan.summary.stack_count,
    sourceFile: updates.plan.source_file,
    lines: planLines.value.map(({ stack, line }) => ({
      key: `${stack}-${line.line_no}-${line.service}`,
      lineNo: line.line_no,
      serviceLabel: planLineServiceLabel(stack, line),
      tagRewriteLabel: planLineTagRewriteLabel(line),
      digestPinLabel: planLineDigestPinLabel(line),
      composeImage: line.compose_image,
      targetImage: line.target_image,
    })),
  };
}

async function focusApplyJobPanel(): Promise<void> {
  await nextTick();
  const panel = applyJobPanelRef.value;
  if (!panel) {
    return;
  }
  panel.scrollIntoView?.({
    block: "start",
    behavior: prefersReducedMotion() ? "auto" : "smooth",
  });
  panel.focus({ preventScroll: true });
}

function shouldAutoScrollLog(element: HTMLElement | null): boolean {
  if (!element) {
    return true;
  }
  const distanceFromBottom =
    element.scrollHeight - element.scrollTop - element.clientHeight;
  return distanceFromBottom <= 48;
}

function scrollLogToBottom(element: HTMLElement | null): void {
  if (!element) {
    return;
  }
  element.scrollTop = element.scrollHeight;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function actionCommand(action: PlanAction): string {
  return action.args.length ? action.args.join(" ") : action.description;
}

function issueType(issue: PlanIssue): "error" | "warning" | "info" {
  return issue.severity === "error" ? "error" : "warning";
}

function applyPreflightCheckType(
  status: ApplyPreflightStatus,
): "success" | "warning" | "error" {
  if (status === "PASS") {
    return "success";
  }
  if (status === "WARN") {
    return "warning";
  }
  return "error";
}

function applyPreflightCheckLabel(status: ApplyPreflightStatus): string {
  if (status === "PASS") {
    return "Pass";
  }
  if (status === "WARN") {
    return "Warn";
  }
  return "Fail";
}

function applyPreflightCheckDetail(check: ApplyPreflightCheck): string {
  if (check.status === "PASS") {
    return "";
  }
  if (check.code === "selected-services-matched" && check.detail === "unmatched") {
    return cleanupItems.value.length
      ? staleReviewSummary(cleanupItems.value, "entry", "entries")
      : "Selected update is unmatched.";
  }
  return check.detail;
}

function cleanupIssueKeys(item: PlanCleanupItem): string[] {
  return [item.reason, item.diagnostic?.code]
    .filter((code): code is string => Boolean(code))
    .map((code) => `${item.line_no}:${code}`);
}

function issueHiddenByCleanupPreview(
  issue: PlanIssue,
  cleanupKeys: ReadonlySet<string>,
): boolean {
  if (issue.line_no === null) {
    return false;
  }
  return cleanupKeys.has(`${issue.line_no}:${issue.code}`);
}

function issueLabel(issue: PlanIssue): string {
  const target = [
    issue.line_no ? `line ${issue.line_no}` : "",
    issue.stack,
    issue.service,
  ]
    .filter(Boolean)
    .join(" / ");
  return target ? `${target}: ${issue.message}` : issue.message;
}

function issueHint(issue: PlanIssue): string {
  return issue.hint || "";
}

function issueDetailString(issue: PlanIssue, key: string): string {
  const value = issue.details[key];
  return typeof value === "string" ? value : "";
}

function digestPinLabelApprovalFromIssue(
  issue: PlanIssue,
): DigestPinLabelRewriteApprovalRequest | null {
  if (issue.code !== "compose-digest-pin-label-rewrite-unapproved") {
    return null;
  }
  const approval = {
    stack: issueDetailString(issue, "stack") || issue.stack,
    service: issueDetailString(issue, "service") || issue.service,
    label_key: issueDetailString(issue, "label_key"),
    current_label_value: issueDetailString(issue, "current_label_value"),
    planned_tag: issueDetailString(issue, "planned_tag"),
    proposed_label_value: issueDetailString(issue, "proposed_label_value"),
  };
  return Object.values(approval).every((value) => value.trim())
    ? approval
    : null;
}

function digestPinLabelApprovalKey(
  approval: DigestPinLabelRewriteApprovalRequest,
): string {
  return [
    approval.stack,
    approval.service,
    approval.label_key,
    approval.current_label_value,
    approval.planned_tag,
    approval.proposed_label_value,
  ].join("\u0000");
}

function digestPinLabelApprovalApproved(issue: PlanIssue): boolean {
  const approval = digestPinLabelApprovalFromIssue(issue);
  const intent = updateIntent.value;
  if (!approval || !intent) {
    return false;
  }
  const key = digestPinLabelApprovalKey(approval);
  return intent.digestPinLabelRewriteApprovals.some(
    (item) => digestPinLabelApprovalKey(item) === key,
  );
}

function digestPinLabelIssueProposedRegex(issue: PlanIssue): string {
  return issueDetailString(issue, "proposed_label_regex");
}

async function approveDigestPinLabelRewrite(issue: PlanIssue): Promise<void> {
  const approval = digestPinLabelApprovalFromIssue(issue);
  const intent = updateIntent.value;
  if (!approval || !intent || updates.loading) {
    return;
  }
  const approvalsByKey = new Map(
    intent.digestPinLabelRewriteApprovals.map((item) => [
      digestPinLabelApprovalKey(item),
      item,
    ]),
  );
  approvalsByKey.set(digestPinLabelApprovalKey(approval), approval);
  const nextIntent: UpdateIntent = {
    ...intent,
    digestPinLabelRewriteApprovals: [...approvalsByKey.values()],
  };
  await updates.createPlan(
    nextIntent.lineNumbers,
    nextIntent.allowTagUpdates,
    nextIntent.tagOverrides,
    nextIntent.digestPinLabelRewriteApprovals,
  );
  if (updateIntent.value !== intent) {
    return;
  }
  updateIntent.value = nextIntent;
  showPreflightModal.value = true;
}

function staleDiagnosticLabel(item: DiagnosticItem): string {
  switch (item.diagnostic?.code) {
    case "compose-label-active-file-missing":
      return "Compose file missing";
    case "compose-label-undiscovered-active-file":
      return "Stack not discovered";
    case "matching-container-without-compose-labels":
      return "Missing Compose labels";
    case "unmatched":
      return "No Compose match";
    default:
      return item.diagnostic ? "Unmatched source" : "No Compose match";
  }
}

function staleDiagnosticDetail(item: DiagnosticItem): string {
  switch (item.diagnostic?.code) {
    case "compose-label-active-file-missing":
      return "Running container exists, but its Compose file is missing or archived.";
    case "compose-label-undiscovered-active-file":
      return "Running container exists, but Compose discovery does not include its stack.";
    case "matching-container-without-compose-labels":
      return "Running container exists, but Docker did not report Compose labels.";
    case "unmatched":
      return "No discovered Compose service or running container matched this line.";
    default:
      return item.diagnostic?.message || "No discovered Compose service matched this line.";
  }
}

function staleIssueSummary(items: DiagnosticItem[]): string {
  return summarizeList(items.map(staleDiagnosticLabel), 2);
}

function staleReviewSummary(
  items: DiagnosticItem[],
  singular: string,
  plural: string,
): string {
  if (!items.length) {
    return "";
  }
  const count = reviewCountLabel(items.length, singular, plural);
  const issue = staleIssueSummary(items);
  return issue ? `${count}: ${issue}.` : `${count}.`;
}

function assistantDetailList(
  items: DiagnosticItem[],
  key: AssistantDetailKey,
): string[] {
  const values: string[] = [];
  for (const item of items) {
    for (const value of diagnosticDetailList(item.diagnostic, key)) {
      if (!values.includes(value)) {
        values.push(value);
      }
    }
  }
  return values;
}

function diagnosticDetailList(
  diagnostic: PendingDiagnostic | null | undefined,
  key: AssistantDetailKey,
): string[] {
  const value = diagnostic?.details?.[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((entry) => {
    if (typeof entry !== "string") {
      return [];
    }
    const cleaned = entry.trim();
    return cleaned ? [cleaned] : [];
  });
}

function cleanupLineLabel(item: PlanCleanupItem): string {
  return `#${item.line_no} ${item.image}`;
}

function removalLineLabel(item: PendingRemovalPlanLine): string {
  return `#${item.line_no} ${item.image}`;
}

function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

function reviewCountLabel(
  count: number,
  singular: string,
  plural = `${singular}s`,
): string {
  const verb = count === 1 ? "needs" : "need";
  return `${pluralize(count, singular, plural)} ${verb} review`;
}

function summarizeList(values: string[], limit = 3): string {
  const uniqueValues = [...new Set(values.filter(Boolean))];
  if (uniqueValues.length <= limit) {
    return uniqueValues.join(", ");
  }
  return `${uniqueValues.slice(0, limit).join(", ")} +${uniqueValues.length - limit} more`;
}

function groupTagChangeCount(group: PendingStackGroup): number {
  return group.items.filter((item) => item.desired_tag || item.action === "tag-update")
    .length;
}

function tagInputProps(item: Pick<PendingItem, "image">): { "aria-label": string } {
  return { "aria-label": `New tag for ${item.image}` };
}

function itemsBreakingCount(items: PendingGroupedItem[]): number {
  return items.filter((item) => releaseNoteFor(item)?.breaking).length;
}

function groupedItemServices(item: PendingGroupedItem): string {
  return item.services.length ? item.services.join(", ") : "stack-level";
}

function groupedItemTarget(item: PendingGroupedItem): string {
  return item.target_image || item.resolved_image || item.image;
}

function groupChangePreviewItems(group: PendingStackGroup): PendingGroupedItem[] {
  return group.items.slice(0, 2);
}

function groupChangeOverflowCount(group: PendingStackGroup): number {
  return Math.max(0, group.items.length - groupChangePreviewItems(group).length);
}

function groupedItemActionLabel(item: PendingGroupedItem): string {
  switch (item.action) {
    case "tag-update":
      return "Tag update";
    case "recreate_service":
      return "Recreate service";
    case "recreate_stack":
      return "Recreate stack";
    case "unmatched":
      return "Needs review";
    default:
      return "Image update";
  }
}

function groupedItemActionTagType(item: PendingGroupedItem): SafetyCue["type"] {
  switch (item.action) {
    case "tag-update":
    case "recreate_stack":
    case "unmatched":
      return "warning";
    case "recreate_service":
      return "info";
    default:
      return "default";
  }
}

function groupedItemTagRewriteLabel(item: PendingGroupedItem): string {
  if (!item.desired_tag) {
    return "";
  }
  return `${item.image} -> ${groupedItemTarget(item)}`;
}

function planLineServiceLabel(stack: string, line: PlanLine): string {
  const service = line.service || "stack-level";
  return updates.plan?.summary.stack_count && updates.plan.summary.stack_count > 1
    ? `${stack} / ${service}`
    : service;
}

function planLineTagRewriteLabel(line: PlanLine): string {
  if (!line.desired_tag || line.action === "digest-pin") {
    return "";
  }
  return `${line.compose_image} -> ${line.target_image}`;
}

function planLineDigestPinLabel(line: PlanLine): string {
  if (line.action !== "digest-pin") {
    return "";
  }
  return `${line.compose_image} -> ${line.target_image}`;
}

async function loadPendingAndReleaseNotes(
  options: { preserveCleanup?: boolean } = {},
): Promise<void> {
  await updates.loadPending(options);
  await updates.loadReleaseNotes().catch(() => undefined);
  void updates.refreshReleaseNotes().catch(() => undefined);
}

async function retryPendingLoad(): Promise<void> {
  await loadPendingAndReleaseNotes().catch(() => undefined);
}

onMounted(() => {
  void retryPendingLoad();
  void settings.loadPendingSafetyCues();
  void reconnectObservedApplyJob();
});

watch(
  () => updates.pending?.items ?? [],
  (items) => {
    const next: Record<number, string> = {};
    const pendingLineNumbers = new Set<number>();
    for (const item of items) {
      pendingLineNumbers.add(item.line_no);
      if (item.desired_tag) {
        next[item.line_no] = tagOverrides.value[item.line_no] ?? item.desired_tag;
      }
    }
    tagOverrides.value = next;
    selectedLineNumbers.value = uniqueSorted(
      selectedLineNumbers.value.filter((lineNo) => pendingLineNumbers.has(lineNo)),
    );
  },
  { immediate: true },
);

onUnmounted(() => {
  closeJobStream();
});

watch(
  () => [updates.applyJob?.status, updates.applyJob?.run_id] as const,
  () => {
    void loadTerminalApplyJobLogIfMissing();
  },
  { immediate: true },
);

watch(
  () => updates.applyJob?.status,
  (status) => {
    applyJobLiveLogExpanded.value = status
      ? !terminalJobStatuses.has(status)
      : true;
  },
  { immediate: true },
);
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="(updates.error || runs.error)" type="error">
      {{ (updates.error || runs.error) }}
    </n-alert>
    <n-alert v-if="updates.pending && !updates.pending.exists" type="warning">
      {{ updates.pending.source_file }} is missing.
    </n-alert>
    <n-alert v-if="updates.releaseNotesError" type="warning">
      Release-note metadata is unavailable: {{ updates.releaseNotesError }}
    </n-alert>
    <n-alert v-if="pendingCleanupMessage" type="success">
      {{ pendingCleanupMessage }}
      <span class="inline-actions recovery-actions">
        <RouterLink
          class="text-link"
          :to="{ name: 'run-detail', params: { id: updates.pendingCleanup?.audit_run_id } }"
        >
          Details
        </RouterLink>
      </span>
    </n-alert>
    <n-alert
      v-if="updates.applyJobRecovery"
      type="warning"
    >
      {{ updates.applyJobRecovery }}
      <span class="inline-actions recovery-actions">
        <RouterLink class="text-link" to="/runs">Runs</RouterLink>
        <RouterLink
          v-if="latestRun"
          class="text-link"
          :to="{ name: 'run-detail', params: { id: latestRun.id } }"
        >
          Latest run
        </RouterLink>
        <RouterLink
          v-if="latestRun"
          class="text-link"
          :to="{ name: 'run-log', params: { id: latestRun.id } }"
        >
          Log
        </RouterLink>
      </span>
    </n-alert>

    <section
      v-if="updates.applyJob"
      ref="applyJobPanelRef"
      class="section-panel apply-job-panel"
      :class="{
        'apply-job-panel-active': applyJobActive,
        'apply-job-panel-success': applyJobSucceeded,
      }"
      tabindex="-1"
      aria-labelledby="apply-job-panel-title"
    >
      <div class="section-heading apply-job-heading">
        <div>
          <p class="eyebrow">Apply job</p>
          <div class="apply-job-heading-title">
            <span v-if="applyJobSucceeded" class="apply-job-complete-mark" aria-hidden="true">
              <CheckCircle2 :size="18" />
            </span>
            <h2 id="apply-job-panel-title">{{ applyJobTitle }}</h2>
          </div>
          <p class="apply-job-summary" role="status" aria-live="polite">
            {{ applyJobStatusMessage }}
          </p>
        </div>
        <n-tag :type="applyJobAlertType">{{ applyJobPanelStatusLabel }}</n-tag>
      </div>

      <div v-if="applyJobActive" class="apply-job-progress" aria-hidden="true">
        <span />
      </div>

      <section
        id="apply-job-panel-status"
        class="apply-job-now"
        :class="{
          'apply-job-now-success': updates.applyJob.status === 'success',
          'apply-job-now-failure': updates.applyJob.status === 'failure',
        }"
        role="status"
        aria-live="polite"
        aria-atomic="true"
        tabindex="-1"
        aria-labelledby="apply-job-now-title"
        :aria-describedby="applyJobNowDescriptionIds"
      >
        <div class="apply-job-now-copy">
          <span>Current status</span>
          <strong id="apply-job-now-title">{{ applyJobNowTitle }}</strong>
          <em id="apply-job-now-message">{{ applyJobNowMessage }}</em>
          <small v-if="applyJobNowDetail" id="apply-job-now-detail">
            {{ applyJobNowDetail }}
          </small>
        </div>
        <n-tag size="small" :type="applyJobAlertType">{{ applyJobNowStatusLabel }}</n-tag>
      </section>

      <section class="apply-job-latest-log" aria-labelledby="apply-job-latest-log-title">
        <span id="apply-job-latest-log-title">Latest log line</span>
        <code>{{ applyJobLatestLogMessage }}</code>
      </section>

      <section class="apply-job-progress-steps" aria-labelledby="apply-job-progress-title">
        <div class="apply-job-impact-heading">
          <strong id="apply-job-progress-title">Update progress</strong>
          <n-tag size="small">{{ applyJobProgressSummary }}</n-tag>
        </div>
        <ol class="apply-progress-list">
          <li
            v-for="step in applyJobProgressSteps"
            :key="step.key"
            class="apply-progress-step"
            :class="`apply-progress-step-${step.status}`"
          >
            <span class="apply-progress-icon" aria-hidden="true">
              <Check v-if="step.status === 'success'" :size="14" />
              <X v-else-if="step.status === 'failure'" :size="14" />
              <Play v-else-if="step.status === 'running'" :size="14" />
            </span>
            <span class="apply-progress-copy">
              <strong>{{ step.label }}</strong>
              <span>{{ step.message }}</span>
              <em v-if="step.detail">{{ step.detail }}</em>
            </span>
            <n-tag size="small" :type="progressTagType(step.status)">
              {{ step.statusLabel }}
            </n-tag>
          </li>
        </ol>
      </section>

      <details class="apply-job-details" :open="!applyJobActive">
        <summary>
          <span>Applied scope</span>
          <n-tag size="small">{{ applyJobImpactLabel || applyJobUpdateLabel }}</n-tag>
        </summary>
        <div class="apply-job-grid">
          <div class="compact-list">
            <div class="list-row">
              <span>Updates</span>
              <strong>{{ applyJobUpdateLabel }}</strong>
              <em>{{ applyJobStartedLabel }}</em>
            </div>
            <div v-if="applyJobImpactLabel" class="list-row">
              <span>Impact</span>
              <strong>{{ applyJobImpactLabel }}</strong>
              <em>{{ applyJobSnapshot?.sourceFile }}</em>
            </div>
            <div v-if="updates.applyJob.run_id" class="list-row">
              <span>Run</span>
              <strong>#{{ updates.applyJob.run_id }}</strong>
              <em class="inline-actions">
                <RouterLink
                  class="text-link"
                  :to="{ name: 'run-detail', params: { id: updates.applyJob.run_id } }"
                >
                  Details
                </RouterLink>
                <RouterLink
                  class="text-link"
                  :to="{ name: 'run-log', params: { id: updates.applyJob.run_id } }"
                >
                  Log
                </RouterLink>
              </em>
            </div>
          </div>

          <section
            class="apply-job-impact"
            aria-labelledby="apply-job-impact-title"
          >
            <div class="apply-job-impact-heading">
              <strong id="apply-job-impact-title">Services and images</strong>
              <n-tag size="small">{{ pluralize(applyJobSnapshotLines.length, "service") }}</n-tag>
            </div>
            <div v-if="applyJobSnapshotLines.length" class="compact-list">
              <div
                v-for="line in applyJobSnapshotLines"
                :key="line.key"
                class="list-row plan-line-row"
              >
                <span>#{{ line.lineNo }}</span>
                <strong>{{ line.serviceLabel }}</strong>
                <em>
                  <span v-if="line.tagRewriteLabel" class="tag-rewrite-detail">
                    <n-tag size="small" type="warning">Tag rewrite</n-tag>
                    {{ line.tagRewriteLabel }}
                  </span>
                  <span v-else-if="line.digestPinLabel" class="tag-rewrite-detail">
                    <n-tag size="small" type="info">Digest pin</n-tag>
                    {{ line.digestPinLabel }}
                  </span>
                  <template v-else>
                    <code>{{ line.composeImage }}</code>
                    <span aria-hidden="true"> -> </span>
                    <code>{{ line.targetImage }}</code>
                  </template>
                </em>
              </div>
            </div>
            <div v-else class="empty-state">
              Plan details are unavailable after page reload.
            </div>
          </section>
        </div>
      </details>

      <section class="apply-job-live-log" aria-labelledby="apply-job-log-title">
        <div class="apply-job-impact-heading apply-job-live-log-heading">
          <div class="apply-job-log-heading-copy">
            <strong id="apply-job-log-title">Live log</strong>
            <span class="apply-job-log-note">Raw command output</span>
            <span class="apply-job-log-path">{{ applyJobLogTitle }}</span>
          </div>
          <n-button
            v-show="!applyJobActive"
            class="apply-job-log-toggle"
            size="small"
            secondary
            :aria-expanded="applyJobLiveLogExpanded"
            :title="applyJobLiveLogToggleLabel"
            @click="applyJobLiveLogExpanded = !applyJobLiveLogExpanded"
          >
            <template #icon>
              <ChevronUp v-if="applyJobLiveLogExpanded" :size="16" />
              <ChevronDown v-else :size="16" />
            </template>
            {{ applyJobLiveLogExpanded ? "Hide output" : "Show output" }}
          </n-button>
        </div>
        <div v-show="applyJobLiveLogVisible" class="apply-job-live-log-body">
          <n-alert
            v-if="updates.applyJobLog?.truncated"
            class="preflight-block"
            type="warning"
            :show-icon="false"
          >
            Showing the last {{ updates.applyJobLog.max_bytes }} bytes.
          </n-alert>
          <n-alert
            v-if="updates.applyJobLog?.error"
            class="preflight-block"
            type="warning"
            :show-icon="false"
          >
            Live log unavailable: {{ updates.applyJobLog.error }}
          </n-alert>
          <div v-if="applyJobLogWaiting" class="empty-state">
            {{ applyJobLogEmptyMessage }}
          </div>
          <pre
            v-else-if="!updates.applyJobLog?.error"
            ref="applyJobPanelLogRef"
            class="log-viewer apply-job-log-viewer"
          >{{ applyJobLogText }}</pre>
        </div>
      </section>

      <n-alert
        v-if="updates.applyJob.error"
        class="plan-section"
        type="error"
      >
        {{ updates.applyJob.error }}
      </n-alert>
    </section>

    <div class="section-heading pending-heading">
      <div>
        <p class="eyebrow value-eyebrow pending-source" :title="pendingSourceFile">
          {{ pendingSourceDisplay }}
        </p>
        <h2>{{ pendingHeadingText }}</h2>
      </div>
      <n-tag size="small" :type="mutationStateType">{{ mutationStateLabel }}</n-tag>
    </div>

    <CoreUpdateTourPanel
      step="pending_select"
      title="Select the update scope"
      detail="Choose one stack or selected lines before previewing. Stack groups are the safest default because they keep related services together."
      next-label="Show preflight guidance"
      next-step="pending_preflight"
    >
      <div class="core-tour-facts">
        <span v-if="pendingLoaded">{{ pluralize(stackGroups.length, "stack") }} matched</span>
        <span v-else>Loading stack matches</span>
        <span v-if="pendingLoaded">{{ unmatchedReviewCountLabel }}</span>
        <span v-else>Waiting for pending file</span>
        <span>{{ mutationStateLabel }}</span>
      </div>
    </CoreUpdateTourPanel>

    <CoreUpdateTourPanel
      step="pending_preflight"
      title="Preview before anything changes"
      detail="Open a preview to see affected services, image targets, tag rewrites, skipped lines, and any blocking issues. Creating a plan does not pull, restart, or edit Docker state."
      next-label="Continue to apply guidance"
      next-step="pending_apply"
      :show="!showPreflightModal"
    />

    <CoreUpdateTourPanel
      step="pending_apply"
      title="Apply only after the plan is clear"
      :detail="pendingApplyTourDetail"
      next-label="Open run history"
      next-step="runs_history"
      next-to="/runs"
    />

    <div v-if="pendingLoaded" class="selection-toolbar">
      <div class="selection-summary">
        <strong>{{ selectedLineNumbers.length }} selected</strong>
        <span v-if="groupingReady">
          {{ pluralize(stackGroups.length, "stack") }} available
          <template v-if="unmatchedItems.length">
            - {{ unmatchedReviewCountLabel }}
          </template>
        </span>
        <span v-else>Pending file order</span>
      </div>
      <div class="inline-actions pending-actions">
        <n-button
          size="small"
          quaternary
          :disabled="!selectableLineNumbers.length"
          @click="selectAllVisible"
        >
          <template #icon>
            <Check :size="16" />
          </template>
          {{ selectAllLabel }}
        </n-button>
      </div>
    </div>

    <div v-if="pendingLoaded && selectedLineNumbers.length" class="batch-action-bar">
      <div class="selection-summary">
        <strong>{{ batchSummaryLabel }}</strong>
        <span>
          Preview the plan before anything changes.
          <template v-if="lineNumbersHaveTagUpdates(selectedLineNumbers)">
            Tag rewrites are confirmed before apply.
          </template>
          <template v-if="removeSelectedDisabledMessage">
            {{ removeSelectedDisabledMessage }}
          </template>
        </span>
      </div>
      <div class="inline-actions pending-actions">
        <n-button size="small" quaternary @click="clearSelection">
          <template #icon>
            <X :size="16" />
          </template>
          Clear selection
        </n-button>
        <n-button
          type="warning"
          size="small"
          secondary
          :disabled="removeSelectedDisabled"
          :loading="updates.loading"
          @click="startSelectedRemoval"
        >
          <template #icon>
            <Trash2 :size="16" />
          </template>
          {{ removalButtonLabel }}
        </n-button>
        <n-button
          type="primary"
          size="small"
          :disabled="updateSelectedDisabled"
          :loading="updates.loading"
          @click="startSelectedUpdate"
        >
          <template #icon>
            <Play :size="16" />
          </template>
          Preview selected plan
        </n-button>
      </div>
    </div>

    <n-alert
      v-if="selectedTagOverrideError"
      type="warning"
    >
      {{ selectedTagOverrideError }}
    </n-alert>

    <template v-if="groupingReady">
      <section class="stack-selection">
        <article
          v-for="group in stackGroups"
          :key="`${group.directory}/${group.compose_file}`"
          class="stack-card"
          :class="{ selected: stackHasSelection(group) }"
        >
          <div class="stack-card-header">
            <div class="stack-title-block">
              <n-checkbox
                :checked="stackSelected(group)"
                :indeterminate="stackIndeterminate(group)"
                :aria-label="`Select stack ${group.name}`"
                @update:checked="toggleStack(group, Boolean($event))"
              >
                <span class="stack-checkbox-label">
                  <span class="sr-only">Select stack </span>
                  <span class="stack-checkbox-kicker" aria-hidden="true">Stack</span>
                  <strong :title="group.directory">{{ group.name }}</strong>
                </span>
              </n-checkbox>
              <div class="stack-identity" aria-label="Stack impact">
                <span>
                  <span class="identity-label">Services</span>
                  {{ group.services_label }}
                </span>
              </div>
            </div>
            <div class="stack-card-side">
              <div class="stack-card-tags">
                <n-tag size="small">{{ pluralize(group.items.length, "update") }}</n-tag>
                <n-tag v-if="groupTagChangeCount(group)" size="small" type="warning">
                  {{ pluralize(groupTagChangeCount(group), "tag rewrite") }}
                </n-tag>
                <n-tag v-if="itemsBreakingCount(group.items)" size="small" type="warning">
                  {{ pluralize(itemsBreakingCount(group.items), "breaking cue") }}
                </n-tag>
              </div>
              <div class="stack-card-actions">
                <n-button
                  size="small"
                  secondary
                  :disabled="updateDisabled(group.line_numbers)"
                  :loading="updates.loading"
                  @click="startStackUpdate(group)"
                >
                  <template #icon>
                    <Play :size="16" />
                  </template>
                  Preview {{ group.name }} plan
                </n-button>
              </div>
            </div>
          </div>

          <div class="stack-change-preview" aria-label="Change preview">
            <div
              v-for="item in groupChangePreviewItems(group)"
              :key="`${group.name}-${item.line_no}-preview`"
              class="stack-change-row"
            >
              <strong class="stack-change-service">{{ groupedItemServices(item) }}</strong>
              <span class="stack-change-target">
                <n-tag
                  size="small"
                  :type="groupedItemActionTagType(item)"
                >
                  {{ groupedItemActionLabel(item) }}
                </n-tag>
                <span
                  v-if="riskCues(item).length"
                  class="risk-badges-container stack-change-risk-cues"
                  aria-label="Safety cues"
                >
                  <n-tag
                    v-for="cue in riskCues(item)"
                    :key="`${item.line_no}-${cue.key}`"
                    size="small"
                    :type="cue.type"
                    class="safety-badge"
                  >
                    {{ cue.label }}
                  </n-tag>
                </span>
                <code
                  class="stack-change-value"
                  data-label="Current"
                  :title="item.image"
                >
                  {{ previewImageLabel(item.image) }}
                </code>
                <span aria-hidden="true">-></span>
                <code
                  class="stack-change-value"
                  data-label="Target"
                  :title="groupedItemTarget(item)"
                >
                  {{ previewImageLabel(groupedItemTarget(item)) }}
                </code>
              </span>
            </div>
            <span v-if="groupChangeOverflowCount(group)" class="stack-change-more">
              +{{ groupChangeOverflowCount(group) }} more in Details
            </span>
          </div>

          <details class="stack-details">
            <summary :aria-label="`Details for ${group.name}`">Details</summary>
            <div class="stack-items">
              <div
                v-for="item in group.items"
                :key="`${group.name}-${item.line_no}`"
                class="pending-update-row"
                :class="{ selected: selectedLineSet.has(item.line_no) }"
              >
                <div class="pending-update-main">
                  <n-checkbox
                    :checked="selectedLineSet.has(item.line_no)"
                    :aria-label="`Select update ${item.image}`"
                    @update:checked="toggleLine(item.line_no, Boolean($event))"
                  >
                    <span class="sr-only">Select update </span>
                    <strong>{{ groupedItemServices(item) }}</strong>
                  </n-checkbox>
                  <n-tag size="small" :type="groupedItemActionTagType(item)">
                    {{ groupedItemActionLabel(item) }}
                  </n-tag>
                </div>
                <div class="pending-update-detail">
                  <code>{{ item.image }}</code>
                  <span>-></span>
                  <code>{{ groupedItemTarget(item) }}</code>
                </div>
                <div class="pending-update-meta">
                  <span>Pending file line #{{ item.line_no }}</span>
                  <span
                    v-if="riskCues(item).length"
                    class="risk-badges-container"
                    aria-label="Safety cues"
                  >
                    <n-tag
                      v-for="cue in riskCues(item)"
                      :key="`${item.line_no}-${cue.key}`"
                      size="small"
                      :type="cue.type"
                      class="safety-badge"
                    >
                      {{ cue.label }}
                    </n-tag>
                  </span>
                  <span v-if="groupedItemTagRewriteLabel(item)" class="tag-rewrite-detail">
                    <n-tag size="small" type="warning">Tag rewrite</n-tag>
                    {{ groupedItemTagRewriteLabel(item) }}
                  </span>
                  <div v-if="releaseNoteFor(item)?.links.length" class="release-notes-cell">
                    <a
                      v-for="link in releaseNoteFor(item)?.links ?? []"
                      :key="`${item.line_no}-${link.kind}-${link.url}`"
                      class="release-note-link"
                      :href="link.url"
                      target="_blank"
                      rel="noreferrer"
                    >
                      {{ link.label }}
                      <ExternalLink :size="14" aria-hidden="true" />
                    </a>
                    <span
                      v-if="releaseNoteFor(item)?.breaking"
                      class="release-breaking-cue"
                      :title="releaseNoteFor(item)?.breaking_reasons.join(' ')"
                      aria-label="Possible breaking change"
                    >
                      <AlertTriangle :size="14" aria-hidden="true" />
                      Possible breaking change
                    </span>
                  </div>
                  <div v-if="item.diagnostic" class="pending-update-diagnostic">
                    <n-alert type="warning" :title="item.diagnostic.message">
                      {{ item.diagnostic.hint }}
                    </n-alert>
                  </div>
                  <span
                    v-if="!releaseNoteFor(item)?.links.length"
                    class="release-notes-muted"
                    :title="releaseNoteReason(releaseNoteFor(item)) || undefined"
                  >
                    <span class="release-notes-status">
                      {{ releaseNoteStatus(releaseNoteFor(item)) }}
                    </span>
                    <span v-if="releaseNoteReason(releaseNoteFor(item))" class="release-notes-reason">
                      {{ releaseNoteReason(releaseNoteFor(item)) }}
                    </span>
                  </span>
                </div>
                <div v-if="item.desired_tag" class="pending-update-tag">
                  <span>New tag</span>
                  <n-input
                    :value="tagOverrideValue(item)"
                    size="small"
                    class="tag-override-input"
                    :placeholder="item.desired_tag"
                    :input-props="tagInputProps(item)"
                    @update:value="updateTagOverride(item, $event)"
                  />
                </div>
              </div>
            </div>
          </details>
        </article>

        <article v-if="unmatchedItems.length" class="stack-card needs-review">
          <div class="stack-card-header">
            <div class="stack-title-block">
              <strong>Stale pending entries</strong>
              <span class="stack-path">{{ unmatchedReviewSummary }}</span>
            </div>
            <div class="stack-card-side">
              <div class="stack-card-tags">
                <n-tag size="small" type="warning">
                  {{ pluralize(unmatchedItems.length, "item") }}
                </n-tag>
                <n-tag v-if="unmatchedIssueSummary" size="small" type="warning">
                  {{ unmatchedIssueSummary }}
                </n-tag>
              </div>
            </div>
          </div>
          <details class="stack-details">
            <summary aria-label="Details for unmatched updates">Details</summary>
            <div class="stack-items">
              <div
                v-for="item in unmatchedItems"
                :key="`unmatched-${item.line_no}`"
                class="pending-update-row"
                :class="{ selected: selectedLineSet.has(item.line_no) }"
              >
                <div class="pending-update-main">
                  <n-checkbox
                    :checked="selectedLineSet.has(item.line_no)"
                    :aria-label="`Select update ${item.image}`"
                    @update:checked="toggleLine(item.line_no, Boolean($event))"
                  >
                    <span class="sr-only">Select update </span>
                    <strong>{{ item.repo }}</strong>
                  </n-checkbox>
                  <n-tag size="small" type="warning">
                    {{ staleDiagnosticLabel(item) }}
                  </n-tag>
                </div>
                <div class="pending-update-detail">
                  <code>{{ item.image }}</code>
                  <span>-></span>
                  <code>{{ groupedItemTarget(item) }}</code>
                </div>
                <div class="pending-update-meta">
                  <span>Pending file line #{{ item.line_no }}</span>
                  <span>{{ staleDiagnosticDetail(item) }}</span>
                </div>
                <div v-if="item.diagnostic" class="pending-update-diagnostic">
                  <n-alert type="warning" :title="item.diagnostic.message">
                    {{ item.diagnostic.hint }}
                  </n-alert>
                </div>
                <div v-if="item.desired_tag" class="pending-update-tag">
                  <span>New tag</span>
                  <n-input
                    :value="tagOverrideValue(item)"
                    size="small"
                    class="tag-override-input"
                    :placeholder="item.desired_tag"
                    :input-props="tagInputProps(item)"
                    @update:value="updateTagOverride(item, $event)"
                  />
                </div>
              </div>
            </div>
          </details>
        </article>

        <div
          v-if="!stackGroups.length && !unmatchedItems.length"
          class="empty-state clear-queue-state"
          role="status"
          aria-live="polite"
        >
          <span class="clear-queue-mark" aria-hidden="true">
            <CheckCircle2 :size="24" />
          </span>
          <strong>Update queue is clear</strong>
          <span>{{ pendingSourceLabel }} has no updates waiting for review.</span>
          <span v-if="settings.coreUpdateTour?.status === 'in_progress'">
            New WUD entries will appear here for stack selection and preflight review.
          </span>
          <RouterLink
            v-if="settings.coreUpdateTour?.status === 'in_progress'"
            class="text-link"
            to="/settings"
          >
            Open setup checklist
          </RouterLink>
          <RouterLink
            v-if="latestRun"
            class="text-link"
            :to="{ name: 'run-detail', params: { id: latestRun.id } }"
          >
            Review latest run #{{ latestRun.id }}
          </RouterLink>
        </div>
      </section>
    </template>

    <template v-else-if="updates.pending">
      <n-alert type="info">
        Stack grouping is unavailable. Showing pending file order.
      </n-alert>

      <div
        v-if="!updates.pending?.items.length"
        class="empty-state clear-queue-state"
        role="status"
        aria-live="polite"
      >
        <span class="clear-queue-mark" aria-hidden="true">
          <CheckCircle2 :size="24" />
        </span>
        <strong>Update queue is clear</strong>
        <span>{{ pendingSourceLabel }} has no updates waiting for review.</span>
        <span v-if="settings.coreUpdateTour?.status === 'in_progress'">
          New WUD entries will appear here for stack selection and preflight review.
        </span>
        <RouterLink
          v-if="settings.coreUpdateTour?.status === 'in_progress'"
          class="text-link"
          to="/settings"
        >
          Open setup checklist
        </RouterLink>
        <RouterLink
          v-if="latestRun"
          class="text-link"
          :to="{ name: 'run-detail', params: { id: latestRun.id } }"
        >
          Review latest run #{{ latestRun.id }}
        </RouterLink>
      </div>

      <n-data-table
        v-else-if="!isMobile"
        :columns="columns"
        :data="updates.pending?.items ?? []"
        :loading="updates.loading"
        :pagination="{ pageSize: 15 }"
        :row-key="rowKey"
        :checked-row-keys="selectedLineNumbers"
        size="small"
        class="data-surface"
        @update:checked-row-keys="updateCheckedRowKeys"
      />

      <div v-else class="mobile-list">
        <article v-for="item in updates.pending?.items ?? []" :key="item.line_no" class="mobile-card">
          <div class="mobile-card-title">
            <n-checkbox
              :checked="selectedLineSet.has(item.line_no)"
              @update:checked="toggleLine(item.line_no, Boolean($event))"
            >
              <span class="sr-only">Select update </span>
              <strong>{{ item.image }}</strong>
            </n-checkbox>
            <n-tag size="small">#{{ item.line_no }}</n-tag>
          </div>
          <dl>
            <div>
              <dt>Repository</dt>
              <dd>{{ item.repo }}</dd>
            </div>
            <div>
              <dt>Current tag</dt>
              <dd>{{ item.current_tag || "None" }}</dd>
            </div>
            <div>
              <dt>New tag</dt>
              <dd>
                <n-input
                  v-if="item.desired_tag"
                  :value="tagOverrideValue(item)"
                  size="small"
                  class="tag-override-input"
                  :placeholder="item.desired_tag"
                  :input-props="tagInputProps(item)"
                  @update:value="updateTagOverride(item, $event)"
                />
                <span v-else>None</span>
              </dd>
            </div>
            <div>
              <dt>New digest</dt>
              <dd>
                <code v-if="item.digest" class="digest-value" :title="item.digest">
                  {{ displayDigest(item.digest) }}
                </code>
                <span v-else>None</span>
              </dd>
            </div>
            <div>
              <dt>Safety cues</dt>
              <dd>
                <div v-if="riskCues(item).length" class="risk-badges-container">
                  <n-tag
                    v-for="cue in riskCues(item)"
                    :key="`${item.line_no}-${cue.key}`"
                    size="small"
                    :type="cue.type"
                    class="safety-badge"
                  >
                    {{ cue.label }}
                  </n-tag>
                </div>
                <span v-else class="risk-badges-muted">None</span>
              </dd>
            </div>
            <div>
              <dt>Release notes</dt>
              <dd>
                <div v-if="releaseNoteFor(item)?.links.length" class="release-notes-cell">
                  <a
                    v-for="link in releaseNoteFor(item)?.links ?? []"
                    :key="`${item.line_no}-${link.kind}-${link.url}`"
                    class="release-note-link"
                    :href="link.url"
                    target="_blank"
                    rel="noreferrer"
                  >
                    {{ link.label }}
                    <ExternalLink :size="14" aria-hidden="true" />
                  </a>
                  <span
                    v-if="releaseNoteFor(item)?.breaking"
                    class="release-breaking-cue"
                    :title="releaseNoteFor(item)?.breaking_reasons.join(' ')"
                    aria-label="Possible breaking change"
                  >
                    <AlertTriangle :size="14" aria-hidden="true" />
                    Possible breaking change
                  </span>
                </div>
                <span
                  v-else
                  class="release-notes-muted"
                  :title="releaseNoteReason(releaseNoteFor(item)) || undefined"
                >
                  <span class="release-notes-status">
                    {{ releaseNoteStatus(releaseNoteFor(item)) }}
                  </span>
                  <span v-if="releaseNoteReason(releaseNoteFor(item))" class="release-notes-reason">
                    {{ releaseNoteReason(releaseNoteFor(item)) }}
                  </span>
                </span>
              </dd>
            </div>
          </dl>
        </article>
      </div>
    </template>

    <section
      v-else-if="pendingLoading"
      class="pending-loading-state"
      role="status"
      aria-live="polite"
      aria-label="Loading pending updates"
    >
      <span aria-hidden="true" class="settings-skeleton-row"></span>
      <span aria-hidden="true" class="settings-skeleton-row"></span>
      <span aria-hidden="true" class="settings-skeleton-row"></span>
    </section>

    <div
      v-else-if="pendingLoadFailed"
      class="empty-state pending-error-state"
      role="alert"
      aria-live="assertive"
    >
      <strong>Pending updates did not load</strong>
      <span>Check the WebUI API connection, then try again.</span>
      <n-button size="small" secondary :loading="updates.loading" @click="retryPendingLoad">
        Retry pending load
      </n-button>
    </div>

    <n-modal
      v-if="updates.plan"
      v-model:show="showPreflightModal"
      :mask-closable="false"
    >
      <section
        class="preflight-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="preflight-modal-title"
      >
        <div class="section-heading">
          <div>
            <p class="eyebrow">Preflight</p>
            <h2 id="preflight-modal-title">{{ preflightTitle }}</h2>
            <p class="preflight-summary-text">{{ preflightSummary }}</p>
            <p v-if="preflightServiceImpactLabel" class="preflight-impact-text">
              {{ preflightServiceImpactLabel }}
            </p>
          </div>
          <n-tag :type="planAlertType">{{ updates.plan.status }}</n-tag>
        </div>

        <div class="preflight-metrics">
          <div>
            <span>Targets</span>
            <strong>{{ updates.plan.summary.target_count }}</strong>
          </div>
          <div>
            <span>Matched</span>
            <strong>{{ updates.plan.summary.matched_target_count }}</strong>
          </div>
          <div>
            <span>Stacks</span>
            <strong>{{ updates.plan.summary.stack_count }}</strong>
          </div>
          <div>
            <span>Issues</span>
            <strong>{{ updates.plan.summary.issue_count }}</strong>
          </div>
        </div>

        <section
          v-if="applyPreflight"
          class="apply-readiness preflight-block"
          aria-labelledby="apply-readiness-title"
        >
          <div class="apply-readiness-heading">
            <div>
              <strong id="apply-readiness-title">Apply readiness</strong>
              <span>{{ applyReadinessSummary }}</span>
            </div>
            <n-tag size="small" :type="applyReadinessStatusType">
              {{ applyReadinessStatusLabel }}
            </n-tag>
          </div>
          <div
            v-if="applyPreflightPassedChecks.length"
            class="apply-readiness-passed"
          >
            <CheckCircle2 :size="16" aria-hidden="true" />
            <p>
              <strong>
                {{ pluralize(applyPreflightPassedChecks.length, "check") }} passed:
              </strong>
              <span class="apply-readiness-pass-list">
                {{ applyPreflightPassedText }}
              </span>
            </p>
          </div>
          <div
            v-if="applyPreflightAttentionChecks.length"
            class="apply-readiness-list"
          >
            <div
              v-for="check in applyPreflightAttentionChecks"
              :key="check.code"
              class="apply-readiness-row"
              :class="`status-${check.status.toLowerCase()}`"
            >
              <CheckCircle2
                v-if="check.status === 'PASS'"
                :size="16"
                aria-hidden="true"
              />
              <AlertTriangle
                v-else-if="check.status === 'WARN'"
                :size="16"
                aria-hidden="true"
              />
              <XCircle v-else :size="16" aria-hidden="true" />
              <strong>{{ check.label }}</strong>
              <n-tag size="small" :type="applyPreflightCheckType(check.status)">
                {{ applyPreflightCheckLabel(check.status) }}
              </n-tag>
              <span
                v-if="applyPreflightCheckDetail(check)"
                class="apply-readiness-detail"
              >
                {{ applyPreflightCheckDetail(check) }}
              </span>
            </div>
          </div>
        </section>

        <CoreUpdateTourPanel
          step="pending_preflight"
          title="Read the plan like a checklist"
          detail="Matched services and images show what will change. Issues block apply, tag rewrites are called out, and cleanup actions only edit the pending file after confirmation."
          next-label="Continue to apply guidance"
          next-step="pending_apply"
          @advanced="closePreflightModal"
        />

        <n-alert
          v-if="mutationDisabledMessage"
          class="preflight-block"
          type="warning"
        >
          {{ mutationDisabledMessage }}
        </n-alert>
        <n-alert
          v-if="preflightTagRewriteNotice"
          class="preflight-block"
          type="warning"
        >
          {{ preflightTagRewriteNotice }}
        </n-alert>
        <n-alert
          v-if="preflightDigestPinNotice"
          class="preflight-block"
          type="info"
        >
          {{ preflightDigestPinNotice }}
        </n-alert>

        <section
          v-if="planDigestPinLabelRewrites.length"
          class="preflight-impact preflight-block"
          aria-labelledby="digest-pin-label-rewrites-title"
        >
          <div class="preflight-impact-heading">
            <strong id="digest-pin-label-rewrites-title">Digest-pin label updates</strong>
            <n-tag size="small">{{ pluralize(planDigestPinLabelRewrites.length, "label") }}</n-tag>
          </div>
          <div class="compact-list">
            <div
              v-for="item in planDigestPinLabelRewrites"
              :key="`${item.stack}-${item.rewrite.service}-${item.rewrite.label_key}-${item.rewrite.current_label_value}`"
              class="list-row plan-line-row"
            >
              <span>Label</span>
              <strong>{{ item.stack }} / {{ item.rewrite.service }}</strong>
              <em>
                <code>{{ item.rewrite.label_key }}={{ item.rewrite.current_label_value }}</code>
                <span aria-hidden="true"> -> </span>
                <code>{{ item.rewrite.proposed_label_regex }}</code>
              </em>
            </div>
          </div>
        </section>

        <section
          v-if="digestPinLabelApprovalIssues.length"
          class="preflight-impact preflight-block"
          aria-labelledby="digest-pin-label-approvals-title"
        >
          <div class="preflight-impact-heading">
            <strong id="digest-pin-label-approvals-title">Digest-pin label approvals</strong>
            <n-tag size="small" type="warning">
              {{ pluralize(digestPinLabelApprovalIssues.length, "approval") }}
            </n-tag>
          </div>
          <p class="preflight-summary-text">
            Approve replacing each current include rule with the exact planned tag before applying.
          </p>
          <div class="compact-list">
            <div
              v-for="issue in digestPinLabelApprovalIssues"
              :key="`${issue.stack}-${issue.service}-${issueDetailString(issue, 'current_label_value')}`"
              class="list-row plan-line-row digest-pin-approval-row"
            >
              <span>Review</span>
              <strong>{{ issue.stack }} / {{ issue.service }}</strong>
              <em>
                <code>{{ issueDetailString(issue, "label_key") }}={{ issueDetailString(issue, "current_label_value") }}</code>
                <span aria-hidden="true"> -> </span>
                <code>{{ digestPinLabelIssueProposedRegex(issue) }}</code>
                <n-button
                  size="small"
                  secondary
                  type="primary"
                  :disabled="digestPinLabelApprovalApproved(issue)"
                  :loading="updates.loading"
                  @click="approveDigestPinLabelRewrite(issue)"
                >
                  <template #icon>
                    <Check :size="16" />
                  </template>
                  {{ digestPinLabelApprovalApproved(issue) ? "Approved" : "Approve label rewrite" }}
                </n-button>
              </em>
            </div>
          </div>
        </section>

        <n-alert
          v-if="cleanupDisabledMessage"
          class="preflight-block"
          type="warning"
        >
          {{ cleanupDisabledMessage }}
        </n-alert>

        <section
          v-if="cleanupAvailable"
          class="preflight-impact preflight-block"
          aria-labelledby="cleanup-preview-title"
        >
          <div class="preflight-impact-heading">
            <strong id="cleanup-preview-title">Unmatched pending entries</strong>
            <n-tag size="small" type="warning">
              {{ pluralize(cleanupItems.length, "entry", "entries") }}
            </n-tag>
          </div>
          <p class="preflight-summary-text">{{ cleanupReviewSummary }}</p>
          <div class="compact-list">
            <div
              v-for="item in cleanupItems"
              :key="`cleanup-${item.line_no}`"
              class="list-row plan-line-row"
            >
              <span>#{{ item.line_no }}</span>
              <strong class="plan-line-heading">
                <span>{{ item.image }}</span>
                <n-tag size="small" type="warning">
                  {{ staleDiagnosticLabel(item) }}
                </n-tag>
              </strong>
              <em>
                <span>{{ staleDiagnosticDetail(item) }}</span>
              </em>
            </div>
          </div>
        </section>

        <section
          v-if="updates.plan.status === 'ready'"
          class="preflight-impact preflight-block"
          aria-labelledby="preflight-impact-title"
        >
          <div class="preflight-impact-heading">
            <strong id="preflight-impact-title">Services and images</strong>
            <n-tag size="small">{{ pluralize(planLines.length, "service") }}</n-tag>
          </div>
          <div v-if="planLines.length" class="compact-list">
            <div
              v-for="{ stack, line } in planLines"
              :key="`${stack}-${line.line_no}-${line.service}`"
              class="list-row plan-line-row"
            >
              <span>#{{ line.line_no }}</span>
              <strong>{{ planLineServiceLabel(stack, line) }}</strong>
              <em>
                <span v-if="planLineTagRewriteLabel(line)" class="tag-rewrite-detail">
                  <n-tag size="small" type="warning">Tag rewrite</n-tag>
                  {{ planLineTagRewriteLabel(line) }}
                </span>
                <span
                  v-else-if="planLineDigestPinLabel(line)"
                  class="tag-rewrite-detail"
                >
                  <n-tag size="small" type="info">Digest pin</n-tag>
                  {{ planLineDigestPinLabel(line) }}
                </span>
                <template v-else>
                  <code>{{ line.compose_image }}</code>
                  <span aria-hidden="true"> -> </span>
                  <code>{{ line.target_image }}</code>
                </template>
              </em>
            </div>
          </div>
          <div v-else class="empty-state">No matched services.</div>
        </section>

        <div v-if="visiblePlanIssues.length" class="warning-list preflight-block">
          <n-alert
            v-for="issue in visiblePlanIssues"
            :key="`${issue.code}-${issue.line_no ?? ''}-${issue.stack}-${issue.service}`"
            :type="issueType(issue)"
          >
            <span>{{ issueLabel(issue) }}</span>
            <span v-if="issueHint(issue)" class="issue-hint">
              {{ issueHint(issue) }}
            </span>
          </n-alert>
        </div>

        <div class="preflight-details-list">
          <details
            v-if="updates.plan.status !== 'ready'"
            class="preflight-details"
            :open="updates.plan.status === 'blocked'"
          >
            <summary>Services and images</summary>
            <div v-if="planLines.length" class="compact-list">
              <div
                v-for="{ stack, line } in planLines"
                :key="`${stack}-${line.line_no}-${line.service}`"
                class="list-row plan-line-row"
              >
                <span>#{{ line.line_no }}</span>
                <strong>{{ planLineServiceLabel(stack, line) }}</strong>
                <em>
                  <span v-if="planLineTagRewriteLabel(line)" class="tag-rewrite-detail">
                    <n-tag size="small" type="warning">Tag rewrite</n-tag>
                    {{ planLineTagRewriteLabel(line) }}
                  </span>
                  <span
                    v-else-if="planLineDigestPinLabel(line)"
                    class="tag-rewrite-detail"
                  >
                    <n-tag size="small" type="info">Digest pin</n-tag>
                    {{ planLineDigestPinLabel(line) }}
                  </span>
                  <template v-else>
                    <code>{{ line.compose_image }}</code>
                    <span aria-hidden="true"> -> </span>
                    <code>{{ line.target_image }}</code>
                  </template>
                </em>
              </div>
            </div>
            <div v-else class="empty-state">No matched services.</div>
          </details>

          <details v-if="planActions.length" class="preflight-details">
            <summary>Commands</summary>
            <div class="plan-actions">
              <div
                v-for="{ stack, action } in planActions"
                :key="`${stack}-${action.kind}-${actionCommand(action)}`"
                class="plan-action"
              >
                <n-tag size="small">{{ action.kind }}</n-tag>
                <code>{{ actionCommand(action) }}</code>
              </div>
            </div>
          </details>

          <details v-if="updates.plan.skipped.length" class="preflight-details" open>
            <summary>Skipped</summary>
            <div class="compact-list">
              <div v-for="item in updates.plan.skipped" :key="item.line_no" class="list-row">
                <span>#{{ item.line_no }}</span>
                <strong>{{ item.image }}</strong>
                <em>{{ item.reason }}</em>
              </div>
            </div>
          </details>

          <details class="preflight-details">
            <summary>Source lines</summary>
            <div class="compact-list">
              <div
                v-for="lineNo in updates.plan.selected_line_numbers"
                :key="lineNo"
                class="list-row"
              >
                <span>Line</span>
                <strong>#{{ lineNo }}</strong>
                <em>{{ updates.plan.source_file }}</em>
              </div>
            </div>
          </details>
        </div>

        <div class="preflight-footer">
          <n-button size="small" quaternary @click="closePreflightModal">
            Close
          </n-button>
          <n-button
            v-if="cleanupAvailable"
            type="warning"
            size="small"
            secondary
            :disabled="cleanupDisabled"
            :loading="updates.loading"
            @click="openCleanupModal"
          >
            <template #icon>
              <Trash2 :size="16" />
            </template>
            {{ cleanupButtonLabel }}
          </n-button>
          <n-button
            v-if="applyVisible"
            type="primary"
            size="small"
            :disabled="applyDisabled"
            :loading="updates.loading"
            @click="confirmApply"
          >
            <template #icon>
              <Play :size="16" />
            </template>
            {{ applyButtonLabel }}
          </n-button>
        </div>
      </section>
    </n-modal>

    <n-modal
      v-if="updates.plan && cleanupAvailable"
      v-model:show="showCleanupModal"
      :mask-closable="false"
    >
      <section
        class="preflight-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cleanup-modal-title"
      >
        <div class="section-heading">
          <div>
            <p class="eyebrow">Pending cleanup</p>
            <h2 id="cleanup-modal-title">Remove unmatched entries</h2>
            <p class="preflight-summary-text">
              These lines will be removed from {{ pendingSourceLabel }} without running Docker updates.
            </p>
          </div>
          <n-tag type="warning">{{ pluralize(cleanupItems.length, "entry", "entries") }}</n-tag>
        </div>

        <n-alert class="preflight-block" type="warning">
          The server will re-read {{ pendingSourceLabel }} and reject the cleanup if any selected line changed or now matches an active Compose stack.
        </n-alert>
        <n-alert class="preflight-block" type="warning">
          This only edits {{ pendingSourceLabel }}. Containers, images, Compose services, and Compose files are not deleted or updated.
        </n-alert>

        <section
          v-if="
            cleanupAssistantFindings.length ||
            cleanupAssistantReasons.length ||
            cleanupAssistantActions.length
          "
          class="preflight-impact preflight-block"
          aria-labelledby="cleanup-guidance-title"
        >
          <div class="preflight-impact-heading">
            <strong id="cleanup-guidance-title">Stale entry guidance</strong>
          </div>
          <div class="pending-assistant">
            <div v-if="cleanupAssistantFindings.length" class="pending-assistant-section">
              <strong>Preflight found</strong>
              <ul>
                <li v-for="finding in cleanupAssistantFindings" :key="finding">
                  {{ finding }}
                </li>
              </ul>
            </div>
            <div v-if="cleanupAssistantReasons.length" class="pending-assistant-section">
              <strong>Likely causes</strong>
              <ul>
                <li v-for="reason in cleanupAssistantReasons" :key="reason">
                  {{ reason }}
                </li>
              </ul>
            </div>
            <div v-if="cleanupAssistantActions.length" class="pending-assistant-section">
              <strong>Recommended actions</strong>
              <ul>
                <li v-for="action in cleanupAssistantActions" :key="action">
                  {{ action }}
                </li>
              </ul>
            </div>
          </div>
        </section>

        <section class="preflight-impact preflight-block" aria-labelledby="cleanup-lines-title">
          <div class="preflight-impact-heading">
            <strong id="cleanup-lines-title">Source lines</strong>
            <n-tag size="small">{{ pluralize(cleanupItems.length, "line") }}</n-tag>
          </div>
          <div class="compact-list">
            <div
              v-for="item in cleanupItems"
              :key="`cleanup-confirm-${item.line_no}`"
              class="list-row plan-line-row"
            >
              <span>Line</span>
              <strong>{{ cleanupLineLabel(item) }}</strong>
              <em><code>{{ item.raw }}</code></em>
            </div>
          </div>
        </section>

        <div class="preflight-footer">
          <n-button size="small" quaternary @click="closeCleanupModal">
            Cancel
          </n-button>
          <n-button
            type="warning"
            size="small"
            :disabled="cleanupDisabled"
            :loading="updates.loading"
            @click="confirmCleanup"
          >
            <template #icon>
              <Trash2 :size="16" />
            </template>
            {{ cleanupButtonLabel }}
          </n-button>
        </div>
      </section>
    </n-modal>

    <n-modal
      v-if="updates.pendingRemovalPlan"
      v-model:show="showRemovalModal"
      :mask-closable="false"
    >
      <section
        class="preflight-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="removal-modal-title"
      >
        <div class="section-heading">
          <div>
            <p class="eyebrow">Pending removal</p>
            <h2 id="removal-modal-title">Remove selected entries</h2>
            <p class="preflight-summary-text">
              These lines will be removed from {{ pendingSourceLabel }} without running Docker updates.
            </p>
          </div>
          <n-tag type="warning">{{ pluralize(removalItems.length, "entry", "entries") }}</n-tag>
        </div>

        <n-alert class="preflight-block" type="warning">
          This only edits {{ pendingSourceLabel }}. Containers, images, and Compose services are not deleted or updated, and WUD may add these entries again if the updates still exist.
        </n-alert>

        <section class="preflight-impact preflight-block" aria-labelledby="removal-lines-title">
          <div class="preflight-impact-heading">
            <strong id="removal-lines-title">Source lines</strong>
            <n-tag size="small">{{ pluralize(removalItems.length, "line") }}</n-tag>
          </div>
          <div class="compact-list">
            <div
              v-for="item in removalItems"
              :key="`removal-confirm-${item.line_no}`"
              class="list-row plan-line-row"
            >
              <span>Line</span>
              <strong>{{ removalLineLabel(item) }}</strong>
              <em><code>{{ item.raw }}</code></em>
            </div>
          </div>
        </section>

        <div class="preflight-footer">
          <n-button size="small" quaternary @click="closeRemovalModal">
            Cancel
          </n-button>
          <n-button
            type="warning"
            size="small"
            :disabled="removalDisabled"
            :loading="updates.loading"
            @click="confirmSelectedRemoval"
          >
            <template #icon>
              <Trash2 :size="16" />
            </template>
            {{ removalConfirmButtonLabel }}
          </n-button>
        </div>
      </section>
    </n-modal>
  </section>
</template>

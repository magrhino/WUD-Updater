<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { breakpointsTailwind, useBreakpoints } from "@vueuse/core";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ExternalLink,
  Play,
  Trash2,
  X,
} from "@lucide/vue";
import {
  NAlert,
  NButton,
  NCheckbox,
  NDataTable,
  NFlex,
  NInput,
  NSkeleton,
  NTag,
  type DataTableRowKey,
} from "naive-ui";

import {
  type PendingGroupedItem,
  type PendingItem,
  type PendingStackGroup,
  type ReleaseNoteInfo,
  type TagOverrideRequest,
} from "../api/client";
import CoreUpdateTourPanel from "../components/CoreUpdateTourPanel.vue";
import PendingApplyJobPanel from "../components/pending/PendingApplyJobPanel.vue";
import PendingCleanupModal from "../components/pending/PendingCleanupModal.vue";
import PendingPlanReviewModal from "../components/pending/PendingPlanReviewModal.vue";
import PendingRemovalModal from "../components/pending/PendingRemovalModal.vue";
import PendingUpdateRow from "../components/pending/PendingUpdateRow.vue";
import { useUpdatesStore } from "../stores/updates";
import { useRunsStore } from "../stores/runs";
import { useSettingsStore } from "../stores/settings";
import {
  digestProvenanceDisplay,
  displayDigest,
} from "../utils/digestProvenance";
import { safetyCues, type SafetyCue } from "./pending/safetyCues";
import { createPendingColumns } from "./pending/tableColumns";
import { pluralize } from "./pending/utils";
import {
  usePendingApplyJob,
  type PendingApplyJobPanelRef,
} from "./pending/usePendingApplyJob";
import {
  usePendingPlanReviewState,
  type PendingUpdateIntent,
} from "./pending/usePendingPlanReviewState";

const updates = useUpdatesStore();
const runs = useRunsStore();
const settings = useSettingsStore();
const breakpoints = useBreakpoints(breakpointsTailwind);
const isMobile = breakpoints.smaller("md");
const selectedLineNumbers = ref<number[]>([]);
const tagOverrides = ref<Record<number, string>>({});
const showPreflightModal = ref(false);
const showCleanupModal = ref(false);
const showRemovalModal = ref(false);
const applyJobPanelRef = ref<PendingApplyJobPanelRef | null>(null);
const tagValuePattern = /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$/;

const columns = computed(() =>
  createPendingColumns({
    displayDigest,
    displayValue,
    releaseNoteFor,
    releaseNoteReason,
    releaseNoteStatus,
    riskCues,
    tagInputProps,
    tagOverrideValue,
    updateTagOverride,
  }),
);

const allLineNumbers = computed(
  () => uniqueSorted(updates.pending?.items.map((item) => item.line_no) ?? []),
);
const groupingReady = computed(
  () => updates.pending?.grouping.status === "ready",
);
const rawStackGroups = computed(() =>
  groupingReady.value ? (updates.pending?.grouping.groups ?? []) : [],
);
const pendingServiceKeys = computed(() => {
  const keys: string[] = [];
  for (const group of rawStackGroups.value) {
    for (const item of group.items) {
      keys.push(...groupedItemServiceKeys(group, item));
    }
  }
  return new Set(keys);
});
const activeDependencySnoozes = computed(() =>
  settings.snoozes.filter(
    (snooze) => snooze.kind === "dependency" && snooze.active,
  ),
);
const dependencyBlockedServiceKeys = computed(() => {
  const pending = pendingServiceKeys.value;
  return new Set(
    activeDependencySnoozes.value
      .filter(
        (snooze) =>
          pending.has(snooze.service_key),
      )
      .map((snooze) => snooze.service_key),
  );
});
const dependencySnoozedItems = computed(() => {
  const blocked = dependencyBlockedServiceKeys.value;
  return rawStackGroups.value.flatMap((group) =>
    group.items
      .filter((item) =>
        groupedItemServiceKeys(group, item).some((key) => blocked.has(key)),
      )
      .map((item) => ({ group, item })),
  );
});
const stackGroups = computed(() =>
  rawStackGroups.value
    .map((group) => {
      const items = group.items.filter(
        (item) =>
          !groupedItemServiceKeys(group, item).some((key) =>
            dependencyBlockedServiceKeys.value.has(key),
          ),
      );
      const services = uniqueStrings(items.flatMap((item) => item.services));
      return {
        ...group,
        items,
        services,
        services_label: services.length ? services.join(", ") : group.services_label,
        line_numbers: items.map((item) => item.line_no),
      };
    })
    .filter((group) => group.items.length > 0),
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
const selectableLineNumbers = computed(() => {
  if (groupingReady.value) {
    return stackLineNumbers.value;
  }
  if (activeDependencySnoozes.value.length) {
    return [];
  }
  return allLineNumbers.value;
});
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
const {
  actionCommand,
  applyButtonLabel,
  applyDisabled,
  applyPreflight,
  applyPreflightAttentionChecks,
  applyPreflightCheckDetail,
  applyPreflightCheckLabel,
  applyPreflightCheckType,
  applyPreflightPassedChecks,
  applyPreflightPassedText,
  applyPlanPayload,
  applyReadinessStatusLabel,
  applyReadinessStatusType,
  applyReadinessSummary,
  applyVisible,
  batchSummaryLabel,
  cleanupAssistantActions,
  cleanupAssistantFindings,
  cleanupAssistantReasons,
  cleanupAvailable,
  cleanupButtonLabel,
  cleanupDisabled,
  cleanupDisabledMessage,
  cleanupItems,
  cleanupLineLabel,
  cleanupReviewSummary,
  approveDigestPinLabelRewrite,
  clearUpdateIntent,
  digestPinLabelApprovalApproved,
  digestPinLabelApprovalIssues,
  digestPinLabelIssueProposedRegex,
  issueDetailString,
  issueHint,
  issueLabel,
  issueType,
  mutationDisabledMessage,
  mutationStateLabel,
  mutationStateType,
  pendingApplyTourDetail,
  pendingCleanupMessage,
  planActions,
  planAlertType,
  planDigestPinLabelRewrites,
  planDigestUnpinUpdates,
  planLines,
  preflightDigestPinNotice,
  preflightDigestUnpinNotice,
  preflightServiceImpactLabel,
  preflightSummary,
  preflightTagRewriteNotice,
  preflightTitle,
  removalButtonLabel,
  removalConfirmButtonLabel,
  removalDisabled,
  removalItems,
  removalLineLabel,
  removeSelectedDisabled,
  removeSelectedDisabledMessage,
  selectedTagOverrideError,
  selectedUpdateContext,
  setUpdateIntent,
  staleDiagnosticDetail,
  staleDiagnosticLabel,
  unmatchedIssueSummary,
  unmatchedReviewCountLabel,
  unmatchedReviewSummary,
  updateSelectedDisabled,
  visiblePlanIssues,
} = usePendingPlanReviewState({
  pendingSourceLabel,
  selectedLineNumbers,
  selectedLineSet,
  stackGroups,
  tagOverrideErrorForLines,
  unmatchedItems,
});

const {
  applyJobActive,
  applyJobAlertType,
  applyJobImpactLabel,
  applyJobLatestLogMessage,
  applyJobLiveLogExpanded,
  applyJobLiveLogToggleLabel,
  applyJobLiveLogVisible,
  applyJobLogEmptyMessage,
  applyJobLogText,
  applyJobLogTitle,
  applyJobLogWaiting,
  applyJobNowDescriptionIds,
  applyJobNowDetail,
  applyJobNowMessage,
  applyJobNowStatusLabel,
  applyJobNowTitle,
  applyJobPanelStatusLabel,
  applyJobProgressSteps,
  applyJobProgressSummary,
  applyJobSnapshot,
  applyJobStartedLabel,
  applyJobStatusMessage,
  applyJobSucceeded,
  applyJobTitle,
  applyJobUpdateLabel,
  applyJobVerification,
  createApplyJobSnapshot,
  focusApplyJobPanel,
  reconnectObservedApplyJob,
  subscribeApplyJob,
} = usePendingApplyJob({
  applyJobPanelRef,
  loadPendingAndReleaseNotes,
});

function rowKey(row: PendingItem): number {
  return row.line_no;
}

function displayValue(value: string): string {
  return value || "None";
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

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))].sort();
}

function groupedItemServiceKeys(
  group: PendingStackGroup,
  item: PendingGroupedItem,
): string[] {
  return item.services
    .filter(Boolean)
    .map((service) => `${group.name}/${service}`);
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

function riskCues(row: PendingItem): SafetyCue[] {
  return safetyCues(row, {
    pending: updates.pending,
    releaseNote: releaseNoteFor(row),
    releaseNotesLoaded: Boolean(updates.releaseNotes),
    releaseNotesLoading: updates.releaseNotesLoading,
    servicePolicies: settings.servicePolicies,
    snoozes: settings.snoozes,
  });
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
  clearUpdateIntent();
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

  const intent: PendingUpdateIntent = {
    title: input.title,
    contextLabel: input.contextLabel,
    lineNumbers,
    allowTagUpdates: lineNumbersHaveTagUpdates(lineNumbers),
    tagOverrides: tagOverridesForLines(lineNumbers),
    digestPinLabelRewriteApprovals: [],
  };
  setUpdateIntent(intent);
  try {
    await updates.createPlan(
      intent.lineNumbers,
      intent.allowTagUpdates,
      intent.tagOverrides,
      intent.digestPinLabelRewriteApprovals,
    );
  } catch {
    showPreflightModal.value = false;
    clearUpdateIntent();
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
  clearUpdateIntent();
  await Promise.all([
    loadPendingAndReleaseNotes({ preserveCleanup: true }),
    runs.loadRuns(),
  ]);
}

async function confirmApply(): Promise<void> {
  if (!updates.plan || applyDisabled.value) {
    return;
  }
  const lineNumbers = updates.plan.selected_line_numbers;
  const snapshot = createApplyJobSnapshot();
  const payload = applyPlanPayload({
    allowTagUpdates: lineNumbersHaveTagUpdates(lineNumbers),
    tagOverrides: tagOverridesForLines(lineNumbers),
  });
  const job = await updates.applyPlan(
    updates.plan.plan_id,
    lineNumbers,
    payload.allowTagUpdates,
    payload.tagOverrides,
    payload.digestPinLabelRewriteApprovals,
  );
  applyJobSnapshot.value = snapshot;
  subscribeApplyJob(job.job_id);
  showPreflightModal.value = false;
  clearUpdateIntent();
  await focusApplyJobPanel();
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
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="(updates.error || runs.error)" type="error">
      {{ (updates.error || runs.error) }}
    </n-alert>
    <n-alert v-if="settings.pendingSafetyCueError" type="warning">
      Pending safety cues are unavailable: {{ settings.pendingSafetyCueError }}
    </n-alert>
    <n-alert v-if="updates.pending && !updates.pending.exists" type="warning">
      {{ updates.pending.source_file }} is missing.
    </n-alert>
    <n-alert v-if="updates.releaseNotesError" type="warning">
      Release-note metadata is unavailable: {{ updates.releaseNotesError }}
    </n-alert>
    <n-alert v-if="pendingCleanupMessage" type="success">
      {{ pendingCleanupMessage }}
      <n-flex inline class="inline-actions recovery-actions" align="center" :size="8">
        <RouterLink
          class="text-link"
          :to="{ name: 'run-detail', params: { id: updates.pendingCleanup?.audit_run_id } }"
        >
          Details
        </RouterLink>
      </n-flex>
    </n-alert>
    <n-alert
      v-if="updates.applyJobRecovery"
      type="warning"
    >
      {{ updates.applyJobRecovery }}
      <n-flex inline class="inline-actions recovery-actions" align="center" :size="8">
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
      </n-flex>
    </n-alert>

    <PendingApplyJobPanel
      v-if="updates.applyJob"
      ref="applyJobPanelRef"
      v-model:live-log-expanded="applyJobLiveLogExpanded"
      :active="applyJobActive"
      :alert-type="applyJobAlertType"
      :impact-label="applyJobImpactLabel"
      :job="updates.applyJob"
      :latest-log-message="applyJobLatestLogMessage"
      :live-log-toggle-label="applyJobLiveLogToggleLabel"
      :live-log-visible="applyJobLiveLogVisible"
      :log="updates.applyJobLog"
      :log-empty-message="applyJobLogEmptyMessage"
      :log-text="applyJobLogText"
      :log-title="applyJobLogTitle"
      :log-waiting="applyJobLogWaiting"
      :now-description-ids="applyJobNowDescriptionIds"
      :now-detail="applyJobNowDetail"
      :now-message="applyJobNowMessage"
      :now-status-label="applyJobNowStatusLabel"
      :now-title="applyJobNowTitle"
      :panel-status-label="applyJobPanelStatusLabel"
      :progress-steps="applyJobProgressSteps"
      :progress-summary="applyJobProgressSummary"
      :snapshot="applyJobSnapshot"
      :started-label="applyJobStartedLabel"
      :status-message="applyJobStatusMessage"
      :succeeded="applyJobSucceeded"
      :title="applyJobTitle"
      :update-label="applyJobUpdateLabel"
      :verification="applyJobVerification"
    />

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
          <template v-if="dependencySnoozedItems.length">
            - {{ pluralize(dependencySnoozedItems.length, "snoozed item") }}
          </template>
          <template v-if="unmatchedItems.length">
            - {{ unmatchedReviewCountLabel }}
          </template>
        </span>
        <span v-else>Pending file order</span>
      </div>
      <n-flex
        class="inline-actions pending-actions"
        align="center"
        :justify="isMobile ? 'flex-start' : 'flex-end'"
        :size="8"
      >
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
      </n-flex>
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
      <n-flex
        class="inline-actions pending-actions"
        align="center"
        :justify="isMobile ? 'flex-start' : 'flex-end'"
        :size="8"
      >
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
      </n-flex>
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
              <PendingUpdateRow
                v-for="item in group.items"
                :key="`${group.name}-${item.line_no}`"
                :item="item"
                :selected="selectedLineSet.has(item.line_no)"
                :service-label="groupedItemServices(item)"
                :status-label="groupedItemActionLabel(item)"
                :status-tag-type="groupedItemActionTagType(item)"
                :risk-cues="riskCues(item)"
                :tag-rewrite-label="groupedItemTagRewriteLabel(item)"
                :release-note="releaseNoteFor(item)"
                :release-note-status="releaseNoteStatus(releaseNoteFor(item))"
                :release-note-reason="releaseNoteReason(releaseNoteFor(item))"
                show-release-notes
                :show-diagnostic="Boolean(item.diagnostic)"
                :tag-override-value="tagOverrideValue(item)"
                :show-tag-input="Boolean(item.desired_tag)"
                :tag-input-props="tagInputProps(item)"
                @toggle="toggleLine"
                @update-tag="(value) => updateTagOverride(item, value)"
              />
            </div>
          </details>
        </article>

        <article v-if="dependencySnoozedItems.length" class="stack-card needs-review">
          <div class="stack-card-header">
            <div class="stack-title-block">
              <strong>Snoozed pending entries</strong>
              <span class="stack-path">
                Excluded from bulk selection until the dependency service updates successfully.
              </span>
            </div>
            <div class="stack-card-side">
              <div class="stack-card-tags">
                <n-tag size="small" type="default">
                  {{ pluralize(dependencySnoozedItems.length, "item") }}
                </n-tag>
              </div>
            </div>
          </div>
          <details class="stack-details">
            <summary aria-label="Details for snoozed updates">Details</summary>
            <div class="stack-items">
              <PendingUpdateRow
                v-for="{ group, item } in dependencySnoozedItems"
                :key="`dependency-snoozed-${item.line_no}`"
                :item="item"
                :selected="selectedLineSet.has(item.line_no)"
                :group-name="group.name"
                :service-label="groupedItemServices(item)"
                status-label="Snoozed"
                status-tag-type="default"
                :risk-cues="riskCues(item)"
                :show-diagnostic="false"
                :show-release-notes="false"
                :tag-override-value="tagOverrideValue(item)"
                :show-tag-input="Boolean(item.desired_tag)"
                :tag-input-props="tagInputProps(item)"
                @toggle="toggleLine"
                @update-tag="(value) => updateTagOverride(item, value)"
              />
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
              <PendingUpdateRow
                v-for="item in unmatchedItems"
                :key="`unmatched-${item.line_no}`"
                :item="item"
                :selected="selectedLineSet.has(item.line_no)"
                :service-label="item.repo"
                :status-label="staleDiagnosticLabel(item)"
                status-tag-type="warning"
                :risk-cues="[]"
                :meta-detail="staleDiagnosticDetail(item)"
                :show-diagnostic="Boolean(item.diagnostic)"
                :show-release-notes="false"
                :tag-override-value="tagOverrideValue(item)"
                :show-tag-input="Boolean(item.desired_tag)"
                :tag-input-props="tagInputProps(item)"
                @toggle="toggleLine"
                @update-tag="(value) => updateTagOverride(item, value)"
              />
            </div>
          </details>
        </article>

        <div
          v-if="
            !stackGroups.length &&
            !dependencySnoozedItems.length &&
            !unmatchedItems.length
          "
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
                <span
                  v-if="digestProvenanceDisplay(item.digest_provenance)"
                  class="digest-provenance"
                  :title="digestProvenanceDisplay(item.digest_provenance)?.title"
                >
                  <span class="digest-provenance-primary">
                    {{ digestProvenanceDisplay(item.digest_provenance)?.primary }}
                  </span>
                  <code
                    v-if="digestProvenanceDisplay(item.digest_provenance)?.digest"
                    class="digest-value"
                  >
                    {{ digestProvenanceDisplay(item.digest_provenance)?.digest }}
                  </code>
                </span>
                <code v-else-if="item.digest" class="digest-value" :title="item.digest">
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
                    rel="noopener noreferrer"
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
      <n-skeleton aria-hidden="true" height="48px" />
      <n-skeleton aria-hidden="true" height="48px" />
      <n-skeleton aria-hidden="true" height="48px" />
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

    <PendingPlanReviewModal
      v-if="updates.plan"
      :show="showPreflightModal"
      :plan="updates.plan"
      :action-command="actionCommand"
      :apply-button-label="applyButtonLabel"
      :apply-disabled="applyDisabled"
      :apply-preflight="applyPreflight"
      :apply-preflight-attention-checks="applyPreflightAttentionChecks"
      :apply-preflight-check-detail="applyPreflightCheckDetail"
      :apply-preflight-check-label="applyPreflightCheckLabel"
      :apply-preflight-check-type="applyPreflightCheckType"
      :apply-preflight-passed-checks="applyPreflightPassedChecks"
      :apply-preflight-passed-text="applyPreflightPassedText"
      :apply-readiness-status-label="applyReadinessStatusLabel"
      :apply-readiness-status-type="applyReadinessStatusType"
      :apply-readiness-summary="applyReadinessSummary"
      :apply-visible="applyVisible"
      :cleanup-available="cleanupAvailable"
      :cleanup-button-label="cleanupButtonLabel"
      :cleanup-disabled="cleanupDisabled"
      :cleanup-disabled-message="cleanupDisabledMessage"
      :cleanup-items="cleanupItems"
      :cleanup-review-summary="cleanupReviewSummary"
      :digest-pin-label-approval-approved="digestPinLabelApprovalApproved"
      :digest-pin-label-approval-issues="digestPinLabelApprovalIssues"
      :digest-pin-label-issue-proposed-regex="digestPinLabelIssueProposedRegex"
      :issue-detail-string="issueDetailString"
      :issue-hint="issueHint"
      :issue-label="issueLabel"
      :issue-type="issueType"
      :loading="updates.loading"
      :mutation-disabled-message="mutationDisabledMessage"
      :plan-actions="planActions"
      :plan-alert-type="planAlertType"
      :plan-digest-pin-label-rewrites="planDigestPinLabelRewrites"
      :plan-digest-unpin-updates="planDigestUnpinUpdates"
      :plan-lines="planLines"
      :preflight-digest-pin-notice="preflightDigestPinNotice"
      :preflight-digest-unpin-notice="preflightDigestUnpinNotice"
      :preflight-service-impact-label="preflightServiceImpactLabel"
      :preflight-summary="preflightSummary"
      :preflight-tag-rewrite-notice="preflightTagRewriteNotice"
      :preflight-title="preflightTitle"
      :stale-diagnostic-detail="staleDiagnosticDetail"
      :stale-diagnostic-label="staleDiagnosticLabel"
      :visible-plan-issues="visiblePlanIssues"
      @apply="confirmApply"
      @approve-digest-pin-label-rewrite="approveDigestPinLabelRewrite"
      @close="closePreflightModal"
      @open-cleanup="openCleanupModal"
    />

    <PendingCleanupModal
      v-if="updates.plan && cleanupAvailable"
      :show="showCleanupModal"
      :assistant-actions="cleanupAssistantActions"
      :assistant-findings="cleanupAssistantFindings"
      :assistant-reasons="cleanupAssistantReasons"
      :cleanup-button-label="cleanupButtonLabel"
      :cleanup-disabled="cleanupDisabled"
      :cleanup-items="cleanupItems"
      :cleanup-line-label="cleanupLineLabel"
      :loading="updates.loading"
      :pending-source-label="pendingSourceLabel"
      @close="closeCleanupModal"
      @confirm="confirmCleanup"
    />

    <PendingRemovalModal
      v-if="updates.pendingRemovalPlan"
      :show="showRemovalModal"
      :loading="updates.loading"
      :pending-source-label="pendingSourceLabel"
      :removal-confirm-button-label="removalConfirmButtonLabel"
      :removal-disabled="removalDisabled"
      :removal-items="removalItems"
      :removal-line-label="removalLineLabel"
      @close="closeRemovalModal"
      @confirm="confirmSelectedRemoval"
    />
  </section>
</template>

<style scoped>
.pending-heading {
  align-items: center;
}

.pending-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.selection-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 56px;
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: var(--shadow-panel-lift);
}

.batch-action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 58px;
  padding: 10px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: var(--shadow-panel-lift);
}

.pending-loading-state {
  display: grid;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: var(--shadow-panel-lift);
}

.pending-error-state {
  gap: 8px;
  padding: 18px;
  text-align: center;
}

.selection-summary {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.selection-summary strong,
.selection-summary span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.selection-summary strong {
  font-size: 0.95rem;
}

.selection-summary span {
  color: var(--color-muted-text);
  font-size: 0.82rem;
}

.stack-selection {
  display: grid;
  gap: 12px;
}

.stack-card {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: var(--shadow-panel-lift);
}

.stack-card.selected {
  border-color: var(--color-border-hover);
}

.stack-card.needs-review {
  background: var(--color-panel-tint);
}

.stack-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.stack-card-side {
  display: grid;
  justify-items: end;
  gap: 8px;
  min-width: 0;
}

.stack-title-block {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.stack-title-block strong {
  min-width: 0;
  overflow-wrap: anywhere;
}

.stack-title-block :deep(.n-checkbox__label) {
  padding-inline: 6px 0;
}

.stack-checkbox-label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  box-sizing: border-box;
  min-height: 30px;
  padding: 5px 10px;
  border: 1px solid color-mix(in srgb,
      var(--color-border-hover) 42%,
      var(--color-border-subtle));
  border-radius: 7px;
  background: color-mix(in srgb,
      var(--color-surface) 94%,
      var(--color-action-blue) 6%);
  color: var(--color-text-secondary);
  font-size: 0.875rem;
  line-height: 1.35;
  transition:
    border-color var(--motion-base) var(--ease-out-quart),
    background-color var(--motion-base) var(--ease-out-quart);
}

.stack-title-block :deep(.n-checkbox:hover) .stack-checkbox-label {
  border-color: var(--color-border-hover);
  background: color-mix(in srgb,
      var(--color-surface) 90%,
      var(--color-action-blue) 10%);
}

.stack-checkbox-label strong {
  color: var(--color-ink);
}

.stack-checkbox-kicker {
  color: var(--color-muted-text);
  font-size: 0.76rem;
  font-weight: 700;
  line-height: 1;
}

.stack-path {
  color: var(--color-muted-text);
  font-size: 0.82rem;
  overflow-wrap: anywhere;
}

.stack-identity {
  display: grid;
  gap: 3px;
  color: var(--color-text-secondary);
  font-size: 0.84rem;
  line-height: 1.35;
}

.stack-identity span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.identity-label {
  margin-right: 6px;
  color: var(--color-muted-text);
  font-weight: 700;
}

.stack-change-preview {
  display: grid;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--color-border-subtle);
}

.stack-change-row {
  display: grid;
  grid-template-columns: minmax(120px, 0.32fr) minmax(0, 1fr);
  gap: 10px;
  min-width: 0;
  color: var(--color-text-secondary);
  font-size: 0.84rem;
  line-height: 1.4;
}

.stack-change-service,
.stack-change-target,
.stack-change-target code,
.stack-change-more {
  min-width: 0;
  overflow-wrap: anywhere;
}

.stack-change-service {
  color: var(--color-ink);
}

.stack-change-target {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px 7px;
}

.stack-change-target code {
  color: var(--color-code-text);
  font-family: var(--font-mono);
  font-size: 0.82rem;
}

.stack-change-more {
  color: var(--color-muted-text);
  font-size: 0.82rem;
}

.stack-card-tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  min-width: 0;
}

.stack-card-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.stack-details {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.stack-details summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
  min-height: 32px;
  cursor: pointer;
  color: var(--color-action-blue);
  font-size: 0.86rem;
  font-weight: 700;
}

.stack-details summary::before {
  content: "";
  width: 0;
  height: 0;
  border-top: 4px solid transparent;
  border-bottom: 4px solid transparent;
  border-left: 5px solid currentColor;
  transition: transform 180ms ease-out;
}

.stack-details[open] summary::before {
  transform: rotate(90deg);
}

.stack-details[open] summary {
  margin-bottom: 8px;
}

.stack-items {
  display: grid;
  border-top: 1px solid var(--color-border-subtle);
}

.recovery-actions {
  flex-wrap: wrap;
  margin-top: 8px;
}

.stack-change-risk-cues {
  display: inline-flex;
}

@media (max-width: 920px) {
  .selection-toolbar,
  .batch-action-bar,
  .stack-card-header {
    align-items: flex-start;
  }
}

@media (max-width: 560px) {
  .selection-toolbar,
  .batch-action-bar,
  .stack-card-header {
    display: grid;
  }

  .pending-actions :deep(.n-button),
  .stack-card-actions :deep(.n-button) {
    min-width: 44px;
    min-height: 44px;
  }

  .stack-details summary {
    min-height: 44px;
  }

  .pending-actions :deep(.n-checkbox),
  .stack-title-block :deep(.n-checkbox) {
    min-height: 44px;
    display: inline-flex;
    align-items: center;
  }

  .stack-card-tags {
    justify-content: flex-start;
  }

  .stack-change-row {
    grid-template-columns: 1fr;
    gap: 4px;
  }

  .stack-change-target {
    display: grid;
    align-items: start;
    gap: 5px;
  }

  .stack-change-target > :deep(.n-tag) {
    width: fit-content;
  }

  .stack-change-target > span[aria-hidden="true"] {
    display: none;
  }

  .stack-change-target code {
    display: block;
  }

  .stack-change-value::before {
    content: attr(data-label);
    display: block;
    margin-bottom: 1px;
    color: var(--color-muted-text);
    font-family: var(--font-sans);
    font-size: 0.74rem;
    font-weight: 700;
    line-height: 1.2;
  }

  .stack-card-side,
  .stack-card-actions {
    justify-items: start;
    justify-content: flex-start;
  }

  .pending-actions {
    justify-content: flex-start;
  }
}
</style>

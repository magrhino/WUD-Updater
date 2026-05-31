<script setup lang="ts">
import { computed, h, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
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
  NInput,
  NModal,
  NTag,
  type DataTableColumns,
  type DataTableRowKey,
} from "naive-ui";

import {
  webApi,
  type ApplyJobLogResponse,
  type ApplyJobResponse,
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
import { useAuthStore } from "../stores/auth";
import { useWebuiStore } from "../stores/webui";

const webui = useWebuiStore();
const auth = useAuthStore();
const breakpoints = useBreakpoints(breakpointsTailwind);
const isMobile = breakpoints.smaller("md");
const selectedLineNumbers = ref<number[]>([]);
const tagOverrides = ref<Record<number, string>>({});
const showPreflightModal = ref(false);
const showCleanupModal = ref(false);
const showRemovalModal = ref(false);
const showApplyJobModal = ref(false);
const jobEventSource = ref<EventSource | null>(null);
const applyJobPanelRef = ref<HTMLElement | null>(null);
const applyJobModalTitleRef = ref<HTMLElement | null>(null);
const applyJobPanelLogRef = ref<HTMLElement | null>(null);
const applyJobModalLogRef = ref<HTMLElement | null>(null);
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
};

type ApplyJobSnapshotLine = {
  key: string;
  lineNo: number;
  serviceLabel: string;
  tagRewriteLabel: string;
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

const updateIntent = ref<UpdateIntent | null>(null);
const applyJobSnapshot = ref<ApplyJobPlanSnapshot | null>(null);

const columns = computed<DataTableColumns<PendingItem>>(() => [
  { type: "selection", width: 48 },
  { title: "Line", key: "line_no", width: 80 },
  { title: "Image", key: "image", minWidth: 240 },
  { title: "Repository", key: "repo", minWidth: 200 },
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
    title: "Release notes",
    key: "release_notes",
    minWidth: 220,
    render: (row) => renderReleaseNotes(row),
  },
]);

const allLineNumbers = computed(
  () => webui.pending?.items.map((item) => item.line_no) ?? [],
);
const groupingReady = computed(
  () => webui.pending?.grouping.status === "ready",
);
const stackGroups = computed(() =>
  groupingReady.value ? (webui.pending?.grouping.groups ?? []) : [],
);
const unmatchedItems = computed(() =>
  groupingReady.value ? (webui.pending?.grouping.unmatched ?? []) : [],
);
const stackLineNumbers = computed(() =>
  uniqueSorted(stackGroups.value.flatMap((group) => group.line_numbers)),
);
const selectableLineNumbers = computed(() =>
  groupingReady.value ? stackLineNumbers.value : allLineNumbers.value,
);
const selectAllLabel = computed(() =>
  groupingReady.value ? "Select all stack updates" : "Select all",
);
const releaseNotesByLine = computed(() => {
  const notes = new Map<number, ReleaseNoteInfo>();
  for (const item of webui.releaseNotes?.items ?? []) {
    notes.set(item.line_no, item);
  }
  return notes;
});
const latestRun = computed(() => webui.runs[0] ?? null);
const pendingSourceFile = computed(() => webui.pending?.source_file ?? "Pending file");
const pendingSourceLabel = computed(() => fileName(pendingSourceFile.value));
const pendingSourceDisplay = computed(() =>
  webui.pending?.source_file ? `Source ${pendingSourceLabel.value}` : "Pending file",
);
const selectedLineSet = computed(() => new Set(selectedLineNumbers.value));
const mutationStateLabel = computed(() =>
  auth.session?.mutations_enabled ? "Mutations enabled" : "Read-only",
);
const mutationStateType = computed(() =>
  auth.session?.mutations_enabled ? "warning" : "success",
);
const selectedTagOverrideError = computed(() => {
  return tagOverrideErrorForLines(selectedLineNumbers.value);
});
const updateSelectedDisabled = computed(
  () =>
    selectedLineNumbers.value.length === 0 ||
    webui.loading ||
    Boolean(selectedTagOverrideError.value),
);
const removeSelectedDisabled = computed(
  () =>
    selectedLineNumbers.value.length === 0 ||
    webui.loading ||
    !auth.session?.mutations_enabled,
);
const removeSelectedDisabledMessage = computed(() => {
  if (!selectedLineNumbers.value.length || auth.session?.mutations_enabled) {
    return "";
  }
  return "Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to remove selected entries.";
});
const planAlertType = computed(() => {
  if (webui.plan?.status === "blocked") {
    return "error";
  }
  if (webui.plan?.status === "empty") {
    return "warning";
  }
  return "info";
});
const planContextLabel = computed(() => {
  if (!webui.plan) {
    return updateIntent.value?.contextLabel ?? "selected updates";
  }
  if (webui.plan.stacks.length === 1) {
    return webui.plan.stacks[0].name;
  }
  if (webui.plan.summary.stack_count > 1) {
    return pluralize(webui.plan.summary.stack_count, "stack");
  }
  return updateIntent.value?.contextLabel ?? "selected updates";
});
const preflightTitle = computed(() => {
  if (!webui.plan) {
    return updateIntent.value?.title ?? "Preview selected plan";
  }
  if (webui.plan.status === "blocked") {
    return "Plan blocked";
  }
  if (webui.plan.status === "empty") {
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
  if (!webui.plan) {
    return "";
  }
  if (webui.plan.status === "blocked") {
    const issueCount = webui.plan.summary.issue_count || webui.plan.issues.length;
    return `${pluralize(issueCount, "issue")} must be fixed before applying.`;
  }
  if (webui.plan.status === "empty") {
    return "No selected services need changes.";
  }
  const serviceCount =
    webui.plan.summary.service_count ||
    webui.plan.summary.target_count ||
    webui.plan.selected_line_numbers.length;
  return `${pluralize(serviceCount, "service")} ready to update.`;
});
const preflightServiceImpactLabel = computed(() => {
  if (!webui.plan || webui.plan.status !== "ready") {
    return "";
  }
  return summarizeList(
    planLines.value.map(({ stack, line }) =>
      webui.plan && webui.plan.summary.stack_count > 1
        ? `${stack} / ${line.service || "stack-level"}`
        : line.service || "stack-level",
    ),
    4,
  );
});
const applyAvailable = computed(
  () => webui.plan?.status === "ready" && webui.plan.can_apply,
);
const applyDisabled = computed(() => !applyAvailable.value || webui.loading);
const applyButtonLabel = computed(() =>
  webui.plan?.selected_line_numbers.length
    ? `Apply ${pluralize(webui.plan.selected_line_numbers.length, "update")}`
    : "Apply selected updates",
);
const cleanupItems = computed(() => webui.plan?.cleanup.items ?? []);
const cleanupAvailable = computed(() => cleanupItems.value.length > 0);
const cleanupButtonLabel = computed(() =>
  `Remove ${pluralize(cleanupItems.value.length, "unmatched entry", "unmatched entries")}`,
);
const cleanupDisabled = computed(
  () => !webui.plan?.cleanup.can_remove_unmatched || webui.loading,
);
const cleanupDisabledMessage = computed(() => {
  if (!webui.plan || !cleanupAvailable.value || webui.plan.cleanup.can_remove_unmatched) {
    return "";
  }
  if (!auth.session?.mutations_enabled) {
    return "Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to remove stale pending entries.";
  }
  return "These pending entries cannot be removed right now.";
});
const pendingCleanupMessage = computed(() => {
  if (!webui.pendingCleanup) {
    return "";
  }
  return `${pluralize(webui.pendingCleanup.removed_count, "pending entry", "pending entries")} removed from ${pendingSourceLabel.value}.`;
});
const removalItems = computed(() => webui.pendingRemovalPlan?.lines ?? []);
const removalButtonLabel = computed(() =>
  `Remove ${pluralize(selectedLineNumbers.value.length, "selected entry", "selected entries")}`,
);
const removalConfirmButtonLabel = computed(() =>
  `Remove ${pluralize(removalItems.value.length, "selected entry", "selected entries")}`,
);
const removalDisabled = computed(
  () => !webui.pendingRemovalPlan?.can_remove || webui.loading,
);
const mutationDisabledMessage = computed(() => {
  if (!webui.plan || webui.plan.status !== "ready" || webui.plan.can_apply) {
    return "";
  }
  if (!auth.session?.mutations_enabled) {
    return "Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to apply updates.";
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
  webui.plan?.stacks.flatMap((stack) =>
    stack.lines.map((line) => ({ stack: stack.name, line })),
  ) ?? [],
);
const planActions = computed(() =>
  webui.plan?.stacks.flatMap((stack) =>
    stack.actions.map((action) => ({ stack: stack.name, action })),
  ) ?? [],
);
const planTagUpdates = computed(() =>
  webui.plan?.stacks.flatMap((stack) =>
    stack.tag_updates.map((update) => ({ stack: stack.name, update })),
  ) ?? [],
);
const plannedTagRewriteLines = computed(() =>
  planLines.value.filter(({ line }) => Boolean(line.desired_tag)),
);
const visibleTagRewriteCount = computed(
  () => planTagUpdates.value.length || plannedTagRewriteLines.value.length,
);
const preflightTagRewriteNotice = computed(() => {
  if (!updateIntent.value?.allowTagUpdates || !visibleTagRewriteCount.value || !webui.plan) {
    return "";
  }
  return `${pluralize(visibleTagRewriteCount.value, "tag rewrite")} will be applied before recreating selected services.`;
});
const applyJobAlertType = computed(() => {
  if (webui.applyJob?.status === "failure") {
    return "error";
  }
  if (webui.applyJob?.status === "success") {
    return "success";
  }
  return "info";
});
const applyJobActive = computed(
  () => Boolean(webui.applyJob && !terminalJobStatuses.has(webui.applyJob.status)),
);
const applyJobSucceeded = computed(() => webui.applyJob?.status === "success");
const applyJobUpdateCount = computed(
  () =>
    webui.applyJob?.selected_line_numbers.length ||
    applyJobSnapshot.value?.lines.length ||
    0,
);
const applyJobUpdateLabel = computed(() =>
  pluralize(applyJobUpdateCount.value, "update"),
);
const applyJobTitle = computed(() => {
  if (!webui.applyJob) {
    return "";
  }
  if (webui.applyJob.status === "queued" || webui.applyJob.status === "running") {
    return `Applying ${applyJobUpdateLabel.value}`;
  }
  if (webui.applyJob.status === "success") {
    return "Apply complete";
  }
  if (webui.applyJob.status === "failure") {
    return "Apply failed";
  }
  return "Apply job";
});
const applyJobStatusMessage = computed(() => {
  if (!webui.applyJob) {
    return "";
  }
  if (webui.applyJob.status === "queued") {
    return "Waiting for the updater job to start.";
  }
  if (webui.applyJob.status === "running") {
    return "Updater command is running.";
  }
  if (webui.applyJob.status === "success") {
    return `${applyJobUpdateLabel.value} finished. Pending updates and run history were refreshed.`;
  }
  if (webui.applyJob.error) {
    return webui.applyJob.error;
  }
  return "Updater stopped before completing the selected updates.";
});
const applyJobStartedLabel = computed(() => {
  if (!webui.applyJob) {
    return "";
  }
  return webui.applyJob.started_at || "Queued";
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
const applyJobLogText = computed(() => webui.applyJobLog?.content ?? "");
const applyJobLogTitle = computed(
  () => webui.applyJobLog?.log_file || webui.applyJob?.log_file || "Live log",
);
const applyJobLogEmptyMessage = computed(() =>
  applyJobActive.value ? "Waiting for log output." : "No live log was captured.",
);
const applyJobLogWaiting = computed(() => {
  const log = webui.applyJobLog;
  if (!log || log.error) {
    return !log;
  }
  return !log.exists && !log.content;
});

function rowKey(row: PendingItem): number {
  return row.line_no;
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
  if (webui.releaseNotesLoading) {
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
  return (webui.pending?.items ?? []).filter((item) => lineSet.has(item.line_no));
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
      const original = webui.pending?.items.find(
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
  webui.clearPlan();
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
  selectedLineNumbers.value = keys
    .map((key) => Number(key))
    .filter((key) => Number.isFinite(key))
    .sort((left, right) => left - right);
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
    webui.loading ||
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
  if (lineNumbers.length === 0 || webui.loading) {
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
  };
  updateIntent.value = intent;
  try {
    await webui.createPlan(
      intent.lineNumbers,
      intent.allowTagUpdates,
      intent.tagOverrides,
    );
  } catch {
    showPreflightModal.value = false;
    updateIntent.value = null;
    return;
  }
  if (webui.plan) {
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
    await webui.createRemovalPlan(lineNumbers);
  } catch {
    showRemovalModal.value = false;
    return;
  }
  if (webui.pendingRemovalPlan?.lines.length) {
    showRemovalModal.value = true;
  }
}

function closeRemovalModal(): void {
  showRemovalModal.value = false;
  webui.clearPlan();
}

async function confirmSelectedRemoval(): Promise<void> {
  const removal = webui.pendingRemovalPlan;
  if (!removal?.removal_id || removalDisabled.value || !removal.lines.length) {
    return;
  }
  const result = await webui.removeSelectedPending(
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
    webui.loadRuns(),
  ]);
}

async function confirmCleanup(): Promise<void> {
  const cleanup = webui.plan?.cleanup;
  if (!cleanup?.cleanup_id || cleanupDisabled.value || !cleanup.items.length) {
    return;
  }
  const result = await webui.cleanupPending(
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
    webui.loadRuns(),
  ]);
}

async function confirmApply(): Promise<void> {
  if (!webui.plan || applyDisabled.value) {
    return;
  }
  const intent = updateIntent.value;
  const lineNumbers = webui.plan.selected_line_numbers;
  const snapshot = createApplyJobSnapshot();
  const job = await webui.createJob(
    webui.plan.plan_id,
    lineNumbers,
    intent?.allowTagUpdates ?? lineNumbersHaveTagUpdates(lineNumbers),
    intent?.tagOverrides ?? tagOverridesForLines(lineNumbers),
  );
  applyJobSnapshot.value = snapshot;
  subscribeApplyJob(job.job_id);
  showApplyJobModal.value = true;
  showPreflightModal.value = false;
  updateIntent.value = null;
  await focusApplyJobModal();
}

function subscribeApplyJob(jobId: string): void {
  closeJobStream();
  const source = webApi.openJobStream(jobId);
  jobEventSource.value = source;
  source.addEventListener("job", (event) => {
    void handleJobEvent(event as MessageEvent<string>);
  });
  source.addEventListener("log", (event) => {
    void handleJobLogEvent(event as MessageEvent<string>);
  });
  source.onerror = () => {
    if (webui.applyJob && terminalJobStatuses.has(webui.applyJob.status)) {
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
    webui.setError("Job status stream returned invalid data.");
    closeJobStream();
    return;
  }
  webui.setApplyJob(job);
  if (!terminalJobStatuses.has(job.status)) {
    return;
  }
  await loadTerminalApplyJobLogIfMissing(job);
  closeJobStream();
  await refreshAfterTerminalJob();
}

async function loadTerminalApplyJobLogIfMissing(
  job: ApplyJobResponse | null = webui.applyJob,
): Promise<void> {
  if (
    !job?.run_id ||
    !terminalJobStatuses.has(job.status) ||
    webui.applyJobLog?.content ||
    applyJobRunLogFallbackRunId.value === job.run_id
  ) {
    return;
  }
  applyJobRunLogFallbackRunId.value = job.run_id;
  await webui.loadApplyJobLogFromRun(job);
}

async function handleJobLogEvent(event: MessageEvent<string>): Promise<void> {
  let log: ApplyJobLogResponse;
  try {
    log = JSON.parse(event.data) as ApplyJobLogResponse;
  } catch {
    webui.setError("Job log stream returned invalid data.");
    return;
  }
  const panelShouldScroll = shouldAutoScrollLog(applyJobPanelLogRef.value);
  const modalShouldScroll = shouldAutoScrollLog(applyJobModalLogRef.value);
  webui.setApplyJobLog(log);
  await nextTick();
  if (panelShouldScroll) {
    scrollLogToBottom(applyJobPanelLogRef.value);
  }
  if (modalShouldScroll) {
    scrollLogToBottom(applyJobModalLogRef.value);
  }
}

function closeJobStream(): void {
  jobEventSource.value?.close();
  jobEventSource.value = null;
}

async function recoverOrRefreshApplyJob(jobId: string): Promise<void> {
  const job = await webui
    .loadApplyJob(jobId, { recoverMissing: true })
    .catch(() => undefined);
  if (job === undefined) {
    return;
  }
  if (job === null) {
    closeJobStream();
    await webui.loadRuns().catch(() => undefined);
    return;
  }
  if (terminalJobStatuses.has(job.status)) {
    closeJobStream();
    await refreshAfterTerminalJob();
  }
}

async function reconnectObservedApplyJob(): Promise<void> {
  if (!webui.rememberedApplyJobId) {
    return;
  }
  const job = await webui
    .loadApplyJob(webui.rememberedApplyJobId, { recoverMissing: true })
    .catch(() => undefined);
  if (job === undefined) {
    return;
  }
  if (job === null) {
    await webui.loadRuns().catch(() => undefined);
    return;
  }
  if (terminalJobStatuses.has(job.status)) {
    await refreshAfterTerminalJob();
    return;
  }
  subscribeApplyJob(job.job_id);
}

async function refreshAfterTerminalJob(): Promise<void> {
  await Promise.all([loadPendingAndReleaseNotes(), webui.loadRuns()]);
}

function createApplyJobSnapshot(): ApplyJobPlanSnapshot | null {
  if (!webui.plan) {
    return null;
  }
  return {
    contextLabel: planContextLabel.value,
    serviceCount:
      webui.plan.summary.service_count ||
      webui.plan.summary.target_count ||
      planLines.value.length,
    stackCount: webui.plan.summary.stack_count,
    sourceFile: webui.plan.source_file,
    lines: planLines.value.map(({ stack, line }) => ({
      key: `${stack}-${line.line_no}-${line.service}`,
      lineNo: line.line_no,
      serviceLabel: planLineServiceLabel(stack, line),
      tagRewriteLabel: planLineTagRewriteLabel(line),
      composeImage: line.compose_image,
      targetImage: line.target_image,
    })),
  };
}

async function focusApplyJobModal(): Promise<void> {
  await nextTick();
  applyJobModalTitleRef.value?.focus({ preventScroll: true });
}

async function focusApplyJobPanel(): Promise<void> {
  await nextTick();
  const panel = applyJobPanelRef.value;
  if (!panel) {
    return;
  }
  panel.scrollIntoView({
    block: "start",
    behavior: prefersReducedMotion() ? "auto" : "smooth",
  });
  panel.focus({ preventScroll: true });
}

function closeApplyJobModal(): void {
  showApplyJobModal.value = false;
  void focusApplyJobPanel();
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

function unmatchedDiagnosticMessage(item: PendingGroupedItem): string {
  return item.diagnostic?.message || "No Compose stack matched this WUD entry.";
}

function unmatchedDiagnosticHint(item: PendingGroupedItem): string {
  return item.diagnostic?.hint || "";
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
  return item.action === "tag-update" ? "Tag update" : "Image update";
}

function groupedItemTagRewriteLabel(item: PendingGroupedItem): string {
  if (!item.desired_tag) {
    return "";
  }
  return `${item.image} -> ${groupedItemTarget(item)}`;
}

function planLineServiceLabel(stack: string, line: PlanLine): string {
  const service = line.service || "stack-level";
  return webui.plan?.summary.stack_count && webui.plan.summary.stack_count > 1
    ? `${stack} / ${service}`
    : service;
}

function planLineTagRewriteLabel(line: PlanLine): string {
  if (!line.desired_tag) {
    return "";
  }
  return `${line.compose_image} -> ${line.target_image}`;
}

async function loadPendingAndReleaseNotes(
  options: { preserveCleanup?: boolean } = {},
): Promise<void> {
  await webui.loadPending(options);
  await webui.loadReleaseNotes().catch(() => undefined);
  void webui.refreshReleaseNotes().catch(() => undefined);
}

onMounted(() => {
  void loadPendingAndReleaseNotes();
  void reconnectObservedApplyJob();
});

watch(
  () => webui.pending?.items ?? [],
  (items) => {
    const next: Record<number, string> = {};
    for (const item of items) {
      if (item.desired_tag) {
        next[item.line_no] = tagOverrides.value[item.line_no] ?? item.desired_tag;
      }
    }
    tagOverrides.value = next;
  },
  { immediate: true },
);

onUnmounted(() => {
  closeJobStream();
});

watch(
  () => webui.applyJob?.job_id ?? "",
  (jobId) => {
    if (!jobId) {
      showApplyJobModal.value = false;
    }
  },
);

watch(
  () => [webui.applyJob?.status, webui.applyJob?.run_id] as const,
  () => {
    void loadTerminalApplyJobLogIfMissing();
  },
  { immediate: true },
);
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="webui.error" type="error">
      {{ webui.error }}
    </n-alert>
    <n-alert v-if="webui.pending && !webui.pending.exists" type="warning">
      {{ webui.pending.source_file }} is missing.
    </n-alert>
    <n-alert v-if="webui.releaseNotesError" type="warning">
      Release-note metadata is unavailable: {{ webui.releaseNotesError }}
    </n-alert>
    <n-alert v-if="pendingCleanupMessage" type="success">
      {{ pendingCleanupMessage }}
      <span class="inline-actions recovery-actions">
        <RouterLink
          class="text-link"
          :to="{ name: 'run-detail', params: { id: webui.pendingCleanup?.audit_run_id } }"
        >
          Details
        </RouterLink>
      </span>
    </n-alert>
    <n-alert
      v-if="webui.applyJobRecovery"
      type="warning"
    >
      {{ webui.applyJobRecovery }}
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
      v-if="webui.applyJob"
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
        <n-tag :type="applyJobAlertType">{{ webui.applyJob.status }}</n-tag>
      </div>

      <div v-if="applyJobActive" class="apply-job-progress" aria-hidden="true">
        <span />
      </div>

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
          <div v-if="webui.applyJob.run_id" class="list-row">
            <span>Run</span>
            <strong>#{{ webui.applyJob.run_id }}</strong>
            <em class="inline-actions">
              <RouterLink
                class="text-link"
                :to="{ name: 'run-detail', params: { id: webui.applyJob.run_id } }"
              >
                Details
              </RouterLink>
              <RouterLink
                class="text-link"
                :to="{ name: 'run-log', params: { id: webui.applyJob.run_id } }"
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

      <section class="apply-job-live-log" aria-labelledby="apply-job-log-title">
        <div class="apply-job-impact-heading">
          <strong id="apply-job-log-title">Live log</strong>
          <span class="apply-job-log-path">{{ applyJobLogTitle }}</span>
        </div>
        <n-alert
          v-if="webui.applyJobLog?.truncated"
          class="preflight-block"
          type="warning"
          :show-icon="false"
        >
          Showing the last {{ webui.applyJobLog.max_bytes }} bytes.
        </n-alert>
        <n-alert
          v-if="webui.applyJobLog?.error"
          class="preflight-block"
          type="warning"
          :show-icon="false"
        >
          Live log unavailable: {{ webui.applyJobLog.error }}
        </n-alert>
        <div v-if="applyJobLogWaiting" class="empty-state">
          {{ applyJobLogEmptyMessage }}
        </div>
        <pre
          v-else-if="!webui.applyJobLog?.error"
          ref="applyJobPanelLogRef"
          class="log-viewer apply-job-log-viewer"
        >{{ applyJobLogText }}</pre>
      </section>

      <n-alert
        v-if="webui.applyJob.error"
        class="plan-section"
        type="error"
      >
        {{ webui.applyJob.error }}
      </n-alert>
    </section>

    <div class="section-heading pending-heading">
      <div>
        <p class="eyebrow value-eyebrow pending-source" :title="pendingSourceFile">
          {{ pendingSourceDisplay }}
        </p>
        <h2>{{ webui.pending?.count ?? 0 }} pending updates</h2>
      </div>
      <n-tag size="small" :type="mutationStateType">{{ mutationStateLabel }}</n-tag>
    </div>

    <div class="selection-toolbar">
      <div class="selection-summary">
        <strong>{{ selectedLineNumbers.length }} selected</strong>
        <span v-if="groupingReady">
          {{ pluralize(stackGroups.length, "stack") }} available
          <template v-if="unmatchedItems.length">
            - {{ pluralize(unmatchedItems.length, "item") }} needs review
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

    <div v-if="selectedLineNumbers.length" class="batch-action-bar">
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
          :loading="webui.loading"
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
          :loading="webui.loading"
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
                <span class="sr-only">Select stack </span>
                <strong :title="group.directory">{{ group.name }}</strong>
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
                  :loading="webui.loading"
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
                  :type="item.action === 'tag-update' ? 'warning' : 'default'"
                >
                  {{ groupedItemActionLabel(item) }}
                </n-tag>
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
                  <n-tag size="small">{{ groupedItemActionLabel(item) }}</n-tag>
                </div>
                <div class="pending-update-detail">
                  <code>{{ item.image }}</code>
                  <span>-></span>
                  <code>{{ groupedItemTarget(item) }}</code>
                </div>
                <div class="pending-update-meta">
                  <span>Pending file line #{{ item.line_no }}</span>
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
              <strong>Needs review</strong>
              <span class="stack-path">
                These pending updates are not matched to a Compose stack yet.
              </span>
            </div>
            <div class="stack-card-side">
              <div class="stack-card-tags">
                <n-tag size="small" type="warning">
                  {{ pluralize(unmatchedItems.length, "item") }}
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
                  <n-tag size="small" type="warning">Needs review</n-tag>
                </div>
                <div class="pending-update-detail">
                  <code>{{ item.image }}</code>
                  <span>-></span>
                  <code>{{ groupedItemTarget(item) }}</code>
                </div>
                <div class="pending-update-meta">
                  <span>Pending file line #{{ item.line_no }}</span>
                  <span>{{ unmatchedDiagnosticMessage(item) }}</span>
                  <span v-if="unmatchedDiagnosticHint(item)">
                    {{ unmatchedDiagnosticHint(item) }}
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

    <template v-else-if="webui.pending">
      <n-alert type="info">
        Stack grouping is unavailable. Showing pending file order.
      </n-alert>

      <div
        v-if="!webui.pending?.items.length"
        class="empty-state clear-queue-state"
        role="status"
        aria-live="polite"
      >
        <span class="clear-queue-mark" aria-hidden="true">
          <CheckCircle2 :size="24" />
        </span>
        <strong>Update queue is clear</strong>
        <span>{{ pendingSourceLabel }} has no updates waiting for review.</span>
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
        :data="webui.pending?.items ?? []"
        :loading="webui.loading"
        :pagination="{ pageSize: 15 }"
        :row-key="rowKey"
        :checked-row-keys="selectedLineNumbers"
        size="small"
        class="data-surface"
        @update:checked-row-keys="updateCheckedRowKeys"
      />

      <div v-else class="mobile-list">
        <article v-for="item in webui.pending?.items ?? []" :key="item.line_no" class="mobile-card">
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

    <n-modal
      v-if="webui.plan"
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
          <n-tag :type="planAlertType">{{ webui.plan.status }}</n-tag>
        </div>

        <div class="preflight-metrics">
          <div>
            <span>Targets</span>
            <strong>{{ webui.plan.summary.target_count }}</strong>
          </div>
          <div>
            <span>Matched</span>
            <strong>{{ webui.plan.summary.matched_target_count }}</strong>
          </div>
          <div>
            <span>Stacks</span>
            <strong>{{ webui.plan.summary.stack_count }}</strong>
          </div>
          <div>
            <span>Issues</span>
            <strong>{{ webui.plan.summary.issue_count }}</strong>
          </div>
        </div>

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
          <div class="compact-list">
            <div
              v-for="item in cleanupItems"
              :key="`cleanup-${item.line_no}`"
              class="list-row plan-line-row"
            >
              <span>#{{ item.line_no }}</span>
              <strong>{{ item.image }}</strong>
              <em>
                <span>{{ item.diagnostic?.message || item.reason }}</span>
                <span v-if="item.diagnostic?.hint">{{ item.diagnostic.hint }}</span>
              </em>
            </div>
          </div>
        </section>

        <section
          v-if="webui.plan.status === 'ready'"
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

        <div v-if="webui.plan.issues.length" class="warning-list preflight-block">
          <n-alert
            v-for="issue in webui.plan.issues"
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
            v-if="webui.plan.status !== 'ready'"
            class="preflight-details"
            :open="webui.plan.status === 'blocked'"
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

          <details v-if="webui.plan.skipped.length" class="preflight-details" open>
            <summary>Skipped</summary>
            <div class="compact-list">
              <div v-for="item in webui.plan.skipped" :key="item.line_no" class="list-row">
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
                v-for="lineNo in webui.plan.selected_line_numbers"
                :key="lineNo"
                class="list-row"
              >
                <span>Line</span>
                <strong>#{{ lineNo }}</strong>
                <em>{{ webui.plan.source_file }}</em>
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
            :loading="webui.loading"
            @click="openCleanupModal"
          >
            <template #icon>
              <Trash2 :size="16" />
            </template>
            {{ cleanupButtonLabel }}
          </n-button>
          <n-button
            v-if="applyAvailable"
            type="primary"
            size="small"
            :disabled="applyDisabled"
            :loading="webui.loading"
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
      v-if="webui.plan && cleanupAvailable"
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
            :loading="webui.loading"
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
      v-if="webui.pendingRemovalPlan"
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
            :loading="webui.loading"
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

    <n-modal
      v-if="webui.applyJob"
      v-model:show="showApplyJobModal"
      :mask-closable="false"
    >
      <section
        class="preflight-modal apply-job-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="apply-job-modal-title"
      >
        <div class="section-heading apply-job-heading">
          <div>
            <p class="eyebrow">Apply job</p>
            <div class="apply-job-heading-title">
              <span
                v-if="applyJobSucceeded"
                class="apply-job-complete-mark"
                aria-hidden="true"
              >
                <CheckCircle2 :size="18" />
              </span>
              <h2
                id="apply-job-modal-title"
                ref="applyJobModalTitleRef"
                tabindex="-1"
              >
                {{ applyJobTitle }}
              </h2>
            </div>
            <p class="apply-job-summary" role="status" aria-live="polite">
              {{ applyJobStatusMessage }}
            </p>
          </div>
          <n-tag :type="applyJobAlertType">{{ webui.applyJob.status }}</n-tag>
        </div>

        <div v-if="applyJobActive" class="apply-job-progress" aria-hidden="true">
          <span />
        </div>

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
            <div v-if="webui.applyJob.run_id" class="list-row">
              <span>Run</span>
              <strong>#{{ webui.applyJob.run_id }}</strong>
              <em class="inline-actions">
                <RouterLink
                  class="text-link"
                  :to="{ name: 'run-detail', params: { id: webui.applyJob.run_id } }"
                >
                  Details
                </RouterLink>
                <RouterLink
                  class="text-link"
                  :to="{ name: 'run-log', params: { id: webui.applyJob.run_id } }"
                >
                  Log
                </RouterLink>
              </em>
            </div>
          </div>

          <section
            class="apply-job-impact"
            aria-labelledby="apply-job-modal-impact-title"
          >
            <div class="apply-job-impact-heading">
              <strong id="apply-job-modal-impact-title">Services and images</strong>
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

        <section class="apply-job-live-log" aria-labelledby="apply-job-modal-log-title">
          <div class="apply-job-impact-heading">
            <strong id="apply-job-modal-log-title">Live log</strong>
            <span class="apply-job-log-path">{{ applyJobLogTitle }}</span>
          </div>
          <n-alert
            v-if="webui.applyJobLog?.truncated"
            class="preflight-block"
            type="warning"
            :show-icon="false"
          >
            Showing the last {{ webui.applyJobLog.max_bytes }} bytes.
          </n-alert>
          <n-alert
            v-if="webui.applyJobLog?.error"
            class="preflight-block"
            type="warning"
            :show-icon="false"
          >
            Live log unavailable: {{ webui.applyJobLog.error }}
          </n-alert>
          <div v-if="applyJobLogWaiting" class="empty-state">
            {{ applyJobLogEmptyMessage }}
          </div>
          <pre
            v-else-if="!webui.applyJobLog?.error"
            ref="applyJobModalLogRef"
            class="log-viewer apply-job-log-viewer"
          >{{ applyJobLogText }}</pre>
        </section>

        <n-alert
          v-if="webui.applyJob.error"
          class="preflight-block"
          type="error"
        >
          {{ webui.applyJob.error }}
        </n-alert>

        <div class="preflight-footer">
          <n-button size="small" quaternary @click="closeApplyJobModal">
            {{ applyJobActive ? "View on page" : "Close" }}
          </n-button>
        </div>
      </section>
    </n-modal>
  </section>
</template>

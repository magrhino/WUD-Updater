import { computed } from "vue";

import type {
  PendingItem,
  PendingResponse,
  ReleaseNoteInfo,
} from "../../api/client";
import type { ReleaseChangelogState } from "../../utils/releaseChangelog";
import { useRunsStore } from "../../stores/runs";
import { useSettingsStore } from "../../stores/settings";
import { useUpdatesStore } from "../../stores/updates";
import { pendingSourceFileName, uniqueSorted } from "./pendingDisplay";
import {
  safetyCues as buildSafetyCues,
  type SafetyCue,
} from "./safetyCues";
import {
  activeSnoozedServiceKeys as buildActiveSnoozedServiceKeys,
  matchingSnoozedServiceKeys,
  pendingServiceKeysForGroups,
  selectableLineNumbersForGroups,
  snoozedItemsForGroups,
  stackGroupsWithoutSnoozedItems,
} from "./snoozeSelection";
import { pluralize } from "./utils";

function pendingHeadingTextFor(
  pending: PendingResponse | null,
  pendingLoadFailed: boolean,
): string {
  if (pending) {
    return pluralize(pending.count, "pending update");
  }
  if (pendingLoadFailed) {
    return "Pending updates unavailable";
  }
  return "Loading pending updates";
}

function pendingSourceDisplayFor(label: string): string {
  if (label === "Pending file") {
    return "Pending file";
  }
  return `Source ${label}`;
}

export function usePendingQueueState() {
  const updates = useUpdatesStore();
  const runs = useRunsStore();
  const settings = useSettingsStore();

  const allLineNumbers = computed(() =>
    uniqueSorted(updates.pending?.items.map((item) => item.line_no) ?? []),
  );
  const groupingReady = computed(
    () => updates.pending?.grouping.status === "ready",
  );
  const rawStackGroups = computed(() =>
    groupingReady.value ? (updates.pending?.grouping.groups ?? []) : [],
  );
  const pendingServiceKeys = computed(() =>
    pendingServiceKeysForGroups(rawStackGroups.value),
  );
  const activeSnoozedServiceKeys = computed(() =>
    buildActiveSnoozedServiceKeys(settings.snoozes),
  );
  const bulkSnoozedServiceKeys = computed(() =>
    matchingSnoozedServiceKeys(
      activeSnoozedServiceKeys.value,
      pendingServiceKeys.value,
    ),
  );
  const snoozedItems = computed(() =>
    snoozedItemsForGroups(rawStackGroups.value, bulkSnoozedServiceKeys.value),
  );
  const stackGroups = computed(() =>
    stackGroupsWithoutSnoozedItems(
      rawStackGroups.value,
      bulkSnoozedServiceKeys.value,
    ),
  );
  const unmatchedItems = computed(() =>
    groupingReady.value ? (updates.pending?.grouping.unmatched ?? []) : [],
  );
  const stackLineNumbers = computed(() =>
    selectableLineNumbersForGroups(stackGroups.value),
  );
  const pendingLoaded = computed(() => updates.pending !== null);
  const pendingLoadFailed = computed(
    () =>
      !pendingLoaded.value &&
      !updates.loading &&
      Boolean(updates.error || runs.error),
  );
  const pendingLoading = computed(
    () => !pendingLoaded.value && !pendingLoadFailed.value,
  );
  const pendingHeadingText = computed(() =>
    pendingHeadingTextFor(updates.pending, pendingLoadFailed.value),
  );
  const selectableLineNumbers = computed(() => {
    if (groupingReady.value) {
      return stackLineNumbers.value;
    }
    if (activeSnoozedServiceKeys.value.size) {
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
  const pendingSourceFile = computed(
    () => updates.pending?.source_file ?? "Pending file",
  );
  const pendingSourceLabel = computed(() => {
    const source = updates.pending?.source;
    if (source && source.active !== "file") {
      return source.label || pendingSourceFileName(pendingSourceFile.value);
    }
    return pendingSourceFileName(pendingSourceFile.value);
  });
  const pendingSourceDisplay = computed(() =>
    pendingSourceDisplayFor(pendingSourceLabel.value),
  );
  const pendingSourceDegraded = computed(
    () => updates.pending?.source?.degraded ?? false,
  );
  const pendingSourceWarning = computed(
    () =>
      updates.pending?.source?.fallback_reason ||
      updates.pending?.source?.detail ||
      "",
  );

  function releaseNoteFor(item: PendingItem): ReleaseNoteInfo | null {
    return releaseNotesByLine.value.get(item.line_no) ?? null;
  }

  function releaseChangelogFor(
    note: ReleaseNoteInfo | null,
  ): ReleaseChangelogState | null {
    return updates.releaseChangelogStateFor(note);
  }

  function riskCues(row: PendingItem): SafetyCue[] {
    return buildSafetyCues(row, {
      pending: updates.pending,
      releaseNote: releaseNoteFor(row),
      releaseNotesLoaded: Boolean(updates.releaseNotes),
      releaseNotesLoading: updates.releaseNotesLoading,
      servicePolicies: settings.servicePolicies,
      snoozes: settings.snoozes,
    });
  }

  return {
    allLineNumbers,
    activeSnoozedServiceKeys,
    bulkSnoozedServiceKeys,
    groupingReady,
    latestRun,
    pendingHeadingText,
    pendingLoaded,
    pendingLoadFailed,
    pendingLoading,
    pendingServiceKeys,
    pendingSourceDisplay,
    pendingSourceDegraded,
    pendingSourceFile,
    pendingSourceLabel,
    pendingSourceWarning,
    rawStackGroups,
    releaseChangelogFor,
    releaseNoteFor,
    releaseNotesByLine,
    riskCues,
    selectableLineNumbers,
    selectAllLabel,
    snoozedItems,
    stackGroups,
    stackLineNumbers,
    unmatchedItems,
  };
}

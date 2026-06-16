import { computed } from "vue";

import type {
  PendingGroupedItem,
  PendingItem,
  PendingStackGroup,
  ReleaseNoteInfo,
} from "../../api/client";
import { useRunsStore } from "../../stores/runs";
import { useSettingsStore } from "../../stores/settings";
import { useUpdatesStore } from "../../stores/updates";
import {
  groupedItemServiceKeys,
  pendingSourceFileName,
  uniqueSorted,
  uniqueStrings,
} from "./pendingDisplay";
import {
  safetyCues as buildSafetyCues,
  type SafetyCue,
} from "./safetyCues";
import { pluralize } from "./utils";

export type DependencySnoozedPendingItem = {
  group: PendingStackGroup;
  item: PendingGroupedItem;
};

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
        .filter((snooze) => pending.has(snooze.service_key))
        .map((snooze) => snooze.service_key),
    );
  });
  const dependencySnoozedItems = computed<DependencySnoozedPendingItem[]>(() => {
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
          services_label: services.length
            ? services.join(", ")
            : group.services_label,
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
    () =>
      !pendingLoaded.value &&
      !updates.loading &&
      Boolean(updates.error || runs.error),
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
  const pendingSourceFile = computed(
    () => updates.pending?.source_file ?? "Pending file",
  );
  const pendingSourceLabel = computed(() =>
    pendingSourceFileName(pendingSourceFile.value),
  );
  const pendingSourceDisplay = computed(() =>
    pendingSourceLabel.value !== "Pending file"
      ? `Source ${pendingSourceLabel.value}`
      : "Pending file",
  );

  function releaseNoteFor(item: PendingItem): ReleaseNoteInfo | null {
    return releaseNotesByLine.value.get(item.line_no) ?? null;
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
    activeDependencySnoozes,
    allLineNumbers,
    dependencyBlockedServiceKeys,
    dependencySnoozedItems,
    groupingReady,
    latestRun,
    pendingHeadingText,
    pendingLoaded,
    pendingLoadFailed,
    pendingLoading,
    pendingServiceKeys,
    pendingSourceDisplay,
    pendingSourceFile,
    pendingSourceLabel,
    rawStackGroups,
    releaseNoteFor,
    releaseNotesByLine,
    riskCues,
    selectableLineNumbers,
    selectAllLabel,
    stackGroups,
    stackLineNumbers,
    unmatchedItems,
  };
}

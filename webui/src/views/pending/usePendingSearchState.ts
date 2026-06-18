import { computed, ref, type ComputedRef } from "vue";

import type {
  PendingGroupedItem,
  PendingItem,
  PendingStackGroup,
  ReleaseNoteInfo,
} from "../../api/client";
import type { SafetyCue } from "./safetyCues";
import type { SnoozedPendingItem } from "./snoozeSelection";
import {
  filterPendingItems,
  filterPendingStackGroups,
  filterSnoozedItems,
  normalizePendingSearch,
} from "./pendingFilter";
import { pluralize } from "./utils";

type UsePendingSearchStateOptions = {
  pendingItems: ComputedRef<PendingItem[]>;
  groupingReady: ComputedRef<boolean>;
  snoozedItems: ComputedRef<SnoozedPendingItem[]>;
  selectableLineNumbers: ComputedRef<number[]>;
  selectAllLabel: ComputedRef<string>;
  stackGroups: ComputedRef<PendingStackGroup[]>;
  unmatchedItems: ComputedRef<PendingGroupedItem[]>;
  releaseNoteFor: (item: PendingItem) => ReleaseNoteInfo | null;
  releaseNoteReason: (note: ReleaseNoteInfo | null) => string;
  releaseNoteStatus: (note: ReleaseNoteInfo | null) => string;
  riskCues: (item: PendingItem) => SafetyCue[];
};

export function usePendingSearchState(options: UsePendingSearchStateOptions) {
  const pendingSearchQuery = ref("");
  const pendingSearchText = computed(() =>
    normalizePendingSearch(pendingSearchQuery.value),
  );
  const pendingSearchActive = computed(() => Boolean(pendingSearchText.value));
  const pendingSearchContext = {
    releaseNoteFor: options.releaseNoteFor,
    releaseNoteReason: options.releaseNoteReason,
    releaseNoteStatus: options.releaseNoteStatus,
    riskCues: options.riskCues,
  };

  const filteredStackGroups = computed(() =>
    filterPendingStackGroups(
      options.stackGroups.value,
      pendingSearchText.value,
      pendingSearchContext,
    ),
  );
  const filteredUnmatchedItems = computed(() =>
    filterPendingItems(
      options.unmatchedItems.value,
      pendingSearchText.value,
      pendingSearchContext,
    ),
  );
  const filteredSnoozedItems = computed(() =>
    filterSnoozedItems(
      options.snoozedItems.value,
      pendingSearchText.value,
      pendingSearchContext,
    ),
  );
  const filteredPendingItems = computed(() =>
    filterPendingItems(
      options.pendingItems.value,
      pendingSearchText.value,
      pendingSearchContext,
    ),
  );
  const visibleLineNumbers = computed(() => {
    if (options.groupingReady.value) {
      return [
        ...filteredStackGroups.value.flatMap((group) => group.visibleLineNumbers),
        ...filteredSnoozedItems.value.map(({ item }) => item.line_no),
        ...filteredUnmatchedItems.value.map((item) => item.line_no),
      ];
    }
    return filteredPendingItems.value.map((item) => item.line_no);
  });
  const visibleSelectableLineNumbers = computed(() => {
    const visibleLines = new Set(visibleLineNumbers.value);
    return options.selectableLineNumbers.value.filter((lineNo) =>
      visibleLines.has(lineNo),
    );
  });
  const visibleSelectAllLabel = computed(() =>
    pendingSearchActive.value ? "Select visible updates" : options.selectAllLabel.value,
  );
  const pendingSearchEmpty = computed(
    () =>
      pendingSearchActive.value &&
      options.pendingItems.value.length > 0 &&
      visibleLineNumbers.value.length === 0,
  );
  const pendingSearchResultLabel = computed(() => {
    if (!pendingSearchActive.value) {
      return "";
    }
    return `${pluralize(visibleLineNumbers.value.length, "visible update")} matched`;
  });

  function clearPendingSearch(): void {
    pendingSearchQuery.value = "";
  }

  return {
    clearPendingSearch,
    filteredPendingItems,
    filteredSnoozedItems,
    filteredStackGroups,
    filteredUnmatchedItems,
    pendingSearchActive,
    pendingSearchEmpty,
    pendingSearchQuery,
    pendingSearchResultLabel,
    visibleLineNumbers,
    visibleSelectableLineNumbers,
    visibleSelectAllLabel,
  };
}

import { computed, type ComputedRef, type Ref } from "vue";

import type { PendingGroupedItem } from "../../api/client";
import { pluralize } from "./utils";

type UsePendingSearchResultStateOptions = {
  pendingSearchActive: ComputedRef<boolean>;
  visibleLineNumbers: ComputedRef<number[]>;
  selectedLineNumbers: Ref<number[]>;
  filteredUnmatchedItems: ComputedRef<PendingGroupedItem[]>;
  unmatchedItems: ComputedRef<PendingGroupedItem[]>;
  unmatchedIssueSummary: ComputedRef<string>;
  unmatchedReviewCountLabel: ComputedRef<string>;
  unmatchedReviewSummary: ComputedRef<string>;
};

export function usePendingSearchResultState(
  options: UsePendingSearchResultStateOptions,
) {
  const selectedHiddenCount = computed(() => {
    if (!options.pendingSearchActive.value) {
      return 0;
    }
    const visibleLines = new Set(options.visibleLineNumbers.value);
    return options.selectedLineNumbers.value.filter(
      (lineNo) => !visibleLines.has(lineNo),
    ).length;
  });
  const visibleUnmatchedReviewSummary = computed(() => {
    if (!options.pendingSearchActive.value) {
      return options.unmatchedReviewSummary.value;
    }
    const count = options.filteredUnmatchedItems.value.length;
    const verb = count === 1 ? "needs" : "need";
    return `${pluralize(count, "pending line", "pending lines")} matched search and ${verb} review.`;
  });
  const visibleUnmatchedIssueSummary = computed(() =>
    options.pendingSearchActive.value &&
    options.filteredUnmatchedItems.value.length !== options.unmatchedItems.value.length
      ? ""
      : options.unmatchedIssueSummary.value,
  );
  const visibleUnmatchedReviewCountLabel = computed(() => {
    if (!options.pendingSearchActive.value) {
      return options.unmatchedItems.value.length
        ? options.unmatchedReviewCountLabel.value
        : "";
    }
    return options.filteredUnmatchedItems.value.length
      ? `${pluralize(options.filteredUnmatchedItems.value.length, "stale item")} visible`
      : "";
  });

  return {
    selectedHiddenCount,
    visibleUnmatchedIssueSummary,
    visibleUnmatchedReviewCountLabel,
    visibleUnmatchedReviewSummary,
  };
}

import {
  computed,
  ref,
  watch,
  type ComputedRef,
  type WritableComputedRef,
} from "vue";
import type { DataTableRowKey } from "naive-ui";

import type {
  PendingGroupedItem,
  PendingItem,
  PendingStackGroup,
  PlanSelectionRequest,
  TagOverrideRequest,
} from "../../api/client";
import { useUpdatesStore } from "../../stores/updates";
import { uniqueSorted } from "./pendingDisplay";

export type UsePendingSelectionStateOptions = {
  pendingItems: ComputedRef<PendingItem[]>;
  selectableLineNumbers: ComputedRef<number[]>;
  selectableSelections?: ComputedRef<PlanSelectionRequest[]>;
  availableSelections?: ComputedRef<PlanSelectionRequest[]>;
  onSelectionChanged?: () => void;
};

const tagValuePattern = /^\w[\w.-]{0,127}$/;

function tagOverrideKey(item: PendingItem): string {
  return JSON.stringify([item.raw, item.image, item.repo, item.desired_tag]);
}

export function pendingSelectionKey(
  selection: PlanSelectionRequest,
): string {
  return selection.selection_id || `line:${selection.line_no}`;
}

export function pendingSelectionForItem(
  item: PendingGroupedItem,
): PlanSelectionRequest {
  return {
    line_no: item.line_no,
    selection_id: item.selection_id ?? "",
  };
}

export function pendingSelectionsForGroup(
  group: PendingStackGroup,
): PlanSelectionRequest[] {
  return group.items.map(pendingSelectionForItem);
}

function lineSelection(lineNo: number): PlanSelectionRequest {
  return { line_no: lineNo, selection_id: "" };
}

function uniqueSelections(
  selections: PlanSelectionRequest[],
): PlanSelectionRequest[] {
  const unique = new Map<string, PlanSelectionRequest>();
  for (const selection of selections) {
    unique.set(pendingSelectionKey(selection), selection);
  }
  return [...unique.values()].sort(
    (left, right) =>
      left.line_no - right.line_no ||
      left.selection_id.localeCompare(right.selection_id),
  );
}

export function usePendingSelectionState(
  options: UsePendingSelectionStateOptions,
) {
  const updates = useUpdatesStore();
  const selectedSelections = ref<PlanSelectionRequest[]>([]);
  const selectedLineNumbers: WritableComputedRef<number[]> = computed({
    get: () =>
      uniqueSorted(
        selectedSelections.value.map((selection) => selection.line_no),
      ),
    set: (lineNumbers) => {
      selectedSelections.value = uniqueSorted(lineNumbers).map(lineSelection);
    },
  });
  const tagOverrides = ref<Record<number, string>>({});
  const tagOverrideKeys = ref<Record<number, string>>({});
  const selectedLineSet = computed(() => new Set(selectedLineNumbers.value));
  const selectedSelectionKeySet = computed(
    () =>
      new Set(
        selectedSelections.value.map((selection) =>
          pendingSelectionKey(selection),
        ),
      ),
  );

  function tagOverrideValue(item: PendingItem): string {
    return tagOverrides.value[item.line_no] ?? item.desired_tag;
  }

  function pendingItemsForLines(lineNumbers: number[]): PendingItem[] {
    const lineSet = new Set(lineNumbers);
    return options.pendingItems.value.filter((item) => lineSet.has(item.line_no));
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
      .filter(
        (item) =>
          item.desired_tag &&
          tagOverrideKeys.value[item.line_no] === tagOverrideKey(item) &&
          tagOverrideValue(item).trim() !== item.desired_tag,
      )
      .map((item) => ({
        line_no: item.line_no,
        tag: tagOverrideValue(item).trim(),
      }));
  }

  function lineNumbersHaveTagUpdates(lineNumbers: number[]): boolean {
    return pendingItemsForLines(lineNumbers).some((item) =>
      Boolean(item.desired_tag),
    );
  }

  function markSelectionChanged(): void {
    options.onSelectionChanged?.();
  }

  function updateTagOverride(item: PendingItem, value: string): void {
    tagOverrides.value = {
      ...tagOverrides.value,
      [item.line_no]: value,
    };
    tagOverrideKeys.value = {
      ...tagOverrideKeys.value,
      [item.line_no]: tagOverrideKey(item),
    };
    const groupedItem = item as Partial<PendingGroupedItem>;
    const selection = groupedItem.selection_id
      ? {
          line_no: item.line_no,
          selection_id: groupedItem.selection_id,
        }
      : lineSelection(item.line_no);
    if (
      !selectedSelectionKeySet.value.has(pendingSelectionKey(selection))
    ) {
      selectedSelections.value = uniqueSelections([
        ...selectedSelections.value,
        selection,
      ]);
    }
    markSelectionChanged();
  }

  function updateCheckedRowKeys(keys: DataTableRowKey[]): void {
    selectedSelections.value = uniqueSorted(
      keys.map(Number).filter((key) => Number.isFinite(key)),
    ).map(lineSelection);
    markSelectionChanged();
  }

  function toggleSelection(
    selection: PlanSelectionRequest,
    checked: boolean,
  ): void {
    const key = pendingSelectionKey(selection);
    const selected = new Map(
      selectedSelections.value.map((item) => [pendingSelectionKey(item), item]),
    );
    if (checked) {
      selected.set(key, selection);
    } else {
      selected.delete(key);
    }
    selectedSelections.value = uniqueSelections([...selected.values()]);
    markSelectionChanged();
  }

  function toggleLine(lineNo: number, checked: boolean): void {
    toggleSelection(lineSelection(lineNo), checked);
  }

  function toggleGroupedItem(
    item: PendingGroupedItem,
    checked: boolean,
  ): void {
    toggleSelection(pendingSelectionForItem(item), checked);
  }

  function selectAllVisible(): void {
    selectedSelections.value = uniqueSelections(
      options.selectableSelections?.value ??
        options.selectableLineNumbers.value.map(lineSelection),
    );
    markSelectionChanged();
  }

  function clearSelection(): void {
    selectedSelections.value = [];
    markSelectionChanged();
  }

  function stackSelected(group: PendingStackGroup): boolean {
    const selections = pendingSelectionsForGroup(group);
    return (
      selections.length > 0 &&
      selections.every((selection) =>
        selectedSelectionKeySet.value.has(pendingSelectionKey(selection)),
      )
    );
  }

  function stackIndeterminate(group: PendingStackGroup): boolean {
    return (
      pendingSelectionsForGroup(group).some((selection) =>
        selectedSelectionKeySet.value.has(pendingSelectionKey(selection)),
      ) &&
      !stackSelected(group)
    );
  }

  function stackHasSelection(group: PendingStackGroup): boolean {
    return pendingSelectionsForGroup(group).some((selection) =>
      selectedSelectionKeySet.value.has(pendingSelectionKey(selection)),
    );
  }

  function toggleStack(group: PendingStackGroup, checked: boolean): void {
    const selected = new Map(
      selectedSelections.value.map((item) => [pendingSelectionKey(item), item]),
    );
    for (const selection of pendingSelectionsForGroup(group)) {
      const key = pendingSelectionKey(selection);
      if (checked) {
        selected.set(key, selection);
      } else {
        selected.delete(key);
      }
    }
    selectedSelections.value = uniqueSelections([...selected.values()]);
    markSelectionChanged();
  }

  function updateDisabled(lineNumbers: number[]): boolean {
    return (
      lineNumbers.length === 0 ||
      updates.loading ||
      Boolean(tagOverrideErrorForLines(lineNumbers))
    );
  }

  watch(
    [
      () => options.pendingItems.value,
      () => options.availableSelections?.value,
    ],
    ([items, availableSelections]) => {
      const next: Record<number, string> = {};
      const nextKeys: Record<number, string> = {};
      const pendingLineNumbers = new Set<number>();
      for (const item of items) {
        pendingLineNumbers.add(item.line_no);
        const key = tagOverrideKey(item);
        if (
          item.desired_tag &&
          tagOverrideKeys.value[item.line_no] === key &&
          tagOverrides.value[item.line_no] !== undefined
        ) {
          next[item.line_no] = tagOverrides.value[item.line_no];
          nextKeys[item.line_no] = key;
        }
      }
      tagOverrides.value = next;
      tagOverrideKeys.value = nextKeys;
      const availableKeys = availableSelections
        ? new Set(availableSelections.map(pendingSelectionKey))
        : null;
      selectedSelections.value = uniqueSelections(
        selectedSelections.value.filter((selection) => {
          if (!pendingLineNumbers.has(selection.line_no)) {
            return false;
          }
          return (
            !availableKeys ||
            availableKeys.has(pendingSelectionKey(selection))
          );
        }),
      );
    },
    { immediate: true },
  );

  return {
    clearSelection,
    lineNumbersHaveTagUpdates,
    pendingItemsForLines,
    selectAllVisible,
    selectedLineNumbers,
    selectedLineSet,
    selectedSelections,
    selectedSelectionKeySet,
    stackHasSelection,
    stackIndeterminate,
    stackSelected,
    tagOverrideErrorForLines,
    tagOverrideValue,
    tagOverrides,
    tagOverridesForLines,
    toggleLine,
    toggleGroupedItem,
    toggleSelection,
    toggleStack,
    updateCheckedRowKeys,
    updateDisabled,
    updateTagOverride,
  };
}

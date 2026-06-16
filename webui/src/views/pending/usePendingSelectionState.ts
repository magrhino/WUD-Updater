import { computed, ref, watch, type ComputedRef } from "vue";
import type { DataTableRowKey } from "naive-ui";

import type {
  PendingItem,
  PendingStackGroup,
  TagOverrideRequest,
} from "../../api/client";
import { useUpdatesStore } from "../../stores/updates";
import { uniqueSorted } from "./pendingDisplay";

export type UsePendingSelectionStateOptions = {
  pendingItems: ComputedRef<PendingItem[]>;
  selectableLineNumbers: ComputedRef<number[]>;
  onSelectionChanged?: () => void;
};

const tagValuePattern = /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$/;

export function usePendingSelectionState(
  options: UsePendingSelectionStateOptions,
) {
  const updates = useUpdatesStore();
  const selectedLineNumbers = ref<number[]>([]);
  const tagOverrides = ref<Record<number, string>>({});
  const selectedLineSet = computed(() => new Set(selectedLineNumbers.value));

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
      .filter((item) => item.desired_tag)
      .map((item) => ({
        line_no: item.line_no,
        tag: tagOverrideValue(item).trim(),
      }))
      .filter((item) => {
        const original = options.pendingItems.value.find(
          (pendingItem) => pendingItem.line_no === item.line_no,
        );
        return original !== undefined && item.tag !== original.desired_tag;
      });
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
    if (!selectedLineSet.value.has(item.line_no)) {
      selectedLineNumbers.value = uniqueSorted([
        ...selectedLineNumbers.value,
        item.line_no,
      ]);
    }
    markSelectionChanged();
  }

  function updateCheckedRowKeys(keys: DataTableRowKey[]): void {
    selectedLineNumbers.value = uniqueSorted(
      keys.map((key) => Number(key)).filter((key) => Number.isFinite(key)),
    );
    markSelectionChanged();
  }

  function toggleLine(lineNo: number, checked: boolean): void {
    const selected = new Set(selectedLineNumbers.value);
    if (checked) {
      selected.add(lineNo);
    } else {
      selected.delete(lineNo);
    }
    selectedLineNumbers.value = uniqueSorted([...selected]);
    markSelectionChanged();
  }

  function selectAllVisible(): void {
    selectedLineNumbers.value = [...options.selectableLineNumbers.value];
    markSelectionChanged();
  }

  function clearSelection(): void {
    selectedLineNumbers.value = [];
    markSelectionChanged();
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
    () => options.pendingItems.value,
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
        selectedLineNumbers.value.filter((lineNo) =>
          pendingLineNumbers.has(lineNo),
        ),
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
    stackHasSelection,
    stackIndeterminate,
    stackSelected,
    tagOverrideErrorForLines,
    tagOverrideValue,
    tagOverrides,
    tagOverridesForLines,
    toggleLine,
    toggleStack,
    updateCheckedRowKeys,
    updateDisabled,
    updateTagOverride,
  };
}

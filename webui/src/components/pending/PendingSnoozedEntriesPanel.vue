<script setup lang="ts">
import { NTag } from "naive-ui";

import type {
  PendingGroupedItem,
  PendingItem,
  SecurityScanInfo,
} from "../../api/client";
import type { SnoozedPendingItem } from "../../views/pending/snoozeSelection";
import {
  groupedItemServices,
  type PendingTagInputProps,
} from "../../views/pending/pendingDisplay";
import type { SafetyCue } from "../../views/pending/safetyCues";
import { pluralize } from "../../views/pending/utils";
import PendingUpdateRow from "./PendingUpdateRow.vue";

defineProps<{
  riskCues: (item: PendingGroupedItem) => SafetyCue[];
  securityScanFor: (item: PendingGroupedItem) => SecurityScanInfo | null;
  selectedLineSet: Set<number>;
  snoozedItems: SnoozedPendingItem[];
  tagInputProps: (item: Pick<PendingItem, "image">) => PendingTagInputProps;
  tagOverrideValue: (item: PendingItem) => string;
}>();

const emit = defineEmits<{
  toggleLine: [lineNo: number, checked: boolean];
  updateTag: [item: PendingGroupedItem, value: string];
}>();
</script>

<template>
  <article v-if="snoozedItems.length" class="stack-card needs-review">
    <div class="stack-card-header">
      <div class="stack-title-block">
        <strong class="wrap-anywhere">Snoozed pending entries</strong>
        <span class="stack-path wrap-anywhere">
          Excluded from bulk selection while snoozed.
        </span>
      </div>
      <div class="stack-card-side">
        <div class="stack-card-tags">
          <n-tag size="small" type="default">
            {{ pluralize(snoozedItems.length, "item") }}
          </n-tag>
        </div>
      </div>
    </div>
    <details class="stack-details">
      <summary
        class="disclosure-summary disclosure-summary-triangle"
        aria-label="Details for snoozed updates"
      >
        Details
      </summary>
      <div class="stack-items">
        <PendingUpdateRow
          v-for="{ group, item } in snoozedItems"
          :key="`snoozed-${item.line_no}`"
          :item="item"
          :selected="selectedLineSet.has(item.line_no)"
          :group-name="group.name"
          :service-label="groupedItemServices(item)"
          status-label="Snoozed"
          status-tag-type="default"
          :risk-cues="riskCues(item)"
          :security-scan="securityScanFor(item)"
          :show-diagnostic="false"
          :show-release-notes="false"
          :tag-override-value="tagOverrideValue(item)"
          :show-tag-input="Boolean(item.desired_tag)"
          :tag-input-props="tagInputProps(item)"
          @toggle="(lineNo, checked) => emit('toggleLine', lineNo, checked)"
          @update-tag="emit('updateTag', item, $event)"
        />
      </div>
    </details>
  </article>
</template>

<style scoped>
.stack-card {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: var(--shadow-panel-lift);
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

.stack-path {
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

.stack-details {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.stack-details .disclosure-summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
  min-height: 32px;
  color: var(--color-action-blue);
  font-size: 0.86rem;
  font-weight: 700;
}

.stack-details[open] .disclosure-summary {
  margin-bottom: 4px;
}

.stack-items {
  display: grid;
  gap: 10px;
  min-width: 0;
}

@media (--wud-compact) {
  .stack-card-header {
    display: grid;
  }
}
</style>

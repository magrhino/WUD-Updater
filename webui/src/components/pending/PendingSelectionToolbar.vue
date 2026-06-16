<script setup lang="ts">
import { Check, Play, Trash2, X } from "@lucide/vue";
import { NButton, NFlex } from "naive-ui";

defineProps<{
  batchSummaryLabel: string;
  dependencySnoozedCount: number;
  groupingReady: boolean;
  hasSelectedTagUpdates: boolean;
  isMobile: boolean;
  loading: boolean;
  pendingLoaded: boolean;
  removalButtonLabel: string;
  removeSelectedDisabled: boolean;
  removeSelectedDisabledMessage: string;
  selectableCount: number;
  selectAllLabel: string;
  selectedCount: number;
  stackCount: number;
  unmatchedReviewCountLabel: string;
  updateSelectedDisabled: boolean;
}>();

const emit = defineEmits<{
  clearSelection: [];
  selectAll: [];
  startRemoval: [];
  startUpdate: [];
}>();
</script>

<template>
  <div v-if="pendingLoaded" class="selection-toolbar">
    <div class="selection-summary">
      <strong class="wrap-anywhere">{{ selectedCount }} selected</strong>
      <span v-if="groupingReady" class="wrap-anywhere">
        {{ stackCount === 1 ? "1 stack" : `${stackCount} stacks` }} available
        <template v-if="dependencySnoozedCount">
          - {{ dependencySnoozedCount === 1 ? "1 snoozed item" : `${dependencySnoozedCount} snoozed items` }}
        </template>
        <template v-if="unmatchedReviewCountLabel">
          - {{ unmatchedReviewCountLabel }}
        </template>
      </span>
      <span v-else class="wrap-anywhere">Pending file order</span>
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
        :disabled="!selectableCount"
        @click="emit('selectAll')"
      >
        <template #icon>
          <Check :size="16" />
        </template>
        {{ selectAllLabel }}
      </n-button>
    </n-flex>
  </div>

  <div v-if="pendingLoaded && selectedCount" class="batch-action-bar">
    <div class="selection-summary">
      <strong class="wrap-anywhere">{{ batchSummaryLabel }}</strong>
      <span class="wrap-anywhere">
        Preview the plan before anything changes.
        <template v-if="hasSelectedTagUpdates">
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
      <n-button size="small" quaternary @click="emit('clearSelection')">
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
        :loading="loading"
        @click="emit('startRemoval')"
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
        :loading="loading"
        @click="emit('startUpdate')"
      >
        <template #icon>
          <Play :size="16" />
        </template>
        Preview selected plan
      </n-button>
    </n-flex>
  </div>
</template>

<style scoped>
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

.selection-summary {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.selection-summary strong {
  font-size: 0.95rem;
}

.selection-summary span {
  color: var(--color-muted-text);
  font-size: 0.82rem;
}

@media (max-width: 920px) {
  .selection-toolbar,
  .batch-action-bar {
    align-items: flex-start;
  }
}

@media (max-width: 560px) {
  .selection-toolbar,
  .batch-action-bar {
    display: grid;
  }

  .pending-actions :deep(.n-button) {
    min-width: 44px;
    min-height: 44px;
  }

  .pending-actions :deep(.n-checkbox) {
    min-height: 44px;
    display: inline-flex;
    align-items: center;
  }

  .pending-actions {
    justify-content: flex-start;
  }
}
</style>

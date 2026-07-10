<script setup lang="ts">
import { NTag } from "naive-ui";

import type {
  PendingGroupedItem,
  PendingItem,
  PendingSnoozedCandidate,
  PendingStackGroup,
  ReleaseNoteInfo,
  SecurityScanInfo,
} from "../../api/client";
import type { SnoozedPendingItem } from "../../views/pending/snoozeSelection";
import type { PendingTagInputProps } from "../../views/pending/pendingDisplay";
import type { SafetyCue } from "../../views/pending/safetyCues";
import { pluralize } from "../../views/pending/utils";
import PendingEmptyQueueState from "./PendingEmptyQueueState.vue";
import PendingSnoozedEntriesPanel from "./PendingSnoozedEntriesPanel.vue";
import PendingStackCard from "./PendingStackCard.vue";
import PendingUpdateRow from "./PendingUpdateRow.vue";

defineProps<{
  latestRunId: number | null;
  loading: boolean;
  pendingSourceLabel: string;
  releaseNoteFor: (item: PendingGroupedItem) => ReleaseNoteInfo | null;
  releaseNoteReason: (note: ReleaseNoteInfo | null) => string;
  releaseNoteStatus: (note: ReleaseNoteInfo | null) => string;
  riskCues: (item: PendingGroupedItem) => SafetyCue[];
  securityScanFor: (item: PendingGroupedItem) => SecurityScanInfo | null;
  selectedLineSet: Set<number>;
  showSetupLink: boolean;
  snoozedCandidates: PendingSnoozedCandidate[];
  snoozedItems: SnoozedPendingItem[];
  stackGroups: PendingStackGroup[];
  stackHasSelection: (group: PendingStackGroup) => boolean;
  stackIndeterminate: (group: PendingStackGroup) => boolean;
  stackSelected: (group: PendingStackGroup) => boolean;
  staleDiagnosticDetail: (item: PendingGroupedItem) => string;
  staleDiagnosticLabel: (item: PendingGroupedItem) => string;
  tagInputProps: (item: Pick<PendingItem, "image">) => PendingTagInputProps;
  tagOverrideValue: (item: PendingItem) => string;
  unmatchedIssueSummary: string;
  unmatchedItems: PendingGroupedItem[];
  unmatchedReviewSummary: string;
  updateDisabled: (lineNumbers: number[]) => boolean;
}>();

const emit = defineEmits<{
  previewStack: [group: PendingStackGroup];
  toggleLine: [lineNo: number, checked: boolean];
  toggleStack: [group: PendingStackGroup, checked: boolean];
  updateTag: [item: PendingGroupedItem, value: string];
}>();
</script>

<template>
  <section class="stack-selection">
    <PendingStackCard
      v-for="group in stackGroups"
      :key="`${group.directory}/${group.compose_file}`"
      :group="group"
      :loading="loading"
      :release-note-for="releaseNoteFor"
      :release-note-reason="releaseNoteReason"
      :release-note-status="releaseNoteStatus"
      :risk-cues="riskCues"
      :security-scan-for="securityScanFor"
      :selected-line-set="selectedLineSet"
      :stack-has-selection="stackHasSelection(group)"
      :stack-indeterminate="stackIndeterminate(group)"
      :stack-selected="stackSelected(group)"
      :tag-input-props="tagInputProps"
      :tag-override-value="tagOverrideValue"
      :update-disabled="updateDisabled(group.line_numbers)"
      @preview-stack="emit('previewStack', $event)"
      @toggle-line="(lineNo, checked) => emit('toggleLine', lineNo, checked)"
      @toggle-stack="(stackGroup, checked) => emit('toggleStack', stackGroup, checked)"
      @update-tag="(item, value) => emit('updateTag', item, value)"
    />

    <PendingSnoozedEntriesPanel
      :risk-cues="riskCues"
      :security-scan-for="securityScanFor"
      :selected-line-set="selectedLineSet"
      :snoozed-candidates="snoozedCandidates"
      :snoozed-items="snoozedItems"
      :tag-input-props="tagInputProps"
      :tag-override-value="tagOverrideValue"
      @toggle-line="(lineNo, checked) => emit('toggleLine', lineNo, checked)"
      @update-tag="(item, value) => emit('updateTag', item, value)"
    />

    <article v-if="unmatchedItems.length" class="stack-card needs-review">
      <div class="stack-card-header">
        <div class="stack-title-block">
          <strong class="wrap-anywhere">Stale pending entries</strong>
          <span class="stack-path wrap-anywhere">{{ unmatchedReviewSummary }}</span>
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
        <summary
          class="disclosure-summary disclosure-summary-triangle"
          aria-label="Details for unmatched updates"
        >
          Details
        </summary>
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
            :security-scan="securityScanFor(item)"
            :meta-detail="staleDiagnosticDetail(item)"
            :show-diagnostic="Boolean(item.diagnostic)"
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

    <PendingEmptyQueueState
      v-if="
        !stackGroups.length &&
        !snoozedCandidates.length &&
        !snoozedItems.length &&
        !unmatchedItems.length
      "
      :latest-run-id="latestRunId"
      :pending-source-label="pendingSourceLabel"
      :show-setup-link="showSetupLink"
    />
  </section>
</template>

<style scoped>
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
  font-size: var(--text-metadata-size);
  font-weight: 700;
}

.stack-details[open] .disclosure-summary {
  margin-bottom: 8px;
}

.stack-items {
  display: grid;
  border-top: 1px solid var(--color-border-subtle);
}

@media (--wud-app-shell) {
  .stack-card-header {
    align-items: flex-start;
  }
}

@media (--wud-compact) {
  .stack-card-header {
    display: grid;
  }

  .stack-details .disclosure-summary {
    min-height: var(--size-touch-target);
  }

  .stack-card-tags {
    justify-content: flex-start;
  }

  .stack-card-side {
    justify-items: start;
    justify-content: flex-start;
  }
}
</style>

<script setup lang="ts">
import { Play } from "@lucide/vue";
import { NButton, NCheckbox, NTag } from "naive-ui";

import type {
  PendingGroupedItem,
  PendingItem,
  PendingStackGroup,
  ReleaseNoteInfo,
  SecurityScanInfo,
} from "../../api/client";
import { displayDigest } from "../../utils/digestProvenance";
import {
  groupChangeOverflowCount,
  groupChangePreviewItems,
  groupedItemActionLabel,
  groupedItemActionTagType,
  groupedItemServices,
  groupedItemTagRewriteLabel,
  groupedItemTarget,
  groupTagChangeCount,
  itemsBreakingCount,
  type PendingTagInputProps,
  previewImageLabel,
} from "../../views/pending/pendingDisplay";
import type { SafetyCue } from "../../views/pending/safetyCues";
import { pluralize } from "../../views/pending/utils";
import PendingUpdateRow from "./PendingUpdateRow.vue";

const props = defineProps<{
  group: PendingStackGroup;
  loading: boolean;
  releaseNoteFor: (item: PendingGroupedItem) => ReleaseNoteInfo | null;
  releaseNoteReason: (note: ReleaseNoteInfo | null) => string;
  releaseNoteStatus: (note: ReleaseNoteInfo | null) => string;
  riskCues: (item: PendingGroupedItem) => SafetyCue[];
  securityScanFor: (item: PendingGroupedItem) => SecurityScanInfo | null;
  selectedLineSet: Set<number>;
  stackHasSelection: boolean;
  stackIndeterminate: boolean;
  stackSelected: boolean;
  tagInputProps: (item: Pick<PendingItem, "image">) => PendingTagInputProps;
  tagOverrideValue: (item: PendingItem) => string;
  updateDisabled: boolean;
}>();

const emit = defineEmits<{
  previewStack: [group: PendingStackGroup];
  toggleLine: [lineNo: number, checked: boolean];
  toggleStack: [group: PendingStackGroup, checked: boolean];
  updateTag: [item: PendingGroupedItem, value: string];
}>();
</script>

<template>
  <article
    class="stack-card"
    :class="{ selected: stackHasSelection }"
  >
    <div class="stack-card-header">
      <div class="stack-title-block">
        <n-checkbox
          :checked="stackSelected"
          :indeterminate="stackIndeterminate"
          :aria-label="`Select stack ${group.name}`"
          @update:checked="emit('toggleStack', group, Boolean($event))"
        >
          <span class="stack-checkbox-label">
            <span class="sr-only">Select stack </span>
            <span class="stack-checkbox-kicker" aria-hidden="true">Stack</span>
            <strong class="wrap-anywhere" :title="group.directory">{{ group.name }}</strong>
          </span>
        </n-checkbox>
        <div class="stack-identity" aria-label="Stack impact">
          <span class="wrap-anywhere">
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
          <n-tag
            v-if="itemsBreakingCount(group.items, releaseNoteFor)"
            size="small"
            type="warning"
          >
            {{ pluralize(itemsBreakingCount(group.items, releaseNoteFor), "breaking cue") }}
          </n-tag>
        </div>
        <div class="stack-card-actions">
          <n-button
            size="small"
            secondary
            :disabled="updateDisabled"
            :loading="loading"
            @click="emit('previewStack', group)"
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
        <strong class="stack-change-service wrap-anywhere">{{ groupedItemServices(item) }}</strong>
        <span class="stack-change-target wrap-anywhere">
          <n-tag
            size="small"
            :type="groupedItemActionTagType(item)"
          >
            {{ groupedItemActionLabel(item) }}
          </n-tag>
          <span
            v-if="riskCues(item).length"
            class="risk-badges-container stack-change-risk-cues"
            aria-label="Safety cues"
          >
            <n-tag
              v-for="cue in riskCues(item)"
              :key="`${item.line_no}-${cue.key}`"
              size="small"
              :type="cue.type"
              class="safety-badge"
            >
              {{ cue.label }}
            </n-tag>
          </span>
          <code
            class="stack-change-value wrap-anywhere"
            data-label="Current"
            :title="item.image"
          >
            {{ previewImageLabel(item.image, displayDigest) }}
          </code>
          <span aria-hidden="true">-&gt;</span>
          <code
            class="stack-change-value wrap-anywhere"
            data-label="Target"
            :title="groupedItemTarget(item)"
          >
            {{ previewImageLabel(groupedItemTarget(item), displayDigest) }}
          </code>
        </span>
      </div>
      <span v-if="groupChangeOverflowCount(group)" class="stack-change-more wrap-anywhere">
        +{{ groupChangeOverflowCount(group) }} more in Details
      </span>
    </div>

    <details class="stack-details">
      <summary
        class="disclosure-summary disclosure-summary-triangle"
        :aria-label="`Details for ${group.name}`"
      >
        Details
      </summary>
      <div class="stack-items">
        <PendingUpdateRow
          v-for="item in group.items"
          :key="`${group.name}-${item.line_no}`"
          :item="item"
          :selected="selectedLineSet.has(item.line_no)"
          :service-label="groupedItemServices(item)"
          :status-label="groupedItemActionLabel(item)"
          :status-tag-type="groupedItemActionTagType(item)"
          :risk-cues="riskCues(item)"
          :tag-rewrite-label="groupedItemTagRewriteLabel(item)"
          :release-note="releaseNoteFor(item)"
          :release-note-status="releaseNoteStatus(releaseNoteFor(item))"
          :release-note-reason="releaseNoteReason(releaseNoteFor(item))"
          :security-scan="securityScanFor(item)"
          show-release-notes
          :show-diagnostic="Boolean(item.diagnostic)"
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

.stack-card.selected {
  border-color: var(--color-border-hover);
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

.stack-title-block :deep(.n-checkbox__label) {
  padding-inline: 6px 0;
}

.stack-checkbox-label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  box-sizing: border-box;
  min-height: 30px;
  padding: 5px 10px;
  border: 1px solid color-mix(in srgb,
      var(--color-border-hover) 42%,
      var(--color-border-subtle));
  border-radius: 7px;
  background: color-mix(in srgb,
      var(--color-surface) 94%,
      var(--color-action-blue) 6%);
  color: var(--color-text-secondary);
  font-size: var(--text-metadata-size);
  line-height: 1.35;
  transition:
    border-color var(--motion-base) var(--ease-out-quart),
    background-color var(--motion-base) var(--ease-out-quart);
}

.stack-title-block :deep(.n-checkbox:hover) .stack-checkbox-label {
  border-color: var(--color-border-hover);
  background: color-mix(in srgb,
      var(--color-surface) 90%,
      var(--color-action-blue) 10%);
}

.stack-checkbox-label strong {
  color: var(--color-ink);
}

.stack-checkbox-kicker {
  color: var(--color-muted-text);
  font-size: var(--text-label-size);
  font-weight: 700;
  line-height: 1.2;
}

.stack-identity {
  display: grid;
  gap: 3px;
  color: var(--color-text-secondary);
  font-size: 0.84rem;
  line-height: 1.35;
}

.identity-label {
  margin-right: 6px;
  color: var(--color-muted-text);
  font-weight: 700;
}

.stack-change-preview {
  display: grid;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--color-border-subtle);
}

.stack-change-row {
  display: grid;
  grid-template-columns: minmax(120px, 0.32fr) minmax(0, 1fr);
  gap: 10px;
  min-width: 0;
  color: var(--color-text-secondary);
  font-size: 0.84rem;
  line-height: 1.4;
}

.stack-change-service {
  color: var(--color-ink);
}

.stack-change-target {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px 7px;
}

.stack-change-target code {
  color: var(--color-code-text);
  font-family: var(--font-mono);
  font-size: 0.82rem;
}

.stack-change-more {
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

.stack-card-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
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

.stack-change-risk-cues {
  display: inline-flex;
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

  .stack-card-actions :deep(.n-button) {
    min-width: var(--size-touch-target);
    min-height: var(--size-touch-target);
  }

  .stack-details .disclosure-summary {
    min-height: var(--size-touch-target);
  }

  .stack-title-block :deep(.n-checkbox) {
    min-height: var(--size-touch-target);
    display: inline-flex;
    align-items: center;
  }

  .stack-card-tags {
    justify-content: flex-start;
  }

  .stack-change-row {
    grid-template-columns: 1fr;
    gap: 4px;
  }

  .stack-change-target {
    display: grid;
    align-items: start;
    gap: 5px;
  }

  .stack-change-target > :deep(.n-tag) {
    width: fit-content;
  }

  .stack-change-target > span[aria-hidden="true"] {
    display: none;
  }

  .stack-change-target code {
    display: block;
  }

  .stack-change-value::before {
    content: attr(data-label);
    display: block;
    margin-bottom: 1px;
    color: var(--color-muted-text);
    font-family: var(--font-sans);
    font-size: var(--text-label-size);
    font-weight: 700;
    line-height: 1.2;
  }

  .stack-card-side,
  .stack-card-actions {
    justify-items: start;
    justify-content: flex-start;
  }
}
</style>

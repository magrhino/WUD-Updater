<script setup lang="ts">
import type { InputHTMLAttributes } from "vue";
import { NAlert, NCheckbox, NInput, NTag } from "naive-ui";

import type {
  PendingGroupedItem,
  ReleaseNoteInfo,
  SecurityScanInfo,
} from "../../api/client";
import PendingReleaseNotes from "./PendingReleaseNotes.vue";
import PendingSecurityScanDetails from "./PendingSecurityScanDetails.vue";

type TagType = "default" | "error" | "info" | "success" | "warning";

type RiskCue = {
  key: string;
  label: string;
  type: TagType;
};

withDefaults(defineProps<{
  item: PendingGroupedItem;
  selected: boolean;
  serviceLabel: string;
  statusLabel: string;
  statusTagType: TagType;
  groupName?: string;
  riskCues?: RiskCue[];
  tagRewriteLabel?: string;
  releaseNote?: ReleaseNoteInfo | null;
  releaseNoteStatus?: string;
  releaseNoteReason?: string;
  securityScan?: SecurityScanInfo | null;
  showReleaseNotes?: boolean;
  showDiagnostic?: boolean;
  metaDetail?: string;
  tagOverrideValue?: string;
  showTagInput?: boolean;
  tagInputProps?: InputHTMLAttributes;
}>(), {
  groupName: "",
  riskCues: () => [],
  tagRewriteLabel: "",
  releaseNote: null,
  releaseNoteStatus: "",
  releaseNoteReason: "",
  securityScan: null,
  showReleaseNotes: false,
  showDiagnostic: false,
  metaDetail: "",
  tagOverrideValue: "",
  showTagInput: false,
  tagInputProps: () => ({}),
});

const emit = defineEmits<{
  toggle: [lineNo: number, checked: boolean];
  updateTag: [value: string];
}>();

function groupedItemTarget(item: PendingGroupedItem): string {
  return item.target_image || item.resolved_image || item.image;
}
</script>

<template>
  <div class="pending-update-row" :class="{ selected }">
    <div class="pending-update-main">
      <n-checkbox
        :checked="selected"
        :aria-label="`Select update ${item.image}`"
        @update:checked="emit('toggle', item.line_no, Boolean($event))"
      >
        <span class="sr-only">Select update</span>
        <strong class="wrap-anywhere">{{ groupName ? `${groupName} / ${serviceLabel}` : serviceLabel }}</strong>
      </n-checkbox>
      <n-tag size="small" :type="statusTagType">
        {{ statusLabel }}
      </n-tag>
    </div>
    <div class="pending-update-detail">
      <code class="wrap-anywhere">{{ item.image }}</code>
      <span>-></span>
      <code class="wrap-anywhere">{{ groupedItemTarget(item) }}</code>
    </div>
    <div class="pending-update-meta">
      <span class="wrap-anywhere">Pending file line #{{ item.line_no }}</span>
      <span
        v-if="riskCues.length"
        class="risk-badges-container wrap-anywhere"
        aria-label="Safety cues"
      >
        <n-tag
          v-for="cue in riskCues"
          :key="`${item.line_no}-${cue.key}`"
          size="small"
          :type="cue.type"
          class="safety-badge"
        >
          {{ cue.label }}
        </n-tag>
      </span>
      <span v-if="tagRewriteLabel" class="tag-rewrite-detail wrap-anywhere">
        <n-tag size="small" type="warning">Tag rewrite</n-tag>
        {{ tagRewriteLabel }}
      </span>
      <span v-if="item.tag_stream" class="tag-stream-detail wrap-anywhere">
        {{ item.tag_stream.current_stream }} -> {{ item.tag_stream.reported_stream }}
      </span>
      <span v-if="metaDetail" class="wrap-anywhere">{{ metaDetail }}</span>
      <PendingReleaseNotes
        v-if="showReleaseNotes"
        :release-note="releaseNote"
        :release-note-status="releaseNoteStatus"
        :release-note-reason="releaseNoteReason"
      />
    </div>
    <PendingSecurityScanDetails
      v-if="securityScan"
      :scan="securityScan"
    />
    <div v-if="showDiagnostic && item.diagnostic" class="pending-update-diagnostic">
      <n-alert type="warning" :title="item.diagnostic.message">
        {{ item.diagnostic.hint }}
      </n-alert>
    </div>
    <div v-if="showTagInput" class="pending-update-tag">
      <span>New tag</span>
      <n-input
        :value="tagOverrideValue"
        size="small"
        class="tag-override-input"
        :placeholder="item.desired_tag"
        :input-props="tagInputProps"
        @update:value="emit('updateTag', $event)"
      />
    </div>
  </div>
</template>

<style scoped>
.pending-update-row {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-border-subtle);
}

.pending-update-row:last-child {
  border-bottom: 0;
}

.pending-update-row.selected {
  padding-right: 10px;
  padding-left: 10px;
  border-radius: 7px;
  background: var(--color-panel-tint);
}

.pending-update-main {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.pending-update-detail,
.pending-update-meta,
.pending-update-tag {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 8px;
  min-width: 0;
}

.tag-stream-detail {
  color: var(--color-warning-fg);
}

.pending-update-detail {
  color: var(--color-code-text);
  font-family: var(--font-mono);
  font-size: 0.82rem;
}

.pending-update-meta,
.pending-update-tag {
  color: var(--color-muted-text);
  font-size: 0.82rem;
}

.pending-update-diagnostic {
  margin-top: 8px;
  width: 100%;
}

@media (--wud-compact) {
  .pending-update-main {
    display: grid;
  }

  .pending-update-tag .tag-override-input {
    min-height: var(--size-touch-target);
  }

  .pending-update-main :deep(.n-checkbox) {
    min-height: var(--size-touch-target);
    display: inline-flex;
    align-items: center;
  }
}
</style>

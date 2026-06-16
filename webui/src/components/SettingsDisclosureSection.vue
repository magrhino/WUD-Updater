<script setup lang="ts">
import type { Component } from "vue";
import { ChevronDown } from "@lucide/vue";
import { NEmpty, NFlex, NTag } from "naive-ui";

type TagType = "default" | "primary" | "success" | "info" | "warning" | "error";

export type SettingsDisclosureRow = {
  key: string;
  name: string;
  detail: string;
  value: string;
  valueKind: "code" | "text";
  valueClass?: string;
  tagLabel: string;
  tagType: TagType;
};

type HeaderTag = {
  label: string;
  type?: TagType;
};

const props = defineProps<{
  id: string;
  eyebrow: string;
  title: string;
  open: boolean;
  compact: boolean;
  "aria-label": string;
  headerTags: HeaderTag[];
  tableHeaders: string[];
  entries: SettingsDisclosureRow[];
  emptyDescription: string;
  icon?: Component;
}>();
</script>

<template>
  <details :id="props.id" class="section-panel settings-disclosure" :open="props.open">
    <summary class="section-heading settings-disclosure-summary">
      <div>
        <p class="eyebrow">{{ props.eyebrow }}</p>
        <h2>{{ props.title }}</h2>
      </div>
      <n-flex
        class="section-heading-meta"
        align="center"
        :justify="props.compact ? 'flex-start' : 'flex-end'"
        :size="8"
      >
        <n-tag
          v-for="tag in props.headerTags"
          :key="tag.label"
          size="small"
          :type="tag.type"
        >
          {{ tag.label }}
        </n-tag>
        <component
          :is="props.icon"
          v-if="props.icon"
          :size="20"
          class="section-heading-icon"
          aria-hidden="true"
        />
        <ChevronDown
          :size="18"
          class="settings-disclosure-chevron"
          aria-hidden="true"
        />
      </n-flex>
    </summary>
    <div
      v-if="props.entries.length"
      class="settings-list"
      role="table"
      :aria-label="props['aria-label']"
    >
      <div class="settings-table-head" role="row">
        <span role="columnheader">{{ props.tableHeaders[0] }}</span>
        <span role="columnheader">{{ props.tableHeaders[1] }}</span>
        <span role="columnheader">{{ props.tableHeaders[2] }}</span>
      </div>
      <div
        v-for="entry in props.entries"
        :key="entry.key"
        class="settings-row"
        role="row"
      >
        <div role="cell">
          <strong>{{ entry.name }}</strong>
          <span>{{ entry.detail }}</span>
        </div>
        <code v-if="entry.valueKind === 'code'" role="cell">
          {{ entry.value }}
        </code>
        <span v-else :class="entry.valueClass" role="cell">
          {{ entry.value }}
        </span>
        <n-tag size="small" :type="entry.tagType" role="cell">
          {{ entry.tagLabel }}
        </n-tag>
      </div>
    </div>
    <n-empty
      v-else
      class="empty-state"
      :description="props.emptyDescription"
      :show-icon="false"
    />
  </details>
</template>

<style scoped>
.settings-disclosure {
  display: block;
  scroll-margin-top: 18px;
}

.settings-disclosure-summary {
  list-style: none;
  cursor: pointer;
}

.settings-disclosure-summary::-webkit-details-marker {
  display: none;
}

.settings-disclosure-summary:focus-visible {
  outline: 2px solid var(--color-border-hover);
  outline-offset: 4px;
  border-radius: 7px;
}

.settings-disclosure-chevron {
  flex: 0 0 auto;
  color: var(--color-muted-text);
  transition: transform 180ms ease-out;
}

.settings-disclosure[open] .settings-disclosure-chevron {
  transform: rotate(180deg);
}

.settings-list {
  display: grid;
  margin-top: 14px;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
}

.settings-table-head {
  display: grid;
  grid-template-columns: minmax(160px, 0.8fr) minmax(0, 1.2fr) minmax(102px, auto);
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  color: var(--color-muted-text);
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
  background: var(--color-table-head);
}

.settings-row {
  display: grid;
  grid-template-columns: minmax(160px, 0.8fr) minmax(0, 1.2fr) minmax(102px, auto);
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 10px 12px;
  border-top: 1px solid var(--color-border-subtle);
}

.settings-row>div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.settings-row strong,
.settings-row span,
.settings-row code {
  min-width: 0;
  overflow-wrap: anywhere;
}

.settings-row span {
  color: var(--color-muted-text);
  font-size: 0.82rem;
}

.settings-row code {
  color: var(--color-code-text);
  font-family: var(--font-mono);
  font-size: 0.84rem;
  line-height: 1.45;
}

.settings-row>:deep(.n-tag) {
  justify-self: start;
}

.settings-redacted-value {
  color: var(--color-text-secondary);
  font-weight: 700;
}

@media (max-width: 560px) {
  .settings-row {
    grid-template-columns: 1fr;
    align-items: start;
    gap: 7px;
  }

  .settings-table-head {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  .settings-row>:deep(.n-tag) {
    width: fit-content;
  }
}
</style>

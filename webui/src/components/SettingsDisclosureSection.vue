<script setup lang="ts">
import type { Component } from "vue";
import { ChevronDown } from "@lucide/vue";
import { NEmpty, NFlex, NTag } from "naive-ui";

import type { SettingsDisclosureRow } from "./SettingsDisclosureSection.types";

type TagType = "default" | "primary" | "success" | "info" | "warning" | "error";

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
  ariaLabel: string;
  headerTags: HeaderTag[];
  tableHeaders: [string, string, string];
  entries: SettingsDisclosureRow[];
  emptyDescription: string;
  icon?: Component;
}>();
</script>

<template>
  <details :id="props.id" class="section-panel settings-disclosure" :open="props.open">
    <summary class="section-heading settings-disclosure-summary disclosure-summary">
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
    <table
      v-if="props.entries.length"
      class="settings-list"
      :aria-label="props.ariaLabel"
    >
      <thead class="settings-table-head">
        <tr>
          <th scope="col">{{ props.tableHeaders[0] }}</th>
          <th scope="col">{{ props.tableHeaders[1] }}</th>
          <th scope="col">{{ props.tableHeaders[2] }}</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="entry in props.entries"
          :key="entry.key"
          class="settings-row"
        >
          <td>
            <strong>{{ entry.name }}</strong>
            <span>{{ entry.detail }}</span>
          </td>
          <td>
            <code v-if="entry.valueKind === 'code'">
              {{ entry.value }}
            </code>
            <span v-else :class="entry.valueClass">
              {{ entry.value }}
            </span>
          </td>
          <td>
            <n-tag size="small" :type="entry.tagType">
              {{ entry.tagLabel }}
            </n-tag>
          </td>
        </tr>
      </tbody>
    </table>
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
  width: 100%;
  margin-top: 14px;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  border-spacing: 0;
  background: var(--color-surface);
}

.settings-table-head {
  display: block;
  color: var(--color-muted-text);
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
  background: var(--color-table-head);
}

.settings-table-head tr,
.settings-row {
  display: grid;
  grid-template-columns: minmax(160px, 0.8fr) minmax(0, 1.2fr) minmax(102px, auto);
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 10px 12px;
  border-top: 1px solid var(--color-border-subtle);
}

.settings-table-head tr {
  border-top: 0;
}

.settings-table-head th {
  min-width: 0;
  padding: 0;
  text-align: left;
}

.settings-row td {
  min-width: 0;
  padding: 0;
}

.settings-row td:first-child {
  display: grid;
  gap: 3px;
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

.settings-row td:last-child :deep(.n-tag) {
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

  .settings-row td:last-child :deep(.n-tag) {
    width: fit-content;
  }
}
</style>

<script setup lang="ts">
import { NTag } from "naive-ui";

import { useSettingsSafety } from "./useSettingsSafety";

const {
  mutationsEnabled,
  mutationStatusIcon,
  mutationStatusLabel,
  mutationStatusDetail,
  mutationStatusTagType,
  restartTargetLabel,
} = useSettingsSafety();
</script>

<template>
  <div
    class="settings-safety-strip"
    :class="{ 'is-mutable': mutationsEnabled, 'is-read-only': !mutationsEnabled }"
  >
    <output class="settings-safety-main">
      <component :is="mutationStatusIcon" :size="18" aria-hidden="true" />
      <span>
        <strong class="wrap-anywhere">{{ mutationStatusLabel }}</strong>
        <span class="wrap-anywhere">{{ mutationStatusDetail }}</span>
      </span>
    </output>
    <div class="settings-safety-meta">
      <n-tag size="small" :type="mutationStatusTagType">
        {{ mutationStatusLabel }}
      </n-tag>
      <n-tag size="small">
        {{ restartTargetLabel }}
      </n-tag>
    </div>
  </div>
</template>

<style scoped>
.settings-safety-strip {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 14px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
}

.settings-safety-strip.is-read-only {
  border-color: color-mix(in srgb, var(--color-border) 72%, var(--color-operational-teal) 28%);
  background: color-mix(in srgb, var(--color-surface) 90%, var(--color-operational-teal) 10%);
}

.settings-safety-strip.is-mutable {
  border-color: color-mix(in srgb, var(--color-border) 68%, var(--color-warning) 32%);
  background: color-mix(in srgb, var(--color-surface) 86%, var(--color-warning-bg) 14%);
}

.settings-safety-main {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}

.settings-safety-main>svg {
  flex: 0 0 auto;
  margin-top: 2px;
  color: var(--color-operational-teal);
}

.settings-safety-strip.is-mutable .settings-safety-main>svg {
  color: var(--color-warning);
}

.settings-safety-main>span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.settings-safety-main strong,
.settings-safety-main>span,
.settings-safety-main>span>span,
.settings-safety-meta {
  min-width: 0;
}

.settings-safety-main>span>span {
  color: var(--color-text-secondary);
  font-size: 0.9rem;
  line-height: 1.45;
}

.settings-safety-meta {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

@media (--wud-compact) {
  .settings-safety-strip {
    display: grid;
  }

  .settings-safety-meta {
    justify-content: flex-start;
  }
}
</style>

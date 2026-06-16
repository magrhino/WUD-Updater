<script setup lang="ts">
import { scrollToElementId } from "./settingsDom";
import { SETTINGS_SECTION_LINKS } from "./settingsDisplay";
</script>

<template>
  <nav class="settings-jump-nav" aria-label="Settings sections">
    <button
      v-for="link in SETTINGS_SECTION_LINKS"
      :key="link.id"
      type="button"
      class="settings-jump-button"
      @click="scrollToElementId(link.id)"
    >
      {{ link.label }}
    </button>
  </nav>
</template>

<style scoped>
.settings-jump-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.settings-jump-button {
  min-height: 32px;
  padding: 0 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 999px;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font: inherit;
  font-size: 0.86rem;
  line-height: 1;
  cursor: pointer;
  transition:
    border-color 180ms ease-out,
    color 180ms ease-out,
    background-color 180ms ease-out;
}

.settings-jump-button:hover,
.settings-jump-button:focus-visible {
  border-color: var(--color-border-hover);
  background: var(--color-panel-tint);
  color: var(--color-ink);
}

.settings-jump-button:focus-visible {
  outline: 2px solid var(--color-border-hover);
  outline-offset: 2px;
}

@media (max-width: 560px) {
  .settings-jump-nav {
    flex-wrap: nowrap;
    max-width: 100%;
    overflow-x: auto;
    padding-bottom: 2px;
  }

  .settings-jump-button {
    flex: 0 0 auto;
    min-height: 44px;
  }
}
</style>

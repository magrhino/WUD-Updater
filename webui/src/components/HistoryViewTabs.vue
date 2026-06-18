<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, useRoute } from "vue-router";

const route = useRoute();
const activeView = computed(() => (route.name === "audit" ? "audit" : "runs"));

const historyViews = [
  { name: "runs", label: "All runs", to: { name: "runs" } },
  { name: "audit", label: "Audit log", to: { name: "audit" } },
];
</script>

<template>
  <nav class="history-view-tabs" aria-label="History views">
    <RouterLink
      v-for="view in historyViews"
      :key="view.name"
      :to="view.to"
      class="history-view-tab"
      :class="{ active: activeView === view.name }"
      :aria-current="activeView === view.name ? 'page' : undefined"
    >
      {{ view.label }}
    </RouterLink>
  </nav>
</template>

<style scoped>
.history-view-tabs {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  width: fit-content;
  margin: -2px 0 16px;
  padding: 4px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-panel-tint);
}

.history-view-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: 7px;
  color: var(--color-muted-text);
  font-size: 0.88rem;
  font-weight: 700;
  line-height: 1.2;
  transition:
    background-color var(--motion-base) var(--ease-out-quart),
    border-color var(--motion-base) var(--ease-out-quart),
    color var(--motion-base) var(--ease-out-quart);
}

.history-view-tab.active {
  border-color: var(--color-border-subtle);
  background: var(--color-surface);
  color: var(--color-ink);
}

.history-view-tab:hover {
  color: var(--color-ink);
}

.history-view-tab:focus-visible {
  outline: 2px solid var(--color-action-blue);
  outline-offset: 2px;
}

@media (--wud-app-shell) {
  .history-view-tabs {
    width: 100%;
  }

  .history-view-tab {
    flex: 1 1 0;
  }
}
</style>

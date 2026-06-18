<script setup lang="ts">
import { Search, X } from "@lucide/vue";
import { NButton, NInput } from "naive-ui";

defineProps<{
  active: boolean;
  query: string;
  resultLabel: string;
}>();

const emit = defineEmits<{
  clear: [];
  "update:query": [value: string];
}>();

function updateQuery(value: string): void {
  emit("update:query", value);
}
</script>

<template>
  <section class="pending-filter-panel" aria-label="Pending update search">
    <n-input
      :value="query"
      clearable
      class="pending-search-input"
      placeholder="Search stack, service, image, tag, digest, action, or release note"
      :input-props="{ 'aria-label': 'Search pending updates' }"
      @update:value="updateQuery"
    >
      <template #prefix>
        <Search :size="16" aria-hidden="true" />
      </template>
    </n-input>
    <span v-if="active" class="pending-filter-status">
      {{ resultLabel }}
    </span>
    <n-button
      v-if="active"
      size="small"
      quaternary
      @click="emit('clear')"
    >
      <template #icon>
        <X :size="16" />
      </template>
      Clear search
    </n-button>
  </section>
</template>

<style scoped>
.pending-filter-panel {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: var(--shadow-panel-lift);
}

.pending-search-input {
  flex: 1 1 320px;
  min-width: 180px;
}

.pending-filter-status {
  flex: 0 0 auto;
  color: var(--color-muted-text);
  font-size: 0.82rem;
}

@media (--wud-compact) {
  .pending-filter-panel {
    display: grid;
  }

  .pending-search-input {
    min-height: 44px;
  }
}
</style>

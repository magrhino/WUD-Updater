<script setup lang="ts">
import type { Component } from "vue";
import { LogOut, RefreshCw } from "@lucide/vue";
import { NButton, NFlex } from "naive-ui";

defineProps<{
  title: string;
  themeButtonTitle: string;
  themeButtonAriaLabel: string;
  themePreferenceIcon: Component;
}>();

defineEmits<{
  "cycle-theme": [];
  refresh: [];
  logout: [];
}>();
</script>

<template>
  <header class="topbar">
    <div>
      <h1>{{ title }}</h1>
    </div>
    <n-flex class="topbar-actions" align="center" :size="8">
      <n-button
        quaternary
        circle
        :title="themeButtonTitle"
        :aria-label="themeButtonAriaLabel"
        @click="$emit('cycle-theme')"
      >
        <template #icon>
          <component :is="themePreferenceIcon" :size="18" />
        </template>
      </n-button>
      <n-button
        quaternary
        circle
        title="Refresh"
        aria-label="Refresh current view"
        @click="$emit('refresh')"
      >
        <template #icon>
          <RefreshCw :size="18" />
        </template>
      </n-button>
      <n-button quaternary title="Sign out" @click="$emit('logout')">
        <template #icon>
          <LogOut :size="18" />
        </template>
        Sign out
      </n-button>
    </n-flex>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
}

.topbar h1 {
  margin: 0;
  color: var(--color-ink);
  font-size: 1.35rem;
  line-height: 1.2;
}

@media (max-width: 920px) {
  .topbar {
    align-items: flex-start;
  }
}

@media (max-width: 560px) {
  .topbar {
    display: grid;
  }

  .topbar-actions :deep(.n-button) {
    min-width: 44px;
    min-height: 44px;
  }

  .topbar-actions :deep(.n-button--circle) {
    min-width: 44px;
  }
}
</style>

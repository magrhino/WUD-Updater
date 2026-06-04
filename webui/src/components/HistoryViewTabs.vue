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

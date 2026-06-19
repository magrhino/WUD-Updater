<script setup lang="ts">
import { NGi, NGrid } from "naive-ui";

export type PreflightMetric = {
  label: string;
  value: string | number;
};

defineProps<{
  items: PreflightMetric[];
}>();
</script>

<template>
  <n-grid
    class="preflight-metrics"
    responsive="self"
    cols="2 560:4"
    :x-gap="8"
    :y-gap="8"
  >
    <n-gi v-for="item in items" :key="item.label">
      <div class="preflight-metric">
        <span>{{ item.label }}</span>
        <strong class="wrap-anywhere">{{ item.value }}</strong>
      </div>
    </n-gi>
  </n-grid>
</template>

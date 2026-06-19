<script setup lang="ts">
import { NAlert } from "naive-ui";

export type PreflightIssue = {
  severity: string;
  code: string;
  message: string;
  hint?: string;
  service_key?: string;
};

defineProps<{
  warnings: string[];
  issues: PreflightIssue[];
}>();

function alertType(severity: string): "error" | "info" | "warning" {
  if (severity === "error") {
    return "error";
  }
  if (severity === "info") {
    return "info";
  }
  return "warning";
}
</script>

<template>
  <div v-if="warnings.length || issues.length" class="preflight-notice-list">
    <n-alert
      v-for="warning in warnings"
      :key="warning"
      type="warning"
      :show-icon="false"
    >
      {{ warning }}
    </n-alert>
    <n-alert
      v-for="issue in issues"
      :key="`${issue.code}-${issue.service_key ?? ''}-${issue.message}`"
      :type="alertType(issue.severity)"
      :show-icon="false"
    >
      <span>{{ issue.message }}</span>
      <span v-if="issue.hint" class="issue-hint">{{ issue.hint }}</span>
    </n-alert>
  </div>
</template>

<style scoped>
.preflight-notice-list {
  display: grid;
  gap: 8px;
}
</style>

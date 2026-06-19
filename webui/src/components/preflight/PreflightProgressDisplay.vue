<script setup lang="ts">
import { NTag } from "naive-ui";

import type { ApplyJobProgressEvent } from "../../api/client";

defineProps<{
  active: boolean;
  progress: ApplyJobProgressEvent[];
  emptyMessage: string;
}>();
</script>

<template>
  <section
    v-if="active || progress.length"
    class="preflight-impact preflight-block"
    aria-labelledby="preflight-progress-title"
  >
    <div class="preflight-impact-heading">
      <strong id="preflight-progress-title">Preview progress</strong>
      <n-tag size="small" :type="active ? 'info' : 'success'">
        {{ active ? "Running" : "Complete" }}
      </n-tag>
    </div>
    <div v-if="progress.length" class="compact-list">
      <div
        v-for="item in progress"
        :key="`${item.phase}-${item.status}-${item.created_at}-${item.message}`"
        class="list-row"
      >
        <span>{{ item.phase }}</span>
        <strong>{{ item.status }}</strong>
        <em>{{ item.message }}</em>
      </div>
    </div>
    <p v-else class="preflight-summary-text">{{ emptyMessage }}</p>
  </section>
</template>

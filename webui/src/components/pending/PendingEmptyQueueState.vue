<script setup lang="ts">
import { CheckCircle2 } from "@lucide/vue";

withDefaults(defineProps<{
  pendingSourceLabel: string;
  latestRunId?: number | null;
  showSetupLink?: boolean;
}>(), {
  latestRunId: null,
  showSetupLink: false,
});
</script>

<template>
  <output
    class="empty-state clear-queue-state"
    aria-live="polite"
  >
    <span class="clear-queue-mark" aria-hidden="true">
      <CheckCircle2 :size="24" />
    </span>
    <strong>Update queue is clear</strong>
    <span>{{ pendingSourceLabel }} has no updates waiting for review.</span>
    <span v-if="showSetupLink">
      New WUD entries will appear here for stack selection and preflight review.
    </span>
    <RouterLink
      v-if="showSetupLink"
      class="text-link"
      to="/settings"
    >
      Open setup checklist
    </RouterLink>
    <RouterLink
      v-if="latestRunId"
      class="text-link"
      :to="{ name: 'run-detail', params: { id: latestRunId } }"
    >
      Review latest run #{{ latestRunId }}
    </RouterLink>
  </output>
</template>

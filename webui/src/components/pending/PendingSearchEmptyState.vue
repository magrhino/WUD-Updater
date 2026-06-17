<script setup lang="ts">
import { computed } from "vue";
import { X } from "@lucide/vue";
import { NButton } from "naive-ui";

const props = defineProps<{
  query: string;
}>();

const emit = defineEmits<{
  clear: [];
}>();

const trimmedQuery = computed(() => props.query.trim());
</script>

<template>
  <div class="empty-state pending-filter-empty-state" aria-live="polite">
    <strong>No pending updates match search</strong>
    <span class="wrap-anywhere">
      No stack, service, image, tag, digest, action, safety cue, or release-note text matched "{{ trimmedQuery }}".
    </span>
    <n-button size="small" secondary @click="emit('clear')">
      <template #icon>
        <X :size="16" />
      </template>
      Clear search
    </n-button>
  </div>
</template>

<style scoped>
.pending-filter-empty-state {
  gap: 8px;
  padding: 18px;
  text-align: center;
}

.pending-filter-empty-state span {
  max-width: 66ch;
  line-height: 1.45;
}
</style>

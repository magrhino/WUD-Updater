<script setup lang="ts">
import { NButton, NFlex } from "naive-ui";

defineProps<{
  primaryLabel?: string;
  primaryDisabled?: boolean;
  primaryLoading?: boolean;
  secondaryLabel?: string;
}>();

const emit = defineEmits<{
  primary: [];
  secondary: [];
}>();
</script>

<template>
  <n-flex class="preflight-footer" justify="flex-end" :size="8">
    <slot name="secondary">
      <n-button size="small" quaternary @click="$emit('secondary')">
        {{ secondaryLabel ?? "Close" }}
      </n-button>
    </slot>
    <slot />
    <slot name="primary">
      <n-button
        type="primary"
        size="small"
        :disabled="primaryDisabled ?? false"
        :loading="primaryLoading ?? false"
        @click="$emit('primary')"
      >
        {{ primaryLabel ?? "Apply" }}
      </n-button>
    </slot>
  </n-flex>
</template>
